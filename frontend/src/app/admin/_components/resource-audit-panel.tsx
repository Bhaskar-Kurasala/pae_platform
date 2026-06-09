"use client";

/**
 * <ResourceAuditPanel> — reusable audit-trail strip for any admin
 * detail surface (student modal, course edit, agent detail, coupon,
 * bundle).
 *
 * Theme-aware: matches the cockpit's light (warm cream) or dark
 * (deep forest) palette. Drops cleanly into any modal/page that
 * already commits to the v8.css token set.
 *
 * Reads from useAdminAuditLog({ resource_type, resource_id }). One
 * row per entry; click to expand a before/after diff (or extra
 * metadata when no diff is present). Two action types get special
 * treatment:
 *   • outreach.send       → renders body_preview as a quoted block
 *   • auth.admin_login    → renders ip_address inline (mono)
 */

import { useMemo, useState } from "react";
import { RefreshCw, ChevronRight } from "lucide-react";
import Link from "next/link";
import {
  useAdminAuditLog,
  type AdminAuditEntry,
} from "@/lib/hooks/use-admin";

export interface ResourceAuditPanelProps {
  resourceType: "user" | "course" | "agent" | "coupon" | "bundle";
  resourceId: string;
  pageTheme?: "light" | "dark";
  limit?: number;
  title?: string;
  emptyMessage?: string;
}

// ── Action-type → category color map ──────────────────────────────
// Mirrors the audit-log page palette so chips read consistently
// across surfaces. Hex picked from v8.css.
type Category =
  | "course"
  | "coupon"
  | "bundle"
  | "feedback"
  | "outreach"
  | "auth"
  | "agent"
  | "default";

const CATEGORY_COLORS: Record<
  Category,
  { bg: string; fg: string; bgDark: string; fgDark: string }
> = {
  course:   { bg: "rgba(31,79,55,0.12)",  fg: "#1f4f37", bgDark: "rgba(95,163,127,0.18)", fgDark: "#8fd6b1" }, // teal/forest
  coupon:   { bg: "rgba(124,58,237,0.14)", fg: "#5b21b6", bgDark: "rgba(167,139,250,0.20)", fgDark: "#c4b5fd" }, // purple
  bundle:   { bg: "rgba(37,99,235,0.12)",  fg: "#1d4ed8", bgDark: "rgba(96,165,250,0.20)", fgDark: "#93c5fd" }, // blue
  feedback: { bg: "rgba(214,165,77,0.18)", fg: "#8a5d10", bgDark: "rgba(232,190,114,0.22)", fgDark: "#e8be72" }, // amber/gold
  outreach: { bg: "rgba(192,97,79,0.14)",  fg: "#a23f31", bgDark: "rgba(217,98,82,0.20)",  fgDark: "#f0a094" }, // red/rose
  auth:     { bg: "rgba(53,109,80,0.10)",  fg: "#356d50", bgDark: "rgba(143,214,177,0.16)", fgDark: "#a8dcc0" }, // eyebrow
  agent:    { bg: "rgba(79,70,229,0.12)",  fg: "#3730a3", bgDark: "rgba(129,140,248,0.20)", fgDark: "#a5b4fc" }, // indigo
  default:  { bg: "rgba(26,38,32,0.07)",   fg: "#7a7565", bgDark: "rgba(255,255,255,0.08)", fgDark: "#c4baa6" }, // muted
};

function categoryOf(actionType: string): Category {
  const t = actionType.toLowerCase();
  if (t.startsWith("course")) return "course";
  if (t.startsWith("coupon")) return "coupon";
  if (t.startsWith("bundle")) return "bundle";
  if (t.startsWith("feedback")) return "feedback";
  if (t.startsWith("outreach")) return "outreach";
  if (t.startsWith("auth")) return "auth";
  if (t.startsWith("agent")) return "agent";
  return "default";
}

// ── Relative time helper ─────────────────────────────────────────
function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  const now = Date.now();
  const diff = Math.max(0, Math.floor((now - then) / 1000));
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  if (diff < 86400 * 30) return `${Math.floor(diff / 86400)}d ago`;
  if (diff < 86400 * 365) return `${Math.floor(diff / 86400 / 30)}mo ago`;
  return `${Math.floor(diff / 86400 / 365)}y ago`;
}

// ── Compute changed-field diff ────────────────────────────────────
function diffEntries(
  before: Record<string, unknown> | null,
  after: Record<string, unknown> | null,
): Array<{ key: string; from: unknown; to: unknown }> {
  if (!before && !after) return [];
  const keys = new Set([
    ...Object.keys(before ?? {}),
    ...Object.keys(after ?? {}),
  ]);
  const out: Array<{ key: string; from: unknown; to: unknown }> = [];
  for (const k of keys) {
    const a = before?.[k];
    const b = after?.[k];
    if (JSON.stringify(a) !== JSON.stringify(b)) {
      out.push({ key: k, from: a, to: b });
    }
  }
  return out;
}

function renderValue(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  try {
    return JSON.stringify(v);
  } catch {
    return String(v);
  }
}

export function ResourceAuditPanel({
  resourceType,
  resourceId,
  pageTheme = "light",
  limit = 20,
  title = "Audit trail",
  emptyMessage = "No admin actions recorded for this resource yet.",
}: ResourceAuditPanelProps) {
  const isDark = pageTheme === "dark";
  const [expanded, setExpanded] = useState<string | null>(null);

  const { data, isLoading, isError, refetch, isFetching } = useAdminAuditLog({
    resource_type: resourceType,
    resource_id: resourceId,
  });

  const items = useMemo(
    () => (data ?? []).slice(0, limit),
    [data, limit],
  );
  const hasMore = (data?.length ?? 0) >= limit;

  // Palette tokens — match v8 / student-modal surface system.
  const tokens = isDark
    ? {
        ink: "#f7f2e8",
        ink2: "#d6cebf",
        muted: "#c4baa6",
        muted2: "#9a9382",
        eyebrow: "#c8b88d",
        eyebrowDot: "#d96252",
        rowBg: "rgba(255,255,255,0.03)",
        rowBgHover: "rgba(255,255,255,0.06)",
        line: "rgba(255,255,255,0.09)",
        accent: "#8fd6b1",
        quote: "rgba(217,98,82,0.10)",
        quoteBorder: "rgba(217,98,82,0.30)",
      }
    : {
        ink: "#1a2620",
        ink2: "#3a3a3a",
        muted: "#7a7565",
        muted2: "#a39d8d",
        eyebrow: "#356d50",
        eyebrowDot: "#4e9470",
        rowBg: "rgba(255,255,255,0.55)",
        rowBgHover: "rgba(255,255,255,0.85)",
        line: "#e7decd",
        accent: "#1f4f37",
        quote: "rgba(192,97,79,0.06)",
        quoteBorder: "rgba(192,97,79,0.25)",
      };

  const moreHref = `/admin/audit-log?resource_type=${encodeURIComponent(
    resourceType,
  )}&resource_id=${encodeURIComponent(resourceId)}`;

  return (
    <section className="cf-rap-root">
      <style>{`
        .cf-rap-root {
          margin-top: 24px;
          font-family: var(--font-inter), 'Inter', system-ui, sans-serif;
          color: ${tokens.ink};
        }
        .cf-rap-header {
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          gap: 16px;
          margin-bottom: 14px;
        }
        .cf-rap-title {
          font-family: var(--font-fraunces), 'Fraunces', Georgia, serif;
          font-size: 16px;
          font-weight: 500;
          letter-spacing: -0.02em;
          line-height: 1.2;
          color: ${tokens.ink};
          margin: 0;
        }
        .cf-rap-sub {
          font-size: 11px;
          color: ${tokens.muted};
          margin-top: 3px;
          letter-spacing: 0.01em;
        }
        .cf-rap-refresh {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          width: 28px; height: 28px;
          border-radius: 999px;
          border: 1px solid ${tokens.line};
          background: ${tokens.rowBg};
          color: ${tokens.muted};
          transition: background .15s, color .15s, transform .2s;
          cursor: pointer;
        }
        .cf-rap-refresh:hover { background: ${tokens.rowBgHover}; color: ${tokens.ink}; }
        .cf-rap-refresh:disabled { opacity: 0.6; cursor: default; }
        .cf-rap-refresh.spinning svg { animation: cf-rap-spin 1s linear infinite; }
        @keyframes cf-rap-spin { to { transform: rotate(360deg); } }

        .cf-rap-list {
          display: flex;
          flex-direction: column;
          gap: 6px;
          list-style: none;
          padding: 0;
          margin: 0;
        }
        .cf-rap-row {
          background: ${tokens.rowBg};
          border: 1px solid ${tokens.line};
          border-radius: 12px;
          padding: 10px 14px;
          cursor: pointer;
          transition: background .18s, border-color .18s;
        }
        .cf-rap-row:hover {
          background: ${tokens.rowBgHover};
          border-color: ${isDark ? "rgba(143,214,177,0.25)" : "rgba(78,148,112,0.25)"};
        }
        .cf-rap-row-top {
          display: flex;
          align-items: center;
          gap: 10px;
          flex-wrap: wrap;
        }
        .cf-rap-chip {
          display: inline-flex;
          align-items: center;
          font-size: 11px;
          font-weight: 700;
          letter-spacing: 0.12em;
          text-transform: uppercase;
          padding: 3px 8px;
          border-radius: 999px;
          flex-shrink: 0;
        }
        .cf-rap-time {
          font-family: var(--font-jetbrains-mono), ui-monospace, monospace;
          font-size: 11px;
          letter-spacing: 0.04em;
          color: ${tokens.muted2};
          font-feature-settings: "tnum";
          flex-shrink: 0;
        }
        .cf-rap-admin {
          font-family: var(--font-jetbrains-mono), ui-monospace, monospace;
          font-size: 11px;
          color: ${tokens.muted};
          flex: 1;
          min-width: 0;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .cf-rap-chev {
          color: ${tokens.muted2};
          transition: transform .2s;
          flex-shrink: 0;
        }
        .cf-rap-chev.open { transform: rotate(90deg); }
        .cf-rap-summary {
          font-size: 13px;
          line-height: 1.5;
          color: ${tokens.ink};
          margin: 6px 0 0;
          letter-spacing: -0.005em;
        }
        .cf-rap-detail {
          margin-top: 10px;
          padding-top: 10px;
          border-top: 1px dashed ${tokens.line};
        }
        .cf-rap-quote {
          font-style: italic;
          padding: 8px 12px;
          border-left: 3px solid ${tokens.quoteBorder};
          background: ${tokens.quote};
          border-radius: 6px;
          font-size: 13px;
          line-height: 1.5;
          color: ${tokens.ink2};
          max-height: 100px;
          overflow-y: auto;
          margin: 0;
          white-space: pre-wrap;
        }
        .cf-rap-ip {
          font-family: var(--font-jetbrains-mono), ui-monospace, monospace;
          font-size: 12px;
          padding: 2px 6px;
          border-radius: 4px;
          background: ${isDark ? "rgba(255,255,255,0.06)" : "rgba(26,38,32,0.06)"};
          color: ${tokens.ink};
        }
        .cf-rap-dl {
          display: grid;
          grid-template-columns: minmax(120px, max-content) 1fr;
          gap: 4px 16px;
          margin: 0;
          font-size: 12px;
        }
        .cf-rap-dl dt {
          font-family: var(--font-jetbrains-mono), ui-monospace, monospace;
          font-size: 11px;
          color: ${tokens.muted};
          letter-spacing: 0.02em;
        }
        .cf-rap-dl dd {
          margin: 0;
          color: ${tokens.ink};
          font-size: 12px;
          line-height: 1.5;
          word-break: break-word;
        }
        .cf-rap-diff-from {
          color: ${isDark ? "#f0a094" : "#a23f31"};
          text-decoration: line-through;
          text-decoration-color: ${isDark ? "rgba(240,160,148,0.45)" : "rgba(162,63,49,0.45)"};
        }
        .cf-rap-diff-arrow {
          color: ${tokens.muted2};
          margin: 0 6px;
        }
        .cf-rap-diff-to {
          color: ${tokens.accent};
          font-weight: 500;
        }
        .cf-rap-meta-label {
          display: inline-block;
          font-family: var(--font-jetbrains-mono), ui-monospace, monospace;
          font-size: 10px;
          letter-spacing: 0.16em;
          text-transform: uppercase;
          color: ${tokens.muted};
          margin-right: 6px;
        }
        .cf-rap-empty, .cf-rap-error {
          font-size: 13px;
          color: ${tokens.muted};
          font-style: italic;
          padding: 14px 0;
        }
        .cf-rap-skeleton {
          height: 44px;
          border-radius: 12px;
          background: linear-gradient(90deg, ${tokens.rowBg} 0%, ${tokens.rowBgHover} 50%, ${tokens.rowBg} 100%);
          background-size: 200% 100%;
          animation: cf-rap-shimmer 1.5s ease-in-out infinite;
        }
        @keyframes cf-rap-shimmer {
          0% { background-position: 200% 0; }
          100% { background-position: -200% 0; }
        }
        .cf-rap-more {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          margin-top: 10px;
          font-size: 12px;
          font-weight: 500;
          color: ${tokens.eyebrow};
          text-decoration: none;
          letter-spacing: -0.005em;
        }
        .cf-rap-more:hover { text-decoration: underline; }
      `}</style>

      <header className="cf-rap-header">
        <div>
          <h3 className="cf-rap-title">{title}</h3>
          <div className="cf-rap-sub">
            Recent admin actions on this {resourceType}
          </div>
        </div>
        <button
          type="button"
          onClick={() => refetch()}
          disabled={isFetching}
          className={`cf-rap-refresh${isFetching ? " spinning" : ""}`}
          aria-label="Refresh audit trail"
          title="Refresh"
        >
          <RefreshCw size={13} />
        </button>
      </header>

      {isLoading ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <div className="cf-rap-skeleton" />
          <div className="cf-rap-skeleton" />
          <div className="cf-rap-skeleton" />
        </div>
      ) : isError ? (
        <div className="cf-rap-error">Couldn&apos;t load audit trail.</div>
      ) : items.length === 0 ? (
        <div className="cf-rap-empty">{emptyMessage}</div>
      ) : (
        <>
          <ol className="cf-rap-list">
            {items.map((entry) => (
              <AuditRow
                key={entry.id}
                entry={entry}
                expanded={expanded === entry.id}
                onToggle={() =>
                  setExpanded((prev) => (prev === entry.id ? null : entry.id))
                }
                isDark={isDark}
              />
            ))}
          </ol>
          {hasMore && (
            <Link className="cf-rap-more" href={moreHref}>
              View more in audit log
              <ChevronRight size={12} />
            </Link>
          )}
        </>
      )}
    </section>
  );
}

interface AuditRowProps {
  entry: AdminAuditEntry;
  expanded: boolean;
  onToggle: () => void;
  isDark: boolean;
}

function AuditRow({ entry, expanded, onToggle, isDark }: AuditRowProps) {
  const cat = categoryOf(entry.action_type);
  const color = CATEGORY_COLORS[cat];
  const chipBg = isDark ? color.bgDark : color.bg;
  const chipFg = isDark ? color.fgDark : color.fg;

  const diff = useMemo(
    () => diffEntries(entry.before, entry.after),
    [entry.before, entry.after],
  );

  const extra = (entry.extra ?? {}) as Record<string, unknown>;
  const bodyPreview =
    entry.action_type === "outreach.send"
      ? (extra.body_preview as string | undefined) ?? null
      : null;
  const ipAddress =
    entry.action_type === "auth.admin_login"
      ? (extra.ip_address as string | undefined) ?? null
      : null;

  return (
    <li
      className="cf-rap-row"
      onClick={onToggle}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onToggle();
        }
      }}
    >
      <div className="cf-rap-row-top">
        <span
          className="cf-rap-chip"
          style={{ background: chipBg, color: chipFg }}
        >
          {entry.action_type}
        </span>
        <span
          className="cf-rap-time"
          title={new Date(entry.created_at).toUTCString()}
        >
          {relativeTime(entry.created_at)}
        </span>
        <span className="cf-rap-admin">{entry.admin_email}</span>
        {ipAddress && <span className="cf-rap-ip">{ipAddress}</span>}
        <ChevronRight
          size={14}
          className={`cf-rap-chev${expanded ? " open" : ""}`}
        />
      </div>
      <p className="cf-rap-summary">{entry.summary}</p>

      {expanded && (
        <div className="cf-rap-detail" onClick={(e) => e.stopPropagation()}>
          {bodyPreview && (
            <blockquote className="cf-rap-quote">{bodyPreview}</blockquote>
          )}
          {diff.length > 0 ? (
            <dl className="cf-rap-dl">
              {diff.map(({ key, from, to }) => (
                <RowDiff key={key} field={key} from={from} to={to} />
              ))}
            </dl>
          ) : (
            !bodyPreview &&
            Object.keys(extra).length > 0 && (
              <dl className="cf-rap-dl">
                {Object.entries(extra).map(([k, v]) => (
                  <RowMeta key={k} field={k} value={v} />
                ))}
              </dl>
            )
          )}
        </div>
      )}
    </li>
  );
}

function RowDiff({
  field,
  from,
  to,
}: {
  field: string;
  from: unknown;
  to: unknown;
}) {
  return (
    <>
      <dt>{field}</dt>
      <dd>
        <span className="cf-rap-diff-from">{renderValue(from)}</span>
        <span className="cf-rap-diff-arrow">→</span>
        <span className="cf-rap-diff-to">{renderValue(to)}</span>
      </dd>
    </>
  );
}

function RowMeta({ field, value }: { field: string; value: unknown }) {
  return (
    <>
      <dt>{field}</dt>
      <dd>{renderValue(value)}</dd>
    </>
  );
}
