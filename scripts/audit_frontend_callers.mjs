#!/usr/bin/env node
/**
 * PR1/A1.2 — frontend API caller inventory.
 *
 * Walks every `.ts` / `.tsx` under `frontend/src/`, finds every API call
 * site, and emits one row per call:
 *
 *   path_template, method, caller_file, caller_line, via_helper
 *
 * What we match:
 *   - api.{verb}<...>("/api/v1/...") and api.{verb}(`/api/v1/...${id}`)
 *     in `frontend/src/lib/api-client.ts` and `frontend/src/lib/chat-api.ts`
 *     (these are wrapper helpers — every call site that imports the named
 *     helper is a transitive caller).
 *   - direct `fetch("/api/v1/...")` anywhere.
 *   - `${API_BASE}/api/v1/...` template strings.
 *
 * Template-literal `${...}` segments are normalized to FastAPI's `{name}`
 * shape so the join with the backend inventory is one-to-one. We use a
 * heuristic: `${id}` → `{id}`, `${exerciseId}` → `{exercise_id}` (snake).
 *
 * Output: `docs/audits/api-callers.csv` (sorted by path_template).
 *
 * Usage:
 *   node scripts/audit_frontend_callers.mjs
 */

import { readdir, readFile, writeFile, mkdir } from "node:fs/promises";
import { join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const REPO = join(__filename, "..", "..");
const SRC_DIR = join(REPO, "frontend", "src");
const OUT_DIR = join(REPO, "docs", "audits");
const OUT_PATH = join(OUT_DIR, "api-callers.csv");

// `del` is a JS-friendly alias for DELETE used by `api.del(...)` in
// `frontend/src/lib/api-client.ts` (since `delete` is a reserved word in
// strict-mode object initializers in some toolchains).
const HTTP_VERBS = ["get", "post", "put", "patch", "delete", "del"];
const VERB_ALIAS = { del: "DELETE" };

/** Walk a directory recursively, yielding .ts / .tsx files. */
async function* walkSrc(dir) {
  const entries = await readdir(dir, { withFileTypes: true });
  for (const e of entries) {
    const p = join(dir, e.name);
    if (e.isDirectory()) {
      if (e.name === "node_modules" || e.name === ".next" || e.name.startsWith(".")) continue;
      yield* walkSrc(p);
    } else if (e.isFile()) {
      if (/\.(ts|tsx)$/.test(e.name) && !/\.d\.ts$/.test(e.name)) {
        yield p;
      }
    }
  }
}

/**
 * Normalize a path so it can be join-matched against the backend route
 * table. Three things happen:
 *
 *   1. Strip query string (`?limit=10`) — backend route table doesn't
 *      include query, so a leftover query mismatches a live route.
 *   2. Replace every `${expr}` template segment with the canonical
 *      placeholder `{*}` — the JS variable name (`id`, `conversationId`,
 *      `qs ? \`?...\` : ""`) bears no useful relation to the FastAPI
 *      param name (`{conversation_id}`), so the join must be shape-based
 *      not name-based. We do the same substitution on the backend side
 *      in `audit_join.py` so the keys actually meet.
 *   3. Trim trailing slash so `/foo` and `/foo/` match.
 */
function normalizePath(raw) {
  // Detect "query-shaped" trailing interpolations like
  //   `/api/v1/path${qs ? `?${qs}` : ""}`
  // — the giveaway is that the interpolation expression itself contains
  // a literal `?`. Real path params don't.
  let s = raw;
  s = s.replace(/\$\{([\s\S]*?)\}(?=$)/g, (_, expr) => (expr.includes("?") ? "" : "{*}"));
  return (
    s
      // Replace any remaining ${...} expression with the canonical
      // placeholder.
      .replace(/\$\{[\s\S]*?\}/g, "{*}")
      // Strip literal query string.
      .replace(/\?.*$/, "")
      // Trim trailing slashes for canonical form.
      .replace(/\/+$/, "")
  );
}

/**
 * Read the string literal that begins at `source[start]` (which must be
 * a quote / backtick) and return [content, endIndexExclusive].
 *
 * Handles double-quote, single-quote, and backtick. For backtick, walks
 * through nested `${...}` expressions correctly (counting brace depth)
 * so the contents survive cases like:
 *
 *   `/api/v1/chat/conversations${qs ? `?${qs}` : ""}`
 *
 * which a naive regex would split on the first inner backtick.
 *
 * Returns null if the literal is unterminated.
 */
function readStringLiteral(source, start) {
  const quote = source[start];
  if (quote !== '"' && quote !== "'" && quote !== "`") return null;
  let i = start + 1;
  let out = "";
  while (i < source.length) {
    const ch = source[i];
    if (ch === "\\") {
      out += ch + source[i + 1];
      i += 2;
      continue;
    }
    if (quote === "`" && ch === "$" && source[i + 1] === "{") {
      // Walk through the entire ${...} expression including any nested
      // strings or further ${...} blocks. We append everything we walk
      // verbatim — `normalizePath` later turns the whole thing into the
      // `{*}` placeholder.
      out += "${";
      i += 2;
      let depth = 1;
      while (i < source.length && depth > 0) {
        const c = source[i];
        if (c === "`" || c === '"' || c === "'") {
          // Skip a nested string literal so its braces / quotes don't
          // confuse the depth counter.
          const inner = readStringLiteral(source, i);
          if (inner) {
            out += source.slice(i, inner[1]);
            i = inner[1];
            continue;
          }
        }
        if (c === "{") depth += 1;
        else if (c === "}") depth -= 1;
        out += c;
        i += 1;
      }
      continue;
    }
    if (ch === quote) {
      return [out, i + 1];
    }
    out += ch;
    i += 1;
  }
  return null;
}

/**
 * Pull every match of:
 *   api.<verb><...>("/api/v1/...")           // double-quoted literal
 *   api.<verb><...>(`/api/v1/...${id}`)      // backtick template
 *   fetch("/api/v1/...")
 *   fetch(`${API_BASE}/api/v1/...`)
 *
 * For each match return { method, path_template, line, via_helper }.
 */
function* extractCalls(source, file) {
  // 1) api.<verb>(...) — find the call site, then read the first string
  // argument with the bracket-aware reader so nested templates work.
  const apiVerbAlt = HTTP_VERBS.join("|");
  const apiHead = new RegExp(
    `\\bapi\\.(${apiVerbAlt})(?:<[^>]*>)?\\s*\\(\\s*`,
    "g",
  );
  let m;
  while ((m = apiHead.exec(source))) {
    const verb = m[1];
    const argStart = m.index + m[0].length;
    const lit = readStringLiteral(source, argStart);
    if (!lit) continue;
    const raw = lit[0];
    if (!raw.includes("/api/v1") && !raw.includes("/health")) continue;
    const lineNo = source.slice(0, m.index).split("\n").length;
    const method = (VERB_ALIAS[verb.toLowerCase()] || verb).toUpperCase();
    yield {
      method,
      path_template: normalizePath(raw),
      line: lineNo,
      via_helper:
        file.includes("api-client") || file.includes("chat-api")
          ? "wrapper"
          : "direct",
    };
  }
  // Reset for the second regex (V8 keeps lastIndex across calls when
  // we share the regex instance, but we built a fresh one each pass.)

  // 2) Bare fetch calls hitting /api/v1
  const fetchHead = /\bfetch\s*\(\s*/g;
  while ((m = fetchHead.exec(source))) {
    const argStart = m.index + m[0].length;
    const lit = readStringLiteral(source, argStart);
    if (!lit) continue;
    const raw = lit[0];
    if (!raw.includes("/api/v1") && !raw.includes("/health")) continue;
    const lineNo = source.slice(0, m.index).split("\n").length;
    const window_ = source.slice(m.index, m.index + 320);
    const methodMatch = /method:\s*['"`](GET|POST|PUT|PATCH|DELETE)['"`]/.exec(
      window_,
    );
    yield {
      method: methodMatch ? methodMatch[1] : "GET",
      path_template: normalizePath(raw.replace(/^\$\{[^}]+\}/, "")),
      line: lineNo,
      via_helper: "fetch",
    };
  }
}

async function main() {
  const callers = [];
  for await (const file of walkSrc(SRC_DIR)) {
    let src;
    try {
      src = await readFile(file, "utf8");
    } catch {
      continue;
    }
    if (!src.includes("/api/v1") && !src.includes("/health")) continue;
    const rel = relative(REPO, file).split(sep).join("/");
    for (const call of extractCalls(src, rel)) {
      callers.push({
        path_template: call.path_template,
        method: call.method,
        caller_file: rel,
        caller_line: call.line,
        via_helper: call.via_helper,
      });
    }
  }

  callers.sort((a, b) => {
    if (a.path_template !== b.path_template) return a.path_template < b.path_template ? -1 : 1;
    if (a.method !== b.method) return a.method < b.method ? -1 : 1;
    if (a.caller_file !== b.caller_file) return a.caller_file < b.caller_file ? -1 : 1;
    return a.caller_line - b.caller_line;
  });

  await mkdir(OUT_DIR, { recursive: true });
  const header = "path_template,method,caller_file,caller_line,via_helper\n";
  const body = callers
    .map((r) =>
      [r.path_template, r.method, r.caller_file, r.caller_line, r.via_helper].join(","),
    )
    .join("\n");
  await writeFile(OUT_PATH, header + body + "\n", "utf8");

  console.log(`[audit_frontend_callers] wrote ${callers.length} rows -> ${OUT_PATH}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
