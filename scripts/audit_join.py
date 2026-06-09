"""PR1/A1.3 — join the backend endpoint inventory with the frontend
caller inventory and emit `docs/audits/endpoint-coverage.md`.

The join key is `(method, path_template)`. Path normalization is done
in the upstream scripts; here we just match strings.

Output is a markdown table grouped by handler, with a verdict column:
  - live           — at least one frontend caller
  - dead           — zero callers, public route (likely deletable)
  - legacy-redirect — file is a redirect stub (the route deleted itself)
  - webhook-only   — provider POSTs to it; no frontend caller expected
  - admin-only     — under /api/v1/admin (called from admin UI; some
                     are intentionally backend-only)
  - oauth-callback — OAuth provider redirects; no frontend caller
  - health         — operational, not user-facing
  - manual-triage  — neither caller nor heuristic match — needs human

The triage column at the right is left blank; you fill it in by hand
when reviewing the dead list before deletions.

Usage:
    python scripts/audit_join.py
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ENDPOINTS_CSV = REPO / "docs" / "audits" / "endpoints.csv"
CALLERS_CSV = REPO / "docs" / "audits" / "api-callers.csv"
OUT_PATH = REPO / "docs" / "audits" / "endpoint-coverage.md"


@dataclass
class Endpoint:
    method: str
    path: str
    tag: str
    handler: str
    file: str
    line: int


@dataclass
class Caller:
    method: str
    path: str
    caller_file: str
    caller_line: int
    via_helper: str


_PARAM_RE = __import__("re").compile(r"\{[^}]+\}")


def _shape_key(path: str) -> str:
    """Normalize a path to its shape — every {param} becomes {*}, and a
    trailing slash is stripped. The frontend caller scanner produces the
    same shape so the join is one-to-one regardless of param naming."""
    canonical = _PARAM_RE.sub("{*}", path)
    if canonical.endswith("/") and len(canonical) > 1:
        canonical = canonical.rstrip("/")
    return canonical


def _classify(ep: Endpoint, callers: list[Caller]) -> str:
    if callers:
        return "live"
    if ep.path.startswith("/health"):
        return "health"
    if ep.path.startswith("/api/v1/webhooks/") or "webhook" in ep.handler.lower():
        return "webhook-only"
    if ep.path.startswith("/api/v1/admin/"):
        return "admin-only"
    if "oauth" in ep.path.lower() or "callback" in ep.handler.lower():
        return "oauth-callback"
    return "dead"


def _load_endpoints() -> list[Endpoint]:
    rows: list[Endpoint] = []
    with ENDPOINTS_CSV.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            rows.append(
                Endpoint(
                    method=r["method"],
                    path=r["path"],
                    tag=r["tag"],
                    handler=r["handler"],
                    file=r["file"],
                    line=int(r["line"]),
                )
            )
    return rows


def _load_callers() -> dict[tuple[str, str], list[Caller]]:
    by_key: dict[tuple[str, str], list[Caller]] = defaultdict(list)
    with CALLERS_CSV.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            # Frontend script already emits `{*}` for template params, but
            # we apply `_shape_key` defensively in case a hand-crafted
            # caller slipped through with a literal `{id}` or trailing /.
            key = (r["method"], _shape_key(r["path_template"]))
            by_key[key].append(
                Caller(
                    method=r["method"],
                    path=r["path_template"],
                    caller_file=r["caller_file"],
                    caller_line=int(r["caller_line"]),
                    via_helper=r["via_helper"],
                )
            )
    return by_key


def main() -> int:
    if not ENDPOINTS_CSV.exists() or not CALLERS_CSV.exists():
        print(
            "[audit_join] missing inventory CSVs — run audit_endpoints.py and "
            "audit_frontend_callers.mjs first",
            file=sys.stderr,
        )
        return 1

    endpoints = _load_endpoints()
    callers_by_key = _load_callers()

    rows: list[tuple[Endpoint, list[Caller], str]] = []
    for ep in endpoints:
        callers = callers_by_key.get((ep.method, _shape_key(ep.path)), [])
        rows.append((ep, callers, _classify(ep, callers)))

    # Counts
    counts: dict[str, int] = defaultdict(int)
    for _, _, verdict in rows:
        counts[verdict] += 1

    # Group by handler-file basename for readability
    grouped: dict[str, list] = defaultdict(list)
    for ep, callers, verdict in rows:
        key = ep.file.rsplit("/", 1)[-1].replace(".py", "")
        grouped[key].append((ep, callers, verdict))

    # Build markdown
    out: list[str] = []
    out.append("# Endpoint coverage report\n")
    out.append(
        "Generated by `scripts/audit_join.py`. Joins `endpoints.csv` "
        "(backend) with `api-callers.csv` (frontend).\n"
    )
    out.append("## Summary\n")
    out.append("| Verdict | Count |")
    out.append("|---|---|")
    for v in (
        "live",
        "dead",
        "admin-only",
        "webhook-only",
        "oauth-callback",
        "health",
    ):
        out.append(f"| {v} | {counts.get(v, 0)} |")
    out.append(f"| **Total** | **{len(rows)}** |\n")

    out.append("## Action items\n")
    dead = [r for r in rows if r[2] == "dead"]
    if dead:
        out.append(
            f"**{len(dead)} routes have zero frontend callers** and are not "
            "webhook / admin / oauth / health. These are deletion candidates "
            "for PR2/A2.2 — review each one against any in-flight feature work "
            "before flipping the verdict to **delete**.\n"
        )
    else:
        out.append("No dead routes detected. Nice.\n")

    # Per-file detail
    out.append("## By file\n")
    for fname in sorted(grouped):
        out.append(f"### `{fname}.py`\n")
        out.append("| Method | Path | Handler | Verdict | Callers | Triage |")
        out.append("|---|---|---|---|---|---|")
        for ep, callers, verdict in grouped[fname]:
            caller_summary = (
                ", ".join(
                    f"`{c.caller_file.split('/')[-1]}:{c.caller_line}`"
                    for c in callers[:3]
                )
                + (f" +{len(callers) - 3} more" if len(callers) > 3 else "")
            )
            badge = {
                "live": "✅ live",
                "dead": "🚨 **dead**",
                "admin-only": "🛠 admin-only",
                "webhook-only": "🪝 webhook-only",
                "oauth-callback": "🔑 oauth",
                "health": "❤ health",
            }.get(verdict, verdict)
            out.append(
                f"| {ep.method} | `{ep.path}` | `{ep.handler}` | {badge} | "
                f"{caller_summary or '—'} |  |"
            )
        out.append("")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text("\n".join(out), encoding="utf-8")
    print(
        f"[audit_join] wrote coverage report -> {OUT_PATH} "
        f"(live={counts.get('live', 0)}, dead={counts.get('dead', 0)})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
