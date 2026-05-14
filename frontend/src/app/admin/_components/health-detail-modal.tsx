"use client";

/**
 * <HealthDetailModal> — focused popup that opens when an operator
 * clicks a tile in <HealthStrip>. Mirrors student-detail-modal's
 * base-ui Dialog primitive, palette, typography, and close behavior.
 *
 * For now, top_confusion + worst_lessons render real data (reusing
 * the same endpoints /admin/content already consumes). The other
 * four keys show placeholder copy until their endpoints land.
 */

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Dialog as DialogPrimitive } from "@base-ui/react/dialog";
import { X } from "lucide-react";
import { api } from "@/lib/api-client";
import {
  useAdminFeedback,
  useConfusionHeatmap,
  useResolveFeedback,
} from "@/lib/hooks/use-admin";

type MetricKey =
  | "revenue_at_risk"
  | "review_queue"
  | "top_confusion"
  | "worst_lessons"
  | "stale_students"
  | "open_feedback"
  | "cohort_delta";

interface HealthDetailModalProps {
  open: boolean;
  metricKey: MetricKey | string | null;
  onClose: () => void;
  pageTheme?: "light" | "dark";
}

const PRETTY: Record<string, string> = {
  revenue_at_risk: "Revenue at risk",
  review_queue: "Review queue",
  top_confusion: "Top confusion",
  worst_lessons: "Worst lessons",
  stale_students: "Stale students",
  open_feedback: "Open feedback",
  cohort_delta: "Cohort delta",
};

const DESCRIPTIONS: Record<string, string> = {
  revenue_at_risk:
    "Sum of MRR tied to paid students currently flagged as at-risk by the retention engine.",
  review_queue:
    "Items waiting on admin review — flagged submissions, refund offers, and outreach acknowledgements.",
  stale_students:
    "Students with no platform activity inside the staleness window who would normally be active.",
  cohort_delta:
    "Week-over-week movement in cohort health: activation, completion, and revenue blended into one trend.",
};

export function HealthDetailModal({
  open,
  metricKey,
  onClose,
  pageTheme = "light",
}: HealthDetailModalProps) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const isDark = pageTheme === "dark";

  useEffect(() => {
    if (!open) return;
    const html = document.documentElement;
    const body = document.body;
    const had = html.classList.contains("dark");
    if (isDark) html.classList.add("dark");
    body.setAttribute("data-cf-health-modal-theme", pageTheme);
    return () => {
      if (!had) html.classList.remove("dark");
      body.removeAttribute("data-cf-health-modal-theme");
    };
  }, [open, isDark, pageTheme]);

  const surface = isDark
    ? {
        bgGradient:
          "linear-gradient(135deg, #19241e 0%, #243128 55%, #2d3d31 100%)",
        cardBg: "rgba(255,255,255,0.05)",
        cardBorder: "rgba(255,255,255,0.09)",
        ink: "#f7f2e8",
        ink2: "#d6cebf",
        muted: "#c4baa6",
        eyebrow: "#c8b88d",
        eyebrowDot: "#d96252",
        accent: "#5fa37f",
        accentSoft: "rgba(95,163,127,0.18)",
        gold: "#e8be72",
        line: "rgba(255,255,255,0.09)",
        borderTop: "rgba(255,255,255,0.06)",
        ring: "rgba(255,255,255,0.04)",
        backdrop: "rgba(0,0,0,0.65)",
      }
    : {
        bgGradient:
          "radial-gradient(ellipse 120% 80% at 20% 0%, #fdfaf3, #f7f3ea 55%, #efe9d9 100%)",
        cardBg: "rgba(255,255,255,0.92)",
        cardBorder: "#e7decd",
        ink: "#1a2620",
        ink2: "#3a3a3a",
        muted: "#7a7565",
        eyebrow: "#356d50",
        eyebrowDot: "#4e9470",
        accent: "#1f4f37",
        accentSoft: "rgba(95,163,127,0.14)",
        gold: "#d6a54d",
        line: "#e7decd",
        borderTop: "rgba(255,255,255,0.8)",
        ring: "rgba(26,38,32,0.06)",
        backdrop: "rgba(8,12,10,0.28)",
      };

  const keyStr = (metricKey ?? "") as string;
  const pretty = PRETTY[keyStr] ?? keyStr.replace(/_/g, " ");

  return (
    <DialogPrimitive.Root open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Backdrop
          className="fixed inset-0 z-50 transition-opacity duration-200 data-ending-style:opacity-0 data-starting-style:opacity-0 supports-backdrop-filter:backdrop-blur-sm"
          style={{ backgroundColor: surface.backdrop }}
        />
        <DialogPrimitive.Popup
          data-theme={pageTheme}
          className="fixed top-1/2 left-1/2 z-50 flex w-[calc(100vw-3rem)] max-w-[760px] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden outline-none transition duration-200 data-ending-style:scale-[0.96] data-ending-style:opacity-0 data-starting-style:scale-[0.96] data-starting-style:opacity-0"
          style={{
            background: surface.bgGradient,
            color: surface.ink,
            borderRadius: 22,
            maxHeight: "calc(100vh - 2rem)",
            boxShadow: isDark
              ? `0 40px 100px rgba(0,0,0,0.75), 0 0 0 1px ${surface.ring}, inset 0 1px 0 ${surface.borderTop}`
              : `0 40px 100px rgba(20,30,25,0.18), 0 0 0 1px ${surface.ring}, inset 0 1px 0 ${surface.borderTop}`,
          }}
        >
          <div
            className="flex items-start gap-3 px-7 py-5"
            style={{
              borderBottom: `1px solid ${surface.line}`,
              backgroundImage: isDark
                ? `radial-gradient(ellipse 600px 200px at 20% 0%, rgba(143,214,177,0.08), transparent 70%), radial-gradient(ellipse 600px 200px at 80% 0%, rgba(232,190,114,0.06), transparent 70%)`
                : `radial-gradient(ellipse 600px 200px at 20% 0%, rgba(78,148,112,0.07), transparent 70%), radial-gradient(ellipse 600px 200px at 80% 0%, rgba(214,165,77,0.06), transparent 70%)`,
            }}
          >
            <div className="min-w-0 flex-1">
              <div
                className="cf-health-modal-eyebrow"
                style={{
                  color: surface.eyebrow,
                  ["--cf-eyebrow-dot" as string]: surface.eyebrowDot,
                  ["--cf-eyebrow-halo" as string]: isDark
                    ? "rgba(143, 214, 177, 0.18)"
                    : "rgba(78, 148, 112, 0.18)",
                }}
              >
                Health metric · {pretty}
              </div>
              <DialogPrimitive.Title
                className="truncate leading-[1.05]"
                style={{
                  color: isDark ? surface.gold : surface.ink,
                  fontFamily: "var(--font-fraunces), Georgia, serif",
                  fontSize: "24px",
                  fontWeight: 600,
                  letterSpacing: "-0.02em",
                  fontStyle: isDark ? "italic" : "normal",
                }}
              >
                {pretty}
              </DialogPrimitive.Title>
            </div>
            <DialogPrimitive.Close
              className="inline-flex h-8 w-8 items-center justify-center rounded-full transition outline-none shrink-0"
              aria-label="Close"
              style={{ color: surface.ink2 }}
              onMouseEnter={(e) => {
                e.currentTarget.style.backgroundColor = isDark
                  ? "rgba(208,212,207,0.08)"
                  : "rgba(26,38,32,0.06)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.backgroundColor = "transparent";
              }}
            >
              <X className="h-4 w-4" />
            </DialogPrimitive.Close>
          </div>

          {mounted && open ? (
            <div className="cf-health-modal-body flex-1 overflow-y-auto px-7 py-6">
              <style>{`
                [data-theme="${pageTheme}"] .cf-health-modal-eyebrow {
                  display: inline-flex;
                  align-items: center;
                  gap: 8px;
                  font-family: var(--font-inter), 'Inter', system-ui, sans-serif;
                  font-size: 10px;
                  letter-spacing: 0.2em;
                  text-transform: uppercase;
                  font-weight: 700;
                  margin-bottom: 10px;
                  color: ${surface.eyebrow};
                }
                [data-theme="${pageTheme}"] .cf-health-modal-eyebrow::before {
                  content: "";
                  width: 6px; height: 6px;
                  border-radius: 50%;
                  background: ${surface.eyebrowDot};
                  box-shadow: 0 0 0 4px ${
                    isDark ? "rgba(143,214,177,0.18)" : "rgba(78,148,112,0.18)"
                  };
                }
                .cf-health-modal-body,
                .cf-health-modal-body * {
                  font-family: var(--font-inter), 'Inter', system-ui, sans-serif;
                  box-sizing: border-box;
                }
                .cf-health-modal-body p { color: ${surface.ink}; font-size: 13px; line-height: 1.58; margin: 0; }
                .cf-health-modal-body .cf-health-section-title {
                  font-family: var(--font-fraunces), Georgia, serif;
                  font-size: 18px;
                  font-weight: 500;
                  letter-spacing: -0.02em;
                  color: ${surface.ink};
                  margin: 0 0 8px;
                }
                .cf-health-modal-body .cf-health-card {
                  background: ${surface.cardBg};
                  border: 1px solid ${surface.cardBorder};
                  border-radius: 14px;
                  padding: 16px 18px;
                }
                .cf-health-modal-body .cf-health-list {
                  list-style: none;
                  margin: 0;
                  padding: 0;
                  display: flex;
                  flex-direction: column;
                  gap: 8px;
                }
                .cf-health-modal-body .cf-health-list li {
                  display: flex;
                  align-items: center;
                  justify-content: space-between;
                  gap: 12px;
                  padding: 10px 12px;
                  background: ${
                    isDark ? "rgba(255,255,255,0.025)" : "rgba(255,255,255,0.55)"
                  };
                  border: 1px solid ${surface.line};
                  border-radius: 12px;
                }
                .cf-health-modal-body .cf-health-list-label {
                  font-size: 14px;
                  font-weight: 600;
                  letter-spacing: -0.005em;
                  color: ${surface.ink};
                }
                .cf-health-modal-body .cf-health-mini-chip {
                  display: inline-flex;
                  align-items: center;
                  gap: 4px;
                  font-family: var(--font-jetbrains-mono), ui-monospace, monospace;
                  font-size: 11px;
                  font-weight: 700;
                  letter-spacing: 0;
                  padding: 4px 9px;
                  border-radius: 999px;
                  background: ${
                    isDark ? "rgba(255,255,255,0.08)" : "rgba(26,38,32,0.08)"
                  };
                  color: ${surface.ink2};
                  font-feature-settings: "tnum";
                }
                .cf-health-modal-body table {
                  width: 100%;
                  border-collapse: collapse;
                  font-size: 13px;
                }
                .cf-health-modal-body th {
                  text-align: left;
                  font-size: 10px;
                  font-weight: 700;
                  letter-spacing: 0.18em;
                  text-transform: uppercase;
                  color: ${surface.muted};
                  padding: 8px 10px;
                  border-bottom: 1px solid ${surface.line};
                }
                .cf-health-modal-body td {
                  padding: 10px;
                  border-bottom: 1px solid ${surface.line};
                  color: ${surface.ink};
                }
                .cf-health-modal-body td.cf-num {
                  font-family: var(--font-jetbrains-mono), ui-monospace, monospace;
                  font-feature-settings: "tnum";
                  text-align: right;
                  color: ${surface.ink2};
                }
                .cf-health-modal-body .cf-empty {
                  font-style: italic;
                  color: ${surface.muted};
                  font-size: 13px;
                }
              `}</style>
              <ModalBody metricKey={keyStr} />
            </div>
          ) : (
            <div
              className="flex-1 flex items-center justify-center text-sm py-16"
              style={{ color: surface.muted }}
            >
              Loading…
            </div>
          )}
        </DialogPrimitive.Popup>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

function ModalBody({ metricKey }: { metricKey: string }) {
  if (metricKey === "top_confusion") return <TopConfusionBody />;
  if (metricKey === "worst_lessons") return <WorstLessonsBody />;
  if (metricKey === "revenue_at_risk") return <RevenueAtRiskBody />;
  if (metricKey === "review_queue") return <ReviewQueueBody />;
  if (metricKey === "stale_students") return <StaleStudentsBody />;
  if (metricKey === "open_feedback") return <FeedbackBody />;
  if (metricKey === "cohort_delta") return <CohortDeltaBody />;
  return <PlaceholderBody metricKey={metricKey} />;
}

const CATEGORY_LABEL: Record<string, string> = {
  bug: "Bug",
  confusing: "Confusing",
  feature_request: "Idea",
  praise: "Praise",
  other: "Other",
};
const CATEGORY_TONE: Record<string, string> = {
  bug: "#d96252",
  confusing: "#d6a54d",
  feature_request: "#356d50",
  praise: "#7a5cc4",
  other: "#8f897d",
};
const SEVERITY_TONE: Record<string, string> = {
  blocking: "#d96252",
  annoying: "#d6a54d",
  cosmetic: "#8f897d",
};

function FeedbackBody() {
  const { data, isLoading, isError } = useAdminFeedback();
  const { mutate: resolve, isPending } = useResolveFeedback();
  const [filter, setFilter] = useState<string>("all");
  const open = (data ?? []).filter((i) => !i.resolved);
  const items = open
    .filter((i) => filter === "all" || (i.category ?? "other") === filter)
    .sort((a, b) => {
      // bugs first, then by date desc
      const av = a.category === "bug" ? 0 : 1;
      const bv = b.category === "bug" ? 0 : 1;
      if (av !== bv) return av - bv;
      return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
    });
  const counts: Record<string, number> = { all: open.length };
  open.forEach((i) => {
    const k = i.category ?? "other";
    counts[k] = (counts[k] ?? 0) + 1;
  });

  return (
    <div className="cf-health-card">
      <h3 className="cf-health-section-title">Open feedback</h3>
      <p style={{ marginBottom: 12 }}>
        {open.length} unresolved item{open.length === 1 ? "" : "s"}. Bugs first,
        then newest. Click Resolve to clear from the queue.
      </p>
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 6,
          marginBottom: 14,
        }}
      >
        {(["all", "bug", "confusing", "feature_request", "praise", "other"] as const).map(
          (k) => {
            const active = filter === k;
            const label = k === "all" ? "All" : CATEGORY_LABEL[k];
            const n = counts[k] ?? 0;
            if (k !== "all" && n === 0) return null;
            return (
              <button
                key={k}
                type="button"
                onClick={() => setFilter(k)}
                style={{
                  padding: "4px 10px",
                  fontSize: 11,
                  fontWeight: 700,
                  letterSpacing: "0.12em",
                  textTransform: "uppercase",
                  borderRadius: 999,
                  border: `1px solid ${
                    active ? "currentColor" : "rgba(0,0,0,0.12)"
                  }`,
                  background: active ? "rgba(0,0,0,0.04)" : "transparent",
                  cursor: "pointer",
                }}
              >
                {label} · {n}
              </button>
            );
          },
        )}
      </div>
      {isLoading ? (
        <p className="cf-empty">Loading…</p>
      ) : isError ? (
        <p className="cf-empty">Failed to load feedback.</p>
      ) : items.length === 0 ? (
        <p className="cf-empty">
          {open.length === 0
            ? "Inbox zero — no open feedback."
            : "No items in this category."}
        </p>
      ) : (
        <ul className="cf-health-list">
          {items.slice(0, 30).map((f) => (
            <FeedbackRow
              key={f.id}
              item={f}
              onResolve={() => resolve(f.id)}
              resolving={isPending}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

function FeedbackRow({
  item,
  onResolve,
  resolving,
}: {
  item: import("@/lib/hooks/use-admin").FeedbackItem;
  onResolve: () => void;
  resolving: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const cat = item.category ?? "other";
  const catTone = CATEGORY_TONE[cat] ?? "#8f897d";
  const hasContext = Boolean(
    item.url ||
      item.user_agent ||
      item.viewport_width ||
      item.app_version ||
      item.error_id,
  );
  const device =
    item.viewport_width && item.viewport_height
      ? `${item.viewport_width}×${item.viewport_height}`
      : null;
  const browser = item.user_agent
    ? item.user_agent.match(/(Chrome|Safari|Firefox|Edge|OPR)\/[\d.]+/)?.[0] ??
      item.user_agent.slice(0, 40)
    : null;

  return (
    <li
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 6,
        padding: "10px 0",
        borderBottom: "1px solid rgba(0,0,0,0.06)",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          fontSize: 11,
          fontWeight: 700,
          letterSpacing: "0.12em",
          textTransform: "uppercase",
          flexWrap: "wrap",
        }}
      >
        <span
          style={{
            padding: "2px 8px",
            borderRadius: 999,
            background: catTone,
            color: "white",
            fontSize: 10,
          }}
        >
          {CATEGORY_LABEL[cat] ?? cat}
        </span>
        {item.severity ? (
          <span
            style={{
              padding: "2px 8px",
              borderRadius: 999,
              border: `1px solid ${SEVERITY_TONE[item.severity] ?? "#8f897d"}`,
              color: SEVERITY_TONE[item.severity] ?? "#8f897d",
              fontSize: 10,
            }}
          >
            {item.severity}
          </span>
        ) : null}
        <span style={{ opacity: 0.7, fontWeight: 500 }}>{item.route}</span>
        <span style={{ opacity: 0.5, fontWeight: 500 }}>
          · {new Date(item.created_at).toLocaleString()}
        </span>
        <button
          type="button"
          onClick={onResolve}
          disabled={resolving}
          style={{
            marginLeft: "auto",
            padding: "3px 9px",
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            borderRadius: 999,
            border: "1px solid currentColor",
            background: "transparent",
            cursor: resolving ? "wait" : "pointer",
            opacity: resolving ? 0.5 : 1,
          }}
        >
          Resolve
        </button>
      </div>
      <div style={{ fontSize: 13, lineHeight: 1.58 }}>{item.body}</div>
      {hasContext ? (
        <div style={{ marginTop: 2 }}>
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            style={{
              fontSize: 10,
              fontWeight: 700,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              opacity: 0.6,
              background: "transparent",
              border: "none",
              cursor: "pointer",
              padding: 0,
            }}
          >
            {expanded ? "Hide context" : "Show context"}
          </button>
          {expanded ? (
            <dl
              style={{
                marginTop: 6,
                display: "grid",
                gridTemplateColumns: "auto 1fr",
                gap: "3px 12px",
                fontSize: 11,
                fontFamily:
                  "var(--font-jetbrains-mono), ui-monospace, monospace",
                opacity: 0.85,
              }}
            >
              {item.url ? (
                <>
                  <dt style={{ opacity: 0.6 }}>URL</dt>
                  <dd style={{ margin: 0, wordBreak: "break-all" }}>
                    {item.url}
                  </dd>
                </>
              ) : null}
              {browser ? (
                <>
                  <dt style={{ opacity: 0.6 }}>Browser</dt>
                  <dd style={{ margin: 0 }}>{browser}</dd>
                </>
              ) : null}
              {device ? (
                <>
                  <dt style={{ opacity: 0.6 }}>Viewport</dt>
                  <dd style={{ margin: 0 }}>{device}</dd>
                </>
              ) : null}
              {item.app_version ? (
                <>
                  <dt style={{ opacity: 0.6 }}>Version</dt>
                  <dd style={{ margin: 0 }}>{item.app_version}</dd>
                </>
              ) : null}
              {item.error_id ? (
                <>
                  <dt style={{ opacity: 0.6 }}>Error ID</dt>
                  <dd style={{ margin: 0 }}>{item.error_id}</dd>
                </>
              ) : null}
            </dl>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

interface RevenueAtRiskItem {
  user_id: string;
  name: string;
  email: string | null;
  amount_cents: number;
  amount_display: string;
  last_active_days: number | null;
  last_active_text: string;
}
interface RevenueAtRiskResponse {
  items: RevenueAtRiskItem[];
  total_cents: number;
  total_display: string;
}

function RevenueAtRiskBody() {
  const { data, isLoading, isError } = useQuery<RevenueAtRiskResponse>({
    queryKey: ["admin", "health-strip", "revenue-at-risk"],
    queryFn: () =>
      api.get<RevenueAtRiskResponse>(
        "/api/v1/admin/health-strip/revenue-at-risk",
      ),
    staleTime: 60_000,
  });
  const items = data?.items ?? [];
  return (
    <div className="cf-health-card">
      <h3 className="cf-health-section-title">Paid students gone silent · 7d+</h3>
      <p style={{ marginBottom: 12 }}>
        Total at risk:{" "}
        <strong>{data?.total_display ?? "$0.00"}</strong> across{" "}
        {items.length} {items.length === 1 ? "student" : "students"}.
      </p>
      {isLoading ? (
        <p className="cf-empty">Loading…</p>
      ) : isError ? (
        <p className="cf-empty">Failed to load revenue at risk.</p>
      ) : items.length === 0 ? (
        <p className="cf-empty">No paid students currently silent. Nice.</p>
      ) : (
        <table aria-label="Paid students at risk">
          <thead>
            <tr>
              <th>Student</th>
              <th style={{ textAlign: "right" }}>Paid</th>
              <th style={{ textAlign: "right" }}>Last seen</th>
            </tr>
          </thead>
          <tbody>
            {items.map((i) => (
              <tr key={i.user_id}>
                <td>
                  <div style={{ fontWeight: 500 }}>{i.name}</div>
                  {i.email ? (
                    <div style={{ fontSize: 11, opacity: 0.7 }}>{i.email}</div>
                  ) : null}
                </td>
                <td className="cf-num">{i.amount_display}</td>
                <td className="cf-num">{i.last_active_text}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

interface ReviewQueueItem {
  submission_id: string;
  user_id: string;
  user_name: string;
  exercise_id: string;
  exercise_title: string | null;
  created_at: string;
  age_hours: number;
  age_text: string;
}
interface ReviewQueueResponse {
  items: ReviewQueueItem[];
  total: number;
}

function ReviewQueueBody() {
  const { data, isLoading, isError } = useQuery<ReviewQueueResponse>({
    queryKey: ["admin", "health-strip", "review-queue"],
    queryFn: () =>
      api.get<ReviewQueueResponse>("/api/v1/admin/health-strip/review-queue"),
    staleTime: 60_000,
  });
  const items = data?.items ?? [];
  return (
    <div className="cf-health-card">
      <h3 className="cf-health-section-title">Review queue · oldest first</h3>
      <p style={{ marginBottom: 12 }}>
        {data?.total ?? 0} submission{(data?.total ?? 0) === 1 ? "" : "s"}{" "}
        awaiting review. Senior-review SLA breached after 48h.
      </p>
      {isLoading ? (
        <p className="cf-empty">Loading…</p>
      ) : isError ? (
        <p className="cf-empty">Failed to load review queue.</p>
      ) : items.length === 0 ? (
        <p className="cf-empty">Queue is empty.</p>
      ) : (
        <table aria-label="Review queue">
          <thead>
            <tr>
              <th>Student</th>
              <th>Exercise</th>
              <th style={{ textAlign: "right" }}>Waiting</th>
            </tr>
          </thead>
          <tbody>
            {items.map((i) => (
              <tr key={i.submission_id}>
                <td>{i.user_name}</td>
                <td>{i.exercise_title ?? "—"}</td>
                <td className="cf-num">{i.age_text}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

interface StaleStudentItem {
  user_id: string;
  name: string;
  email: string | null;
  last_active_days: number | null;
  last_active_text: string;
  is_paid: boolean;
}
interface StaleStudentsResponse {
  items: StaleStudentItem[];
  total: number;
}

function StaleStudentsBody() {
  const { data, isLoading, isError } = useQuery<StaleStudentsResponse>({
    queryKey: ["admin", "health-strip", "stale-students"],
    queryFn: () =>
      api.get<StaleStudentsResponse>(
        "/api/v1/admin/health-strip/stale-students",
      ),
    staleTime: 60_000,
  });
  const items = data?.items ?? [];
  return (
    <div className="cf-health-card">
      <h3 className="cf-health-section-title">No activity · 7d+</h3>
      <p style={{ marginBottom: 12 }}>
        {data?.total ?? 0} student{(data?.total ?? 0) === 1 ? "" : "s"} haven&apos;t
        logged in for a week. Paid accounts flagged below trigger
        re-engagement automation.
      </p>
      {isLoading ? (
        <p className="cf-empty">Loading…</p>
      ) : isError ? (
        <p className="cf-empty">Failed to load stale students.</p>
      ) : items.length === 0 ? (
        <p className="cf-empty">Everyone is active.</p>
      ) : (
        <table aria-label="Stale students">
          <thead>
            <tr>
              <th>Student</th>
              <th>Paid</th>
              <th style={{ textAlign: "right" }}>Last seen</th>
            </tr>
          </thead>
          <tbody>
            {items.slice(0, 30).map((i) => (
              <tr key={i.user_id}>
                <td>
                  <div style={{ fontWeight: 500 }}>{i.name}</div>
                  {i.email ? (
                    <div style={{ fontSize: 11, opacity: 0.7 }}>{i.email}</div>
                  ) : null}
                </td>
                <td>
                  {i.is_paid ? (
                    <span className="cf-health-mini-chip">Paid</span>
                  ) : (
                    <span style={{ opacity: 0.5 }}>—</span>
                  )}
                </td>
                <td className="cf-num">{i.last_active_text}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

interface CohortDailyPoint {
  date: string;
  signups: number;
  paid: number;
}
interface CohortDeltaResponse {
  this_week_signups: number;
  last_week_signups: number;
  delta_pct: number;
  delta_text: string;
  this_week_paid: number;
  last_week_paid: number;
  this_week_completions: number;
  last_week_completions: number;
  daily: CohortDailyPoint[];
}

function CohortDeltaBody() {
  const { data, isLoading, isError } = useQuery<CohortDeltaResponse>({
    queryKey: ["admin", "health-strip", "cohort-delta"],
    queryFn: () =>
      api.get<CohortDeltaResponse>("/api/v1/admin/health-strip/cohort-delta"),
    staleTime: 60_000,
  });
  return (
    <div className="cf-health-card">
      <h3 className="cf-health-section-title">Cohort delta · week-over-week</h3>
      <p style={{ marginBottom: 12 }}>
        Signups, paid conversions, and lesson completions this week vs. last.
      </p>
      {isLoading ? (
        <p className="cf-empty">Loading…</p>
      ) : isError || !data ? (
        <p className="cf-empty">Failed to load cohort delta.</p>
      ) : (
        <>
          <table aria-label="Cohort delta">
            <thead>
              <tr>
                <th>Metric</th>
                <th style={{ textAlign: "right" }}>Last week</th>
                <th style={{ textAlign: "right" }}>This week</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Signups</td>
                <td className="cf-num">{data.last_week_signups}</td>
                <td className="cf-num">
                  {data.this_week_signups}{" "}
                  <span style={{ opacity: 0.7 }}>({data.delta_text})</span>
                </td>
              </tr>
              <tr>
                <td>Paid conversions</td>
                <td className="cf-num">{data.last_week_paid}</td>
                <td className="cf-num">{data.this_week_paid}</td>
              </tr>
              <tr>
                <td>Lesson completions</td>
                <td className="cf-num">{data.last_week_completions}</td>
                <td className="cf-num">{data.this_week_completions}</td>
              </tr>
            </tbody>
          </table>
          {data.daily?.length ? (
            <p style={{ marginTop: 12, fontSize: 11, opacity: 0.7 }}>
              {data.daily.length}-day signup trend recorded.
            </p>
          ) : null}
        </>
      )}
    </div>
  );
}

function PlaceholderBody({ metricKey }: { metricKey: string }) {
  const description =
    DESCRIPTIONS[metricKey] ?? "Detail content for this metric.";
  const pretty = PRETTY[metricKey] ?? metricKey.replace(/_/g, " ");
  return (
    <div className="cf-health-card">
      <h3 className="cf-health-section-title">{pretty}</h3>
      <p>{description}</p>
      <p style={{ marginTop: 10 }} className="cf-empty">
        Coming soon: detail data for {metricKey}. Detailed breakdown coming
        soon — wire to backend endpoint.
      </p>
    </div>
  );
}

function TopConfusionBody() {
  const { data, isLoading, isError } = useConfusionHeatmap(7);
  const top = (data ?? []).slice(0, 5);
  return (
    <div className="cf-health-card">
      <h3 className="cf-health-section-title">Top confused concepts · 7d</h3>
      <p style={{ marginBottom: 12 }}>
        Concepts where the Socratic tutor logged the most help requests in the
        last week.
      </p>
      {isLoading ? (
        <p className="cf-empty">Loading…</p>
      ) : isError ? (
        <p className="cf-empty">Failed to load confusion data.</p>
      ) : top.length === 0 ? (
        <p className="cf-empty">No confusion events recorded.</p>
      ) : (
        <ul className="cf-health-list">
          {top.map((c) => (
            <li key={c.topic}>
              <span className="cf-health-list-label">{c.topic}</span>
              <span style={{ display: "inline-flex", gap: 6 }}>
                <span className="cf-health-mini-chip">
                  {c.help_count} asks
                </span>
                <span className="cf-health-mini-chip">
                  {c.distinct_students} students
                </span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

interface LessonPerformance {
  lesson_id: string;
  lesson_title: string;
  question_count: number;
  confusion_count: number;
}

function WorstLessonsBody() {
  const { data, isLoading, isError } = useQuery<LessonPerformance[]>({
    queryKey: ["admin", "content-performance"],
    queryFn: () =>
      api.get<LessonPerformance[]>("/api/v1/admin/content-performance"),
    staleTime: 60_000,
  });
  const ranked = (data ?? [])
    .map((l) => ({
      ...l,
      rate: l.question_count > 0 ? l.confusion_count / l.question_count : 0,
    }))
    .sort((a, b) => b.rate - a.rate)
    .slice(0, 5);

  return (
    <div className="cf-health-card">
      <h3 className="cf-health-section-title">Worst lessons by confusion rate</h3>
      <p style={{ marginBottom: 12 }}>
        Lessons whose Socratic-tutor exchanges most often resolve to a
        confusion flag. Top 5 by ratio.
      </p>
      {isLoading ? (
        <p className="cf-empty">Loading…</p>
      ) : isError ? (
        <p className="cf-empty">Failed to load lesson performance.</p>
      ) : ranked.length === 0 ? (
        <p className="cf-empty">No lesson interaction data yet.</p>
      ) : (
        <table aria-label="Worst lessons by confusion rate">
          <thead>
            <tr>
              <th>Lesson</th>
              <th style={{ textAlign: "right" }}>Asks</th>
              <th style={{ textAlign: "right" }}>Confused</th>
              <th style={{ textAlign: "right" }}>Rate</th>
            </tr>
          </thead>
          <tbody>
            {ranked.map((l) => (
              <tr key={l.lesson_id}>
                <td>{l.lesson_title}</td>
                <td className="cf-num">{l.question_count}</td>
                <td className="cf-num">{l.confusion_count}</td>
                <td className="cf-num">{(l.rate * 100).toFixed(0)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
