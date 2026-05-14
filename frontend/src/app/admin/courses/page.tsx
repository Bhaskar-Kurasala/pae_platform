"use client";

/**
 * /admin/courses — premium course operations cockpit.
 *
 * Three tabs:
 *  - Courses: catalog + operational health, inline edit, bulk actions,
 *    drill-down to coupons per course.
 *  - Bundles: bundle CRUD with course picker.
 *  - Coupons: platform-wide coupon table with create + scope filters.
 *
 * Visual system mirrors the v8 admin chrome (Fraunces titles, Inter body,
 * warm-cream / dark-forest palette, mini-chip pills, soft 12px cards).
 */

import { useMemo, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Eye,
  Pencil,
  Plus,
  Star,
  Trash2,
  X,
} from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  useCoursesHealth,
  useCourseCoupons,
  useAllCoupons,
  useCreateCoupon,
  useUpdateCoupon,
  useDeleteCoupon,
  useBundles,
  useCreateBundle,
  useUpdateBundle,
  useDeleteBundle,
  useAddCourseToBundle,
  useRemoveCourseFromBundle,
  type CourseHealth,
  type BundleSummary,
} from "@/lib/hooks/use-courses";
import { useAdminTheme } from "@/lib/hooks/use-admin-theme";
import { api } from "@/lib/api-client";
import { cn } from "@/lib/utils";

type TabKey = "courses" | "bundles" | "coupons";
type FilterKey =
  | "all"
  | "published"
  | "drafts"
  | "free"
  | "paid"
  | "needs_attention";

type CouponScopeFilter =
  | "all"
  | "active"
  | "expired"
  | "course"
  | "bundle"
  | "platform";

const FILTER_LABEL: Record<FilterKey, string> = {
  all: "All",
  published: "Published",
  drafts: "Drafts",
  free: "Free",
  paid: "Paid",
  needs_attention: "Needs attention",
};

const FILTER_ORDER: FilterKey[] = [
  "all",
  "published",
  "drafts",
  "free",
  "paid",
  "needs_attention",
];

const DIFFICULTIES = ["beginner", "intermediate", "advanced"] as const;

// ---------- helpers ----------

function formatPrice(priceCents: number): string {
  if (priceCents === 0) return "Free";
  return `$${(priceCents / 100).toFixed(0)}`;
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function rowBorderColor(c: CourseHealth): string | null {
  if (!c.needs_attention) return null;
  if (c.avg_confusion_rate > 0.3) return "#d96252";
  return "#d6a54d";
}

function confusionTone(rate: number): { fill: string; muted: boolean } {
  if (rate > 0.3) return { fill: "#d96252", muted: false };
  if (rate > 0.15) return { fill: "#d6a54d", muted: false };
  return { fill: "#9ca3af", muted: true };
}

function matches(filter: FilterKey, c: CourseHealth): boolean {
  switch (filter) {
    case "all":
      return true;
    case "published":
      return c.is_published;
    case "drafts":
      return !c.is_published;
    case "free":
      return c.price_cents === 0;
    case "paid":
      return c.price_cents > 0;
    case "needs_attention":
      return c.needs_attention;
  }
}

function generateCouponCode(prefix = "SALE"): string {
  const year = new Date().getFullYear();
  const rand = Math.random().toString(36).slice(2, 6).toUpperCase();
  return `${prefix}${year}${rand}`;
}

// ---------- page ----------

export default function AdminCoursesPage() {
  const { theme } = useAdminTheme();
  const isDark = theme === "dark";
  const [tab, setTab] = useState<TabKey>("courses");

  const pageBg = isDark
    ? "linear-gradient(180deg, #0b110e 0%, #10120e 100%)"
    : "#FBF7EE";
  const ink = isDark ? "#f0ece1" : "#10120e";
  const muted = isDark ? "#9a9588" : "#686559";
  const line = isDark ? "#2c3830" : "#dbd1bf";
  const eyebrow = isDark ? "#8fd6b1" : "#356d50";

  return (
    <div
      className="min-h-screen w-full"
      style={{
        background: pageBg,
        color: ink,
        fontFamily: "var(--font-inter), Inter, system-ui, sans-serif",
      }}
    >
      <div className="w-full px-6 py-8 md:px-10 md:py-10 max-w-[1400px] mx-auto space-y-6">
        <header className="flex flex-col gap-1">
          <span
            style={{
              fontSize: 10,
              fontWeight: 700,
              letterSpacing: "0.2em",
              textTransform: "uppercase",
              color: eyebrow,
            }}
          >
            Operate · Catalog
          </span>
          <h1
            style={{
              fontFamily: "var(--font-fraunces), Georgia, serif",
              fontSize: 32,
              fontWeight: 500,
              letterSpacing: "-0.04em",
              lineHeight: 1.1,
            }}
          >
            Courses
          </h1>
          <p style={{ color: muted, fontSize: 14, maxWidth: 720 }}>
            The full catalog with operational health, bundle composition, and
            promotional coupons. Inline-edit pricing, difficulty, and
            visibility without leaving the table.
          </p>
        </header>

        {/* Tabs */}
        <div
          role="tablist"
          aria-label="Courses cockpit tabs"
          className="inline-flex items-center gap-1 rounded-full p-1"
          style={{
            background: isDark
              ? "rgba(255,255,255,0.04)"
              : "rgba(255,255,255,0.7)",
            border: `1px solid ${line}`,
          }}
        >
          {(["courses", "bundles", "coupons"] as TabKey[]).map((k) => {
            const active = tab === k;
            return (
              <button
                key={k}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => setTab(k)}
                className="px-4 py-1.5 rounded-full transition"
                style={{
                  fontSize: 11,
                  fontWeight: 700,
                  letterSpacing: "0.12em",
                  textTransform: "uppercase",
                  background: active ? "#1D9E75" : "transparent",
                  color: active ? "#ffffff" : ink,
                  cursor: "pointer",
                  border: "none",
                }}
              >
                {k}
              </button>
            );
          })}
        </div>

        {tab === "courses" ? (
          <CoursesTab isDark={isDark} ink={ink} muted={muted} line={line} />
        ) : tab === "bundles" ? (
          <BundlesTab isDark={isDark} ink={ink} muted={muted} line={line} />
        ) : (
          <CouponsTab isDark={isDark} ink={ink} muted={muted} line={line} />
        )}
      </div>
    </div>
  );
}

// =====================================================================
// COURSES TAB
// =====================================================================

interface TabProps {
  isDark: boolean;
  ink: string;
  muted: string;
  line: string;
}

function CoursesTab({ isDark, ink, muted, line }: TabProps) {
  const { data, isLoading, isError, error } = useCoursesHealth();
  const [filter, setFilter] = useState<FilterKey>("all");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [expandedCourseId, setExpandedCourseId] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const createCoupon = useCreateCoupon();

  const items = useMemo<CourseHealth[]>(() => data?.items ?? [], [data]);

  const counts = useMemo<Record<FilterKey, number>>(() => {
    const out: Record<FilterKey, number> = {
      all: 0,
      published: 0,
      drafts: 0,
      free: 0,
      paid: 0,
      needs_attention: 0,
    };
    for (const c of items) {
      out.all += 1;
      if (c.is_published) out.published += 1;
      else out.drafts += 1;
      if (c.price_cents === 0) out.free += 1;
      else out.paid += 1;
      if (c.needs_attention) out.needs_attention += 1;
    }
    return out;
  }, [items]);

  const filtered = useMemo(
    () => items.filter((c) => matches(filter, c)),
    [items, filter],
  );

  const cardBg = isDark ? "rgba(255,255,255,0.04)" : "rgba(255,255,255,0.7)";

  const publishMutation = useMutation({
    mutationFn: async (vars: { courseId: string; next: boolean }) =>
      api.patch<CourseHealth>(`/api/v1/admin/courses/${vars.courseId}`, {
        is_published: vars.next,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "courses-health"] });
    },
  });

  const featureMutation = useMutation({
    mutationFn: async (vars: { courseId: string; next: boolean }) =>
      api.patch<CourseHealth>(`/api/v1/admin/courses/${vars.courseId}`, {
        is_featured: vars.next,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "courses-health"] });
    },
  });

  const patchMutation = useMutation({
    mutationFn: async (vars: {
      courseId: string;
      body: Record<string, unknown>;
    }) =>
      api.patch<CourseHealth>(
        `/api/v1/admin/courses/${vars.courseId}`,
        vars.body,
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "courses-health"] });
    },
  });

  function toggleSelect(courseId: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(courseId)) next.delete(courseId);
      else next.add(courseId);
      return next;
    });
  }

  function clearSelection() {
    setSelected(new Set());
  }

  async function bulkSetPublish(next: boolean) {
    const ids = Array.from(selected);
    await Promise.all(
      ids.map((id) =>
        api.patch(`/api/v1/admin/courses/${id}`, { is_published: next }),
      ),
    );
    queryClient.invalidateQueries({ queryKey: ["admin", "courses-health"] });
  }

  async function bulkApplyCoupon() {
    const raw = window.prompt("Percent off (1-100)?", "20");
    if (!raw) return;
    const pct = Number(raw);
    if (!Number.isFinite(pct) || pct < 1 || pct > 100) {
      window.alert("Enter a number between 1 and 100.");
      return;
    }
    const ids = Array.from(selected);
    for (const courseId of ids) {
      await createCoupon.mutateAsync({
        code: generateCouponCode(),
        course_id: courseId,
        percent_off: Math.round(pct),
      });
    }
    clearSelection();
  }

  return (
    <div className="space-y-4">
      {/* Filter chips */}
      <div className="flex flex-wrap items-center gap-2">
        {FILTER_ORDER.map((k) => {
          const active = filter === k;
          return (
            <button
              key={k}
              type="button"
              onClick={() => setFilter(k)}
              className="inline-flex items-center rounded-full px-3 py-1 transition"
              style={{
                fontSize: 11,
                fontWeight: 700,
                letterSpacing: "0.12em",
                textTransform: "uppercase",
                border: `1px solid ${active ? "transparent" : line}`,
                backgroundColor: active ? "#1D9E75" : "transparent",
                color: active ? "#ffffff" : ink,
                cursor: "pointer",
              }}
            >
              {FILTER_LABEL[k]} · {counts[k]}
            </button>
          );
        })}
      </div>

      {/* Bulk action bar */}
      {selected.size > 0 ? (
        <div
          className="flex flex-wrap items-center gap-3 rounded-xl px-4 py-3"
          style={{
            background: isDark
              ? "rgba(143,214,177,0.08)"
              : "rgba(78,148,112,0.06)",
            border: `1px solid ${isDark ? "rgba(143,214,177,0.22)" : "rgba(78,148,112,0.20)"}`,
          }}
        >
          <span style={{ fontSize: 13, fontWeight: 600 }}>
            {selected.size} selected
          </span>
          <span style={{ color: muted }}>·</span>
          <BulkButton onClick={() => bulkSetPublish(true)} ink={ink} line={line}>
            Publish all
          </BulkButton>
          <BulkButton
            onClick={() => bulkSetPublish(false)}
            ink={ink}
            line={line}
          >
            Unpublish all
          </BulkButton>
          <BulkButton onClick={bulkApplyCoupon} ink={ink} line={line}>
            Apply % off
          </BulkButton>
          <button
            type="button"
            onClick={clearSelection}
            style={{
              marginLeft: "auto",
              fontSize: 12,
              color: muted,
              background: "transparent",
              border: "none",
              cursor: "pointer",
              textDecoration: "underline",
            }}
          >
            Clear selection
          </button>
        </div>
      ) : null}

      {/* Table */}
      {isLoading ? (
        <SkeletonRows />
      ) : isError ? (
        <ErrorCard
          message={`Failed to load courses: ${(error as Error)?.message ?? "unknown"}`}
          isDark={isDark}
          line={line}
        />
      ) : items.length === 0 ? (
        <EmptyCard
          title="No courses yet"
          body="The catalog is empty. Create your first course to start onboarding students."
          isDark={isDark}
          line={line}
          muted={muted}
        />
      ) : filtered.length === 0 ? (
        <EmptyCard
          title="No matches"
          body={`No courses match the "${FILTER_LABEL[filter]}" filter.`}
          isDark={isDark}
          line={line}
          muted={muted}
        />
      ) : (
        <div
          className="overflow-x-auto rounded-xl"
          style={{
            background: cardBg,
            border: `1px solid ${line}`,
            boxShadow: isDark
              ? "0 1px 0 rgba(0,0,0,0.3)"
              : "0 1px 0 rgba(120,90,40,0.04), 0 1px 2px rgba(120,90,40,0.06)",
          }}
        >
          <table className="w-full text-sm" aria-label="Courses">
            <thead>
              <tr style={{ borderBottom: `1px solid ${line}` }}>
                <Th width={36}>
                  <input
                    type="checkbox"
                    aria-label="Select all"
                    checked={
                      filtered.length > 0 &&
                      filtered.every((c) => selected.has(c.course_id))
                    }
                    onChange={(e) => {
                      if (e.target.checked) {
                        setSelected(
                          new Set(filtered.map((c) => c.course_id)),
                        );
                      } else {
                        clearSelection();
                      }
                    }}
                  />
                </Th>
                <Th>Title</Th>
                <Th>Difficulty</Th>
                <Th align="right">Price</Th>
                <Th align="center" width={36}>
                  <Star size={12} aria-label="Featured" />
                </Th>
                <Th align="right">Enrol.</Th>
                <Th>Completion</Th>
                <Th>Confusion</Th>
                <Th>Feedback</Th>
                <Th>Publish</Th>
                <Th align="right">Actions</Th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((c) => {
                const tone = rowBorderColor(c);
                const expanded = expandedCourseId === c.course_id;
                const isSelected = selected.has(c.course_id);
                return (
                  <CourseRow
                    key={c.course_id}
                    c={c}
                    tone={tone}
                    expanded={expanded}
                    isSelected={isSelected}
                    onToggleSelect={() => toggleSelect(c.course_id)}
                    onToggleExpand={() =>
                      setExpandedCourseId(expanded ? null : c.course_id)
                    }
                    onPatch={(body) =>
                      patchMutation.mutateAsync({
                        courseId: c.course_id,
                        body,
                      })
                    }
                    onTogglePublish={() =>
                      publishMutation.mutate({
                        courseId: c.course_id,
                        next: !c.is_published,
                      })
                    }
                    onToggleFeature={(curr) =>
                      featureMutation.mutate({
                        courseId: c.course_id,
                        next: !curr,
                      })
                    }
                    isDark={isDark}
                    ink={ink}
                    muted={muted}
                    line={line}
                  />
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function BulkButton({
  children,
  onClick,
  ink,
  line,
}: {
  children: React.ReactNode;
  onClick: () => void;
  ink: string;
  line: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="rounded-full px-3 py-1 transition"
      style={{
        fontSize: 11,
        fontWeight: 700,
        letterSpacing: "0.12em",
        textTransform: "uppercase",
        border: `1px solid ${line}`,
        background: "transparent",
        color: ink,
        cursor: "pointer",
      }}
    >
      {children}
    </button>
  );
}

function Th({
  children,
  align = "left",
  width,
}: {
  children?: React.ReactNode;
  align?: "left" | "right" | "center";
  width?: number;
}) {
  return (
    <th
      className="px-3 py-3"
      style={{
        textAlign: align,
        width,
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: "0.14em",
        textTransform: "uppercase",
        color: "currentColor",
        opacity: 0.6,
      }}
    >
      {children}
    </th>
  );
}

// ---------- Course row ----------

function CourseRow({
  c,
  tone,
  expanded,
  isSelected,
  onToggleSelect,
  onToggleExpand,
  onPatch,
  onTogglePublish,
  onToggleFeature,
  isDark,
  ink,
  muted,
  line,
}: {
  c: CourseHealth & { is_featured?: boolean };
  tone: string | null;
  expanded: boolean;
  isSelected: boolean;
  onToggleSelect: () => void;
  onToggleExpand: () => void;
  onPatch: (body: Record<string, unknown>) => Promise<unknown>;
  onTogglePublish: () => void;
  onToggleFeature: (curr: boolean) => void;
  isDark: boolean;
  ink: string;
  muted: string;
  line: string;
}) {
  const enoughEnrollments = c.enrollments >= 5;
  const completionPct = Math.round(c.completion_rate * 100);
  const confusionPct = Math.round(c.avg_confusion_rate * 100);
  const confTone = confusionTone(c.avg_confusion_rate);

  const isFeatured = Boolean((c as { is_featured?: boolean }).is_featured);

  return (
    <>
      <tr
        style={{
          borderBottom: expanded ? "none" : `1px solid ${line}`,
          boxShadow: tone ? `inset 3px 0 0 0 ${tone}` : undefined,
          background: isSelected
            ? isDark
              ? "rgba(143,214,177,0.06)"
              : "rgba(78,148,112,0.05)"
            : undefined,
        }}
      >
        <td className="px-3 py-3">
          <input
            type="checkbox"
            aria-label={`Select ${c.title}`}
            checked={isSelected}
            onChange={onToggleSelect}
          />
        </td>
        <td className="px-3 py-3">
          <Link
            href={`/admin/courses/${c.course_id}/edit`}
            className="block group"
          >
            <span style={{ fontWeight: 600, color: ink }}>{c.title}</span>
            <span
              style={{
                display: "block",
                fontSize: 11,
                color: muted,
                fontFamily:
                  "var(--font-jetbrains-mono), ui-monospace, monospace",
              }}
            >
              {c.slug}
            </span>
          </Link>
        </td>
        <td className="px-3 py-3">
          <DifficultyEdit
            value={c.difficulty}
            onSave={async (v) => onPatch({ difficulty: v })}
            isDark={isDark}
            ink={ink}
            line={line}
          />
        </td>
        <td className="px-3 py-3 text-right">
          <PriceEdit
            priceCents={c.price_cents}
            onSave={async (cents) => onPatch({ price_cents: cents })}
            isDark={isDark}
            ink={ink}
            line={line}
          />
        </td>
        <td className="px-3 py-3 text-center">
          <button
            type="button"
            aria-label={
              isFeatured ? `Unfeature ${c.title}` : `Feature ${c.title}`
            }
            aria-pressed={isFeatured}
            onClick={() => onToggleFeature(isFeatured)}
            style={{
              background: "transparent",
              border: "none",
              cursor: "pointer",
              color: isFeatured ? "#d6a54d" : muted,
            }}
          >
            <Star
              size={16}
              fill={isFeatured ? "#d6a54d" : "none"}
              strokeWidth={1.8}
            />
          </button>
        </td>
        <td
          className="px-3 py-3 text-right"
          style={{
            fontFamily: "var(--font-jetbrains-mono), ui-monospace, monospace",
            fontVariantNumeric: "tabular-nums",
            fontWeight: 600,
          }}
        >
          {c.enrollments}
        </td>
        <td className="px-3 py-3 min-w-[140px]">
          {enoughEnrollments ? (
            <Bar
              value={completionPct}
              color="#1D9E75"
              isDark={isDark}
            />
          ) : (
            <span style={{ fontSize: 11, color: muted }}>—</span>
          )}
        </td>
        <td className="px-3 py-3 min-w-[140px]">
          <Bar
            value={confusionPct}
            color={confTone.fill}
            muted={confTone.muted}
            isDark={isDark}
          />
        </td>
        <td className="px-3 py-3">
          {c.negative_feedback_count > 0 ? (
            <Pill bg="#d96252" color="#fff">
              {c.negative_feedback_count}
              <AlertTriangle size={11} style={{ marginLeft: 4 }} />
            </Pill>
          ) : (
            <Pill
              bg={isDark ? "rgba(255,255,255,0.06)" : "#efe9d8"}
              color={muted}
            >
              {c.open_feedback_count}
            </Pill>
          )}
        </td>
        <td className="px-3 py-3">
          <PublishSwitch
            value={c.is_published}
            onToggle={onTogglePublish}
            label={c.title}
          />
        </td>
        <td className="px-3 py-3 text-right">
          <div className="inline-flex items-center gap-1">
            <IconBtn
              ink={ink}
              line={line}
              onClick={onToggleExpand}
              ariaLabel={
                expanded
                  ? `Hide coupons for ${c.title}`
                  : `Open coupons for ${c.title}`
              }
            >
              {expanded ? (
                <ChevronDown size={14} />
              ) : (
                <ChevronRight size={14} />
              )}
            </IconBtn>
            <a
              href={`/catalog/${c.slug}`}
              target="_blank"
              rel="noopener noreferrer"
              aria-label={`Preview ${c.title} as a student`}
              className="inline-grid place-items-center rounded-md transition"
              style={{
                width: 28,
                height: 28,
                color: muted,
                textDecoration: "none",
              }}
            >
              <Eye size={14} />
            </a>
            <Link
              href={`/admin/courses/${c.course_id}/edit`}
              aria-label={`Edit ${c.title}`}
              className="inline-grid place-items-center rounded-md transition"
              style={{ width: 28, height: 28, color: muted }}
            >
              <Pencil size={14} />
            </Link>
          </div>
        </td>
      </tr>
      {expanded ? (
        <tr style={{ borderBottom: `1px solid ${line}` }}>
          <td colSpan={11} className="px-3 py-3">
            <CouponsDrillDown
              course={c}
              isDark={isDark}
              ink={ink}
              muted={muted}
              line={line}
            />
          </td>
        </tr>
      ) : null}
    </>
  );
}

function IconBtn({
  children,
  onClick,
  ariaLabel,
  ink,
  line,
}: {
  children: React.ReactNode;
  onClick: () => void;
  ariaLabel: string;
  ink: string;
  line: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={ariaLabel}
      className="inline-grid place-items-center rounded-md transition"
      style={{
        width: 28,
        height: 28,
        background: "transparent",
        color: ink,
        border: `1px solid ${line}`,
        cursor: "pointer",
      }}
    >
      {children}
    </button>
  );
}

function Pill({
  children,
  bg,
  color,
}: {
  children: React.ReactNode;
  bg: string;
  color: string;
}) {
  return (
    <span
      className="inline-flex items-center rounded-full px-2.5 py-0.5"
      style={{
        background: bg,
        color,
        fontSize: 11,
        fontWeight: 700,
        letterSpacing: "0.12em",
        textTransform: "uppercase",
      }}
    >
      {children}
    </span>
  );
}

function Bar({
  value,
  color,
  muted,
  isDark,
}: {
  value: number;
  color: string;
  muted?: boolean;
  isDark: boolean;
}) {
  return (
    <div className="flex items-center gap-2">
      <div
        role="progressbar"
        aria-valuenow={value}
        aria-valuemin={0}
        aria-valuemax={100}
        className="h-2 flex-1 rounded-full overflow-hidden min-w-[60px]"
        style={{
          background: isDark ? "rgba(255,255,255,0.07)" : "#e8e0cc",
        }}
      >
        <div
          className="h-full rounded-full"
          style={{
            width: `${Math.max(0, Math.min(100, value))}%`,
            backgroundColor: color,
            opacity: muted ? 0.5 : 1,
          }}
        />
      </div>
      <span
        className="w-9 text-right"
        style={{
          fontFamily: "var(--font-jetbrains-mono), ui-monospace, monospace",
          fontVariantNumeric: "tabular-nums",
          fontSize: 11,
          opacity: muted ? 0.65 : 1,
        }}
      >
        {value}%
      </span>
    </div>
  );
}

function PublishSwitch({
  value,
  onToggle,
  label,
}: {
  value: boolean;
  onToggle: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={value}
      aria-label={`${value ? "Unpublish" : "Publish"} ${label}`}
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        onToggle();
      }}
      className="relative inline-flex h-5 w-9 items-center rounded-full transition"
      style={{
        backgroundColor: value ? "#1D9E75" : "rgba(127,127,127,0.35)",
        cursor: "pointer",
        border: "none",
        padding: 0,
      }}
    >
      <span
        className="inline-block h-4 w-4 rounded-full bg-white shadow transition"
        style={{
          transform: value ? "translateX(18px)" : "translateX(2px)",
        }}
      />
    </button>
  );
}

// ---------- inline edit: difficulty ----------

function DifficultyEdit({
  value,
  onSave,
  isDark,
  ink,
  line,
}: {
  value: string;
  onSave: (v: string) => Promise<unknown>;
  isDark: boolean;
  ink: string;
  line: string;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  async function commit(next: string) {
    if (next === value) {
      setEditing(false);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onSave(next);
      setSaved(true);
      window.setTimeout(() => setSaved(false), 1000);
    } catch (e) {
      setError((e as Error)?.message ?? "Failed");
      setDraft(value);
    } finally {
      setBusy(false);
      setEditing(false);
    }
  }

  if (editing) {
    return (
      <select
        autoFocus
        disabled={busy}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => commit(draft)}
        onKeyDown={(e) => {
          if (e.key === "Enter") commit(draft);
          if (e.key === "Escape") setEditing(false);
        }}
        style={{
          background: isDark ? "rgba(255,255,255,0.06)" : "#fff",
          color: ink,
          border: `1px solid ${line}`,
          borderRadius: 6,
          padding: "2px 6px",
          fontSize: 12,
          textTransform: "capitalize",
        }}
      >
        {DIFFICULTIES.map((d) => (
          <option key={d} value={d}>
            {d}
          </option>
        ))}
      </select>
    );
  }

  return (
    <button
      type="button"
      onClick={() => setEditing(true)}
      title={error ?? "Click to edit"}
      className="inline-flex items-center rounded-full px-2.5 py-0.5 transition"
      style={{
        background: isDark ? "rgba(255,255,255,0.05)" : "#efe9d8",
        color: ink,
        fontSize: 11,
        fontWeight: 700,
        letterSpacing: "0.12em",
        textTransform: "uppercase",
        border: error ? "1px solid #d96252" : "1px solid transparent",
        cursor: "pointer",
      }}
    >
      {value}
      {saved ? <span style={{ marginLeft: 4, color: "#1D9E75" }}>✓</span> : null}
    </button>
  );
}

// ---------- inline edit: price (with >20% delta confirm) ----------

function PriceEdit({
  priceCents,
  onSave,
  isDark,
  ink,
  line,
}: {
  priceCents: number;
  onSave: (cents: number) => Promise<unknown>;
  isDark: boolean;
  ink: string;
  line: string;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(String(Math.round(priceCents / 100)));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  async function commit() {
    const dollars = Number(draft);
    if (!Number.isFinite(dollars) || dollars < 0) {
      setError("Invalid");
      setDraft(String(Math.round(priceCents / 100)));
      setEditing(false);
      return;
    }
    const cents = Math.round(dollars * 100);
    if (cents === priceCents) {
      setEditing(false);
      return;
    }
    // >20% delta confirm
    const oldDollars = priceCents / 100;
    const delta =
      oldDollars === 0
        ? cents > 0
          ? Infinity
          : 0
        : Math.abs(dollars - oldDollars) / oldDollars;
    if (delta > 0.2) {
      const ok = window.confirm(
        `Price change from $${oldDollars.toFixed(0)} to $${dollars.toFixed(0)} is more than 20%. Confirm?`,
      );
      if (!ok) {
        setDraft(String(Math.round(priceCents / 100)));
        setEditing(false);
        return;
      }
    }
    setBusy(true);
    setError(null);
    try {
      await onSave(cents);
      setSaved(true);
      window.setTimeout(() => setSaved(false), 1000);
    } catch (e) {
      setError((e as Error)?.message ?? "Failed");
      setDraft(String(Math.round(priceCents / 100)));
    } finally {
      setBusy(false);
      setEditing(false);
    }
  }

  if (editing) {
    return (
      <input
        autoFocus
        disabled={busy}
        type="number"
        min={0}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") commit();
          if (e.key === "Escape") setEditing(false);
        }}
        style={{
          width: 80,
          background: isDark ? "rgba(255,255,255,0.06)" : "#fff",
          color: ink,
          border: `1px solid ${line}`,
          borderRadius: 6,
          padding: "2px 6px",
          fontSize: 12,
          textAlign: "right",
          fontFamily: "var(--font-jetbrains-mono), ui-monospace, monospace",
        }}
      />
    );
  }

  return (
    <button
      type="button"
      onClick={() => setEditing(true)}
      title={error ?? "Click to edit"}
      style={{
        background: "transparent",
        border: error ? "1px solid #d96252" : "1px solid transparent",
        borderRadius: 6,
        padding: "2px 6px",
        cursor: "pointer",
        color: ink,
        fontFamily: "var(--font-jetbrains-mono), ui-monospace, monospace",
        fontVariantNumeric: "tabular-nums",
      }}
    >
      {formatPrice(priceCents)}
      {saved ? <span style={{ marginLeft: 4, color: "#1D9E75" }}>✓</span> : null}
    </button>
  );
}

// ---------- coupons drill-down (inline expanded row) ----------

function CouponsDrillDown({
  course,
  isDark,
  ink,
  muted,
  line,
}: {
  course: CourseHealth;
  isDark: boolean;
  ink: string;
  muted: string;
  line: string;
}) {
  const { data: coupons, isLoading } = useCourseCoupons(course.course_id);
  const create = useCreateCoupon();
  const update = useUpdateCoupon();
  const del = useDeleteCoupon();
  const [showForm, setShowForm] = useState(false);
  const [code, setCode] = useState("");
  const [pct, setPct] = useState("20");
  const [maxRedemptions, setMaxRedemptions] = useState("");
  const [expiresAt, setExpiresAt] = useState("");

  const subCardBg = isDark ? "rgba(255,255,255,0.02)" : "rgba(255,252,245,0.5)";

  async function submitCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!code.trim()) return;
    await create.mutateAsync({
      code: code.trim().toUpperCase(),
      course_id: course.course_id,
      percent_off: Number(pct),
      max_redemptions: maxRedemptions ? Number(maxRedemptions) : null,
      expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
    });
    setCode("");
    setPct("20");
    setMaxRedemptions("");
    setExpiresAt("");
    setShowForm(false);
  }

  return (
    <div
      className="rounded-xl p-4"
      style={{
        background: subCardBg,
        border: `1px solid ${line}`,
      }}
    >
      <div className="flex items-center justify-between mb-3">
        <h3
          style={{
            fontFamily: "var(--font-fraunces), Georgia, serif",
            fontSize: 18,
            fontWeight: 500,
            letterSpacing: "-0.02em",
          }}
        >
          Coupons for {course.title}
        </h3>
        <button
          type="button"
          onClick={() => setShowForm((s) => !s)}
          className="inline-flex items-center gap-1 rounded-full px-3 py-1"
          style={{
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            background: "#1D9E75",
            color: "#fff",
            border: "none",
            cursor: "pointer",
          }}
        >
          <Plus size={12} /> Add coupon
        </button>
      </div>

      {showForm ? (
        <form
          onSubmit={submitCreate}
          className="grid grid-cols-1 md:grid-cols-5 gap-2 mb-3"
        >
          <Input
            placeholder="Code (e.g. SAVE20)"
            value={code}
            onChange={setCode}
            isDark={isDark}
            ink={ink}
            line={line}
          />
          <Input
            placeholder="% off"
            type="number"
            value={pct}
            onChange={setPct}
            isDark={isDark}
            ink={ink}
            line={line}
          />
          <Input
            placeholder="Max redemptions"
            type="number"
            value={maxRedemptions}
            onChange={setMaxRedemptions}
            isDark={isDark}
            ink={ink}
            line={line}
          />
          <Input
            placeholder="Expires"
            type="datetime-local"
            value={expiresAt}
            onChange={setExpiresAt}
            isDark={isDark}
            ink={ink}
            line={line}
          />
          <button
            type="submit"
            disabled={create.isPending}
            style={{
              fontSize: 11,
              fontWeight: 700,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              background: "#1D9E75",
              color: "#fff",
              border: "none",
              borderRadius: 6,
              padding: "6px 12px",
              cursor: "pointer",
              opacity: create.isPending ? 0.6 : 1,
            }}
          >
            Create
          </button>
        </form>
      ) : null}

      {isLoading ? (
        <div style={{ color: muted, fontSize: 13 }}>Loading coupons…</div>
      ) : (coupons ?? []).length === 0 ? (
        <div style={{ color: muted, fontSize: 13 }}>
          No coupons yet. Create one above.
        </div>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr style={{ borderBottom: `1px solid ${line}` }}>
              <Th>Code</Th>
              <Th align="right">% off</Th>
              <Th align="right">Used / Limit</Th>
              <Th>Expires</Th>
              <Th>Active</Th>
              <Th align="right">Delete</Th>
            </tr>
          </thead>
          <tbody>
            {(coupons ?? []).map((cp) => (
              <tr key={cp.id} style={{ borderBottom: `1px solid ${line}` }}>
                <td
                  className="px-3 py-2"
                  style={{
                    fontFamily:
                      "var(--font-jetbrains-mono), ui-monospace, monospace",
                    fontWeight: 600,
                  }}
                >
                  {cp.code}
                </td>
                <td className="px-3 py-2 text-right">{cp.percent_off}%</td>
                <td
                  className="px-3 py-2 text-right"
                  style={{
                    fontFamily:
                      "var(--font-jetbrains-mono), ui-monospace, monospace",
                  }}
                >
                  {cp.redemption_count} / {cp.max_redemptions ?? "∞"}
                </td>
                <td className="px-3 py-2" style={{ color: muted, fontSize: 12 }}>
                  {formatDate(cp.expires_at)}
                </td>
                <td className="px-3 py-2">
                  <PublishSwitch
                    value={cp.is_active}
                    onToggle={() =>
                      update.mutate({
                        couponId: cp.id,
                        body: { is_active: !cp.is_active },
                      })
                    }
                    label={cp.code}
                  />
                </td>
                <td className="px-3 py-2 text-right">
                  <button
                    type="button"
                    onClick={() => {
                      if (
                        window.confirm(`Delete coupon ${cp.code}? Cannot undo.`)
                      ) {
                        del.mutate({
                          couponId: cp.id,
                          courseId: course.course_id,
                        });
                      }
                    }}
                    aria-label={`Delete ${cp.code}`}
                    style={{
                      background: "transparent",
                      border: "none",
                      color: "#d96252",
                      cursor: "pointer",
                    }}
                  >
                    <Trash2 size={14} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function Input({
  value,
  onChange,
  placeholder,
  type = "text",
  isDark,
  ink,
  line,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
  isDark: boolean;
  ink: string;
  line: string;
}) {
  return (
    <input
      type={type}
      value={value}
      placeholder={placeholder}
      onChange={(e) => onChange(e.target.value)}
      style={{
        background: isDark ? "rgba(255,255,255,0.06)" : "#fff",
        color: ink,
        border: `1px solid ${line}`,
        borderRadius: 6,
        padding: "6px 10px",
        fontSize: 13,
      }}
    />
  );
}

// =====================================================================
// BUNDLES TAB
// =====================================================================

function BundlesTab({ isDark, ink, muted, line }: TabProps) {
  const { data, isLoading, isError } = useBundles();
  const { data: coursesData } = useCoursesHealth();
  const createBundle = useCreateBundle();
  const updateBundle = useUpdateBundle();
  const deleteBundle = useDeleteBundle();
  const addCourse = useAddCourseToBundle();
  const removeCourse = useRemoveCourseFromBundle();

  const [creating, setCreating] = useState(false);
  const [expandedBundleId, setExpandedBundleId] = useState<string | null>(null);

  const courses = coursesData?.items ?? [];
  const bundles = data?.items ?? [];

  if (isLoading) return <SkeletonRows />;
  if (isError)
    return (
      <ErrorCard message="Failed to load bundles" isDark={isDark} line={line} />
    );

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p style={{ color: muted, fontSize: 13 }}>
          {bundles.length} bundle{bundles.length === 1 ? "" : "s"}
        </p>
        <button
          type="button"
          onClick={() => setCreating(true)}
          className="inline-flex items-center gap-1 rounded-full px-3 py-1"
          style={{
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            background: "#1D9E75",
            color: "#fff",
            border: "none",
            cursor: "pointer",
          }}
        >
          <Plus size={12} /> New bundle
        </button>
      </div>

      {creating ? (
        <BundleCreateForm
          courses={courses}
          isDark={isDark}
          ink={ink}
          muted={muted}
          line={line}
          onCancel={() => setCreating(false)}
          onSubmit={async (body) => {
            await createBundle.mutateAsync(body);
            setCreating(false);
          }}
        />
      ) : null}

      {bundles.length === 0 ? (
        <EmptyCard
          title="No bundles yet"
          body="Bundle multiple courses for discounted package pricing."
          isDark={isDark}
          line={line}
          muted={muted}
        />
      ) : (
        <div className="grid grid-cols-1 gap-3">
          {bundles.map((b) => (
            <BundleCard
              key={b.id}
              bundle={b}
              courses={courses}
              expanded={expandedBundleId === b.id}
              onToggleExpand={() =>
                setExpandedBundleId(expandedBundleId === b.id ? null : b.id)
              }
              onUpdate={(body) =>
                updateBundle.mutateAsync({ bundleId: b.id, body })
              }
              onDelete={() => {
                if (window.confirm(`Delete bundle "${b.title}"?`)) {
                  deleteBundle.mutate(b.id);
                }
              }}
              onAddCourse={(courseId) =>
                addCourse.mutateAsync({ bundleId: b.id, courseId })
              }
              onRemoveCourse={(courseId) =>
                removeCourse.mutateAsync({ bundleId: b.id, courseId })
              }
              isDark={isDark}
              ink={ink}
              muted={muted}
              line={line}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function BundleCreateForm({
  courses,
  isDark,
  ink,
  muted,
  line,
  onCancel,
  onSubmit,
}: {
  courses: CourseHealth[];
  isDark: boolean;
  ink: string;
  muted: string;
  line: string;
  onCancel: () => void;
  onSubmit: (body: {
    slug: string;
    title: string;
    description?: string;
    price_cents: number;
    course_ids: string[];
    is_published?: boolean;
  }) => Promise<unknown>;
}) {
  const [title, setTitle] = useState("");
  const [slug, setSlug] = useState("");
  const [description, setDescription] = useState("");
  const [priceDollars, setPriceDollars] = useState("99");
  const [selected, setSelected] = useState<Set<string>>(new Set());

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    await onSubmit({
      title,
      slug,
      description: description || undefined,
      price_cents: Math.round(Number(priceDollars) * 100),
      course_ids: Array.from(selected),
    });
  }

  return (
    <form
      onSubmit={submit}
      className="rounded-xl p-4 space-y-3"
      style={{
        background: isDark
          ? "rgba(255,255,255,0.04)"
          : "rgba(255,255,255,0.7)",
        border: `1px solid ${line}`,
      }}
    >
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
        <Input
          value={title}
          onChange={setTitle}
          placeholder="Bundle title"
          isDark={isDark}
          ink={ink}
          line={line}
        />
        <Input
          value={slug}
          onChange={setSlug}
          placeholder="bundle-slug"
          isDark={isDark}
          ink={ink}
          line={line}
        />
        <Input
          value={priceDollars}
          onChange={setPriceDollars}
          placeholder="Price ($)"
          type="number"
          isDark={isDark}
          ink={ink}
          line={line}
        />
        <Input
          value={description}
          onChange={setDescription}
          placeholder="Description (optional)"
          isDark={isDark}
          ink={ink}
          line={line}
        />
      </div>
      <div>
        <div
          style={{
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: "0.14em",
            textTransform: "uppercase",
            color: muted,
            marginBottom: 6,
          }}
        >
          Courses in bundle
        </div>
        <div className="flex flex-wrap gap-1.5">
          {courses.map((c) => {
            const on = selected.has(c.course_id);
            return (
              <button
                type="button"
                key={c.course_id}
                onClick={() =>
                  setSelected((prev) => {
                    const next = new Set(prev);
                    if (next.has(c.course_id)) next.delete(c.course_id);
                    else next.add(c.course_id);
                    return next;
                  })
                }
                style={{
                  fontSize: 11,
                  fontWeight: 700,
                  letterSpacing: "0.06em",
                  background: on ? "#1D9E75" : "transparent",
                  color: on ? "#fff" : ink,
                  border: `1px solid ${on ? "transparent" : line}`,
                  borderRadius: 999,
                  padding: "3px 10px",
                  cursor: "pointer",
                }}
              >
                {c.title}
              </button>
            );
          })}
        </div>
      </div>
      <div className="flex gap-2">
        <button
          type="submit"
          style={{
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            background: "#1D9E75",
            color: "#fff",
            border: "none",
            borderRadius: 999,
            padding: "6px 14px",
            cursor: "pointer",
          }}
        >
          Create bundle
        </button>
        <button
          type="button"
          onClick={onCancel}
          style={{
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            background: "transparent",
            color: ink,
            border: `1px solid ${line}`,
            borderRadius: 999,
            padding: "6px 14px",
            cursor: "pointer",
          }}
        >
          Cancel
        </button>
      </div>
    </form>
  );
}

function BundleCard({
  bundle,
  courses,
  expanded,
  onToggleExpand,
  onUpdate,
  onDelete,
  onAddCourse,
  onRemoveCourse,
  isDark,
  ink,
  muted,
  line,
}: {
  bundle: BundleSummary;
  courses: CourseHealth[];
  expanded: boolean;
  onToggleExpand: () => void;
  onUpdate: (body: Record<string, unknown>) => Promise<unknown>;
  onDelete: () => void;
  onAddCourse: (courseId: string) => Promise<unknown>;
  onRemoveCourse: (courseId: string) => Promise<unknown>;
  isDark: boolean;
  ink: string;
  muted: string;
  line: string;
}) {
  const createCoupon = useCreateCoupon();
  const [showCouponForm, setShowCouponForm] = useState(false);
  const [couponCode, setCouponCode] = useState("");
  const [couponPct, setCouponPct] = useState("20");

  const inBundle = new Set(bundle.course_ids);
  const available = courses.filter((c) => !inBundle.has(c.course_id));

  return (
    <div
      className="rounded-xl p-4"
      style={{
        background: isDark
          ? "rgba(255,255,255,0.04)"
          : "rgba(255,255,255,0.7)",
        border: `1px solid ${line}`,
      }}
    >
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex-1 min-w-0">
          <div
            style={{
              fontFamily: "var(--font-fraunces), Georgia, serif",
              fontSize: 18,
              fontWeight: 500,
              letterSpacing: "-0.02em",
            }}
          >
            {bundle.title}
          </div>
          <div
            style={{
              fontSize: 11,
              color: muted,
              fontFamily:
                "var(--font-jetbrains-mono), ui-monospace, monospace",
            }}
          >
            {bundle.slug} · {bundle.course_count} courses ·{" "}
            {formatPrice(bundle.price_cents)}
          </div>
        </div>
        <div className="flex items-center gap-3">
          <PublishSwitch
            value={bundle.is_published}
            onToggle={() => onUpdate({ is_published: !bundle.is_published })}
            label={bundle.title}
          />
          <button
            type="button"
            onClick={onToggleExpand}
            style={{
              fontSize: 11,
              fontWeight: 700,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              background: "transparent",
              color: ink,
              border: `1px solid ${line}`,
              borderRadius: 999,
              padding: "4px 12px",
              cursor: "pointer",
            }}
          >
            {expanded ? "Close" : "Edit"}
          </button>
          <button
            type="button"
            onClick={onDelete}
            aria-label="Delete bundle"
            style={{
              background: "transparent",
              border: "none",
              color: "#d96252",
              cursor: "pointer",
            }}
          >
            <Trash2 size={14} />
          </button>
        </div>
      </div>

      {expanded ? (
        <div className="mt-4 space-y-3">
          <BundleEditFields
            bundle={bundle}
            onUpdate={onUpdate}
            isDark={isDark}
            ink={ink}
            muted={muted}
            line={line}
          />
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div
              className="rounded-xl p-3"
              style={{
                background: isDark
                  ? "rgba(255,255,255,0.02)"
                  : "rgba(255,252,245,0.6)",
                border: `1px solid ${line}`,
              }}
            >
              <div
                style={{
                  fontSize: 10,
                  fontWeight: 700,
                  letterSpacing: "0.14em",
                  textTransform: "uppercase",
                  color: muted,
                  marginBottom: 8,
                }}
              >
                In bundle
              </div>
              <div className="flex flex-col gap-1.5">
                {(bundle.expanded_courses ?? []).map((c) => (
                  <button
                    key={c.id}
                    type="button"
                    onClick={() => onRemoveCourse(c.id)}
                    className="flex items-center justify-between rounded-md px-2 py-1.5"
                    style={{
                      background: "transparent",
                      border: `1px solid ${line}`,
                      color: ink,
                      cursor: "pointer",
                    }}
                  >
                    <span style={{ fontSize: 13 }}>{c.title}</span>
                    <X size={12} />
                  </button>
                ))}
                {(bundle.expanded_courses ?? []).length === 0 ? (
                  <span style={{ color: muted, fontSize: 12 }}>Empty</span>
                ) : null}
              </div>
            </div>
            <div
              className="rounded-xl p-3"
              style={{
                background: isDark
                  ? "rgba(255,255,255,0.02)"
                  : "rgba(255,252,245,0.6)",
                border: `1px solid ${line}`,
              }}
            >
              <div
                style={{
                  fontSize: 10,
                  fontWeight: 700,
                  letterSpacing: "0.14em",
                  textTransform: "uppercase",
                  color: muted,
                  marginBottom: 8,
                }}
              >
                Available
              </div>
              <div className="flex flex-col gap-1.5">
                {available.map((c) => (
                  <button
                    key={c.course_id}
                    type="button"
                    onClick={() => onAddCourse(c.course_id)}
                    className="flex items-center justify-between rounded-md px-2 py-1.5"
                    style={{
                      background: "transparent",
                      border: `1px solid ${line}`,
                      color: ink,
                      cursor: "pointer",
                    }}
                  >
                    <span style={{ fontSize: 13 }}>{c.title}</span>
                    <Plus size={12} />
                  </button>
                ))}
                {available.length === 0 ? (
                  <span style={{ color: muted, fontSize: 12 }}>
                    All courses added
                  </span>
                ) : null}
              </div>
            </div>
          </div>

          <div>
            <button
              type="button"
              onClick={() => setShowCouponForm((s) => !s)}
              style={{
                fontSize: 11,
                fontWeight: 700,
                letterSpacing: "0.12em",
                textTransform: "uppercase",
                background: "transparent",
                color: "#1D9E75",
                border: "none",
                cursor: "pointer",
                textDecoration: "underline",
              }}
            >
              {showCouponForm ? "Hide" : "Apply coupon to this bundle"}
            </button>
            {showCouponForm ? (
              <form
                className="mt-2 flex flex-wrap gap-2 items-center"
                onSubmit={async (e) => {
                  e.preventDefault();
                  await createCoupon.mutateAsync({
                    code: couponCode.trim().toUpperCase(),
                    bundle_id: bundle.id,
                    percent_off: Number(couponPct),
                  });
                  setCouponCode("");
                  setShowCouponForm(false);
                }}
              >
                <Input
                  value={couponCode}
                  onChange={setCouponCode}
                  placeholder="Code"
                  isDark={isDark}
                  ink={ink}
                  line={line}
                />
                <Input
                  value={couponPct}
                  onChange={setCouponPct}
                  type="number"
                  placeholder="% off"
                  isDark={isDark}
                  ink={ink}
                  line={line}
                />
                <button
                  type="submit"
                  style={{
                    fontSize: 11,
                    fontWeight: 700,
                    letterSpacing: "0.12em",
                    textTransform: "uppercase",
                    background: "#1D9E75",
                    color: "#fff",
                    border: "none",
                    borderRadius: 999,
                    padding: "6px 14px",
                    cursor: "pointer",
                  }}
                >
                  Create
                </button>
              </form>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function BundleEditFields({
  bundle,
  onUpdate,
  isDark,
  ink,
  muted,
  line,
}: {
  bundle: BundleSummary;
  onUpdate: (body: Record<string, unknown>) => Promise<unknown>;
  isDark: boolean;
  ink: string;
  muted: string;
  line: string;
}) {
  const [title, setTitle] = useState(bundle.title);
  const [slug, setSlug] = useState(bundle.slug);
  const [description, setDescription] = useState(bundle.description ?? "");
  const [priceDollars, setPriceDollars] = useState(
    String(Math.round(bundle.price_cents / 100)),
  );

  async function save() {
    await onUpdate({
      title,
      slug,
      description: description || null,
      price_cents: Math.round(Number(priceDollars) * 100),
    });
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-4 gap-2">
      <Input
        value={title}
        onChange={setTitle}
        placeholder="Title"
        isDark={isDark}
        ink={ink}
        line={line}
      />
      <Input
        value={slug}
        onChange={setSlug}
        placeholder="slug"
        isDark={isDark}
        ink={ink}
        line={line}
      />
      <Input
        value={priceDollars}
        onChange={setPriceDollars}
        type="number"
        placeholder="Price ($)"
        isDark={isDark}
        ink={ink}
        line={line}
      />
      <div className="flex gap-2">
        <Input
          value={description}
          onChange={setDescription}
          placeholder="Description"
          isDark={isDark}
          ink={ink}
          line={line}
        />
        <button
          type="button"
          onClick={save}
          style={{
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            background: "#1D9E75",
            color: "#fff",
            border: "none",
            borderRadius: 6,
            padding: "0 14px",
            cursor: "pointer",
          }}
        >
          Save
        </button>
      </div>
      <span className="sr-only" style={{ color: muted }}>
        Edit bundle fields
      </span>
    </div>
  );
}

// =====================================================================
// COUPONS TAB
// =====================================================================

function CouponsTab({ isDark, ink, muted, line }: TabProps) {
  const { data: coupons, isLoading, isError } = useAllCoupons();
  const { data: coursesData } = useCoursesHealth();
  const { data: bundlesData } = useBundles();
  const create = useCreateCoupon();
  const update = useUpdateCoupon();
  const del = useDeleteCoupon();
  const [filter, setFilter] = useState<CouponScopeFilter>("all");
  const [creating, setCreating] = useState(false);

  const courses = coursesData?.items ?? [];
  const bundles = bundlesData?.items ?? [];

  const courseTitle = (id: string | null) =>
    courses.find((c) => c.course_id === id)?.title ?? null;
  const bundleTitle = (id: string | null) =>
    bundles.find((b) => b.id === id)?.title ?? null;

  const all = useMemo(() => coupons ?? [], [coupons]);
  const [now] = useState<number>(() => Date.now());

  const counts = useMemo(() => {
    let active = 0;
    let expired = 0;
    for (const c of all) {
      const isExpired =
        c.expires_at != null && new Date(c.expires_at).getTime() < now;
      if (isExpired) expired += 1;
      else if (c.is_active) active += 1;
    }
    return { active, expired };
  }, [all, now]);

  const filtered = useMemo(() => {
    return all.filter((c) => {
      const isExpired =
        c.expires_at != null && new Date(c.expires_at).getTime() < now;
    switch (filter) {
      case "all":
        return true;
      case "active":
        return c.is_active && !isExpired;
      case "expired":
        return isExpired;
      case "course":
        return c.course_id != null;
      case "bundle":
        return c.bundle_id != null;
      case "platform":
        return c.course_id == null && c.bundle_id == null;
      }
    });
  }, [all, filter, now]);

  if (isLoading) return <SkeletonRows />;
  if (isError)
    return (
      <ErrorCard message="Failed to load coupons" isDark={isDark} line={line} />
    );

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <p style={{ color: muted, fontSize: 13 }}>
          {counts.active} active · {counts.expired} expired ·{" "}
          {all.length} total
        </p>
        <button
          type="button"
          onClick={() => setCreating(true)}
          className="inline-flex items-center gap-1 rounded-full px-3 py-1"
          style={{
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            background: "#1D9E75",
            color: "#fff",
            border: "none",
            cursor: "pointer",
          }}
        >
          <Plus size={12} /> New coupon
        </button>
      </div>

      <div className="flex flex-wrap gap-2">
        {(
          [
            "all",
            "active",
            "expired",
            "course",
            "bundle",
            "platform",
          ] as CouponScopeFilter[]
        ).map((k) => {
          const active = filter === k;
          return (
            <button
              key={k}
              type="button"
              onClick={() => setFilter(k)}
              style={{
                fontSize: 11,
                fontWeight: 700,
                letterSpacing: "0.12em",
                textTransform: "uppercase",
                background: active ? "#1D9E75" : "transparent",
                color: active ? "#fff" : ink,
                border: `1px solid ${active ? "transparent" : line}`,
                borderRadius: 999,
                padding: "4px 12px",
                cursor: "pointer",
              }}
            >
              {k}
            </button>
          );
        })}
      </div>

      {creating ? (
        <CouponCreateForm
          courses={courses}
          bundles={bundles}
          isDark={isDark}
          ink={ink}
          muted={muted}
          line={line}
          onCancel={() => setCreating(false)}
          onSubmit={async (body) => {
            await create.mutateAsync(body);
            setCreating(false);
          }}
        />
      ) : null}

      {filtered.length === 0 ? (
        <EmptyCard
          title="No coupons"
          body="No coupons match this filter."
          isDark={isDark}
          line={line}
          muted={muted}
        />
      ) : (
        <div
          className="overflow-x-auto rounded-xl"
          style={{
            background: isDark
              ? "rgba(255,255,255,0.04)"
              : "rgba(255,255,255,0.7)",
            border: `1px solid ${line}`,
          }}
        >
          <table className="w-full text-sm">
            <thead>
              <tr style={{ borderBottom: `1px solid ${line}` }}>
                <Th>Code</Th>
                <Th>Scope</Th>
                <Th align="right">% off</Th>
                <Th align="right">Used / Limit</Th>
                <Th>Expires</Th>
                <Th>Active</Th>
                <Th align="right">Delete</Th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((cp) => {
                const scope = cp.course_id
                  ? courseTitle(cp.course_id) ?? "Course"
                  : cp.bundle_id
                    ? bundleTitle(cp.bundle_id) ?? "Bundle"
                    : "Platform";
                return (
                  <tr
                    key={cp.id}
                    style={{ borderBottom: `1px solid ${line}` }}
                  >
                    <td
                      className="px-3 py-2"
                      style={{
                        fontFamily:
                          "var(--font-jetbrains-mono), ui-monospace, monospace",
                        fontWeight: 600,
                      }}
                    >
                      {cp.code}
                    </td>
                    <td className="px-3 py-2">{scope}</td>
                    <td className="px-3 py-2 text-right">{cp.percent_off}%</td>
                    <td
                      className="px-3 py-2 text-right"
                      style={{
                        fontFamily:
                          "var(--font-jetbrains-mono), ui-monospace, monospace",
                      }}
                    >
                      {cp.redemption_count} / {cp.max_redemptions ?? "∞"}
                    </td>
                    <td
                      className="px-3 py-2"
                      style={{ color: muted, fontSize: 12 }}
                    >
                      {formatDate(cp.expires_at)}
                    </td>
                    <td className="px-3 py-2">
                      <PublishSwitch
                        value={cp.is_active}
                        onToggle={() =>
                          update.mutate({
                            couponId: cp.id,
                            body: { is_active: !cp.is_active },
                          })
                        }
                        label={cp.code}
                      />
                    </td>
                    <td className="px-3 py-2 text-right">
                      <button
                        type="button"
                        onClick={() => {
                          if (
                            window.confirm(`Delete coupon ${cp.code}?`)
                          ) {
                            del.mutate({
                              couponId: cp.id,
                              courseId: cp.course_id,
                            });
                          }
                        }}
                        aria-label={`Delete ${cp.code}`}
                        style={{
                          background: "transparent",
                          border: "none",
                          color: "#d96252",
                          cursor: "pointer",
                        }}
                      >
                        <Trash2 size={14} />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function CouponCreateForm({
  courses,
  bundles,
  isDark,
  ink,
  muted,
  line,
  onCancel,
  onSubmit,
}: {
  courses: CourseHealth[];
  bundles: BundleSummary[];
  isDark: boolean;
  ink: string;
  muted: string;
  line: string;
  onCancel: () => void;
  onSubmit: (body: {
    code: string;
    course_id?: string | null;
    bundle_id?: string | null;
    percent_off: number;
    max_redemptions?: number | null;
    expires_at?: string | null;
  }) => Promise<unknown>;
}) {
  const [code, setCode] = useState("");
  const [pct, setPct] = useState("20");
  const [maxRed, setMaxRed] = useState("");
  const [expiresAt, setExpiresAt] = useState("");
  const [scope, setScope] = useState<string>("platform");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    let course_id: string | null = null;
    let bundle_id: string | null = null;
    if (scope.startsWith("c:")) course_id = scope.slice(2);
    else if (scope.startsWith("b:")) bundle_id = scope.slice(2);
    await onSubmit({
      code: code.trim().toUpperCase(),
      course_id,
      bundle_id,
      percent_off: Number(pct),
      max_redemptions: maxRed ? Number(maxRed) : null,
      expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
    });
  }

  return (
    <form
      onSubmit={submit}
      className="rounded-xl p-4"
      style={{
        background: isDark
          ? "rgba(255,255,255,0.04)"
          : "rgba(255,255,255,0.7)",
        border: `1px solid ${line}`,
      }}
    >
      <div className="grid grid-cols-1 md:grid-cols-3 gap-2 mb-2">
        <Input
          value={code}
          onChange={setCode}
          placeholder="CODE"
          isDark={isDark}
          ink={ink}
          line={line}
        />
        <Input
          value={pct}
          onChange={setPct}
          placeholder="% off"
          type="number"
          isDark={isDark}
          ink={ink}
          line={line}
        />
        <select
          value={scope}
          onChange={(e) => setScope(e.target.value)}
          style={{
            background: isDark ? "rgba(255,255,255,0.06)" : "#fff",
            color: ink,
            border: `1px solid ${line}`,
            borderRadius: 6,
            padding: "6px 10px",
            fontSize: 13,
          }}
        >
          <option value="platform">Platform-wide</option>
          <optgroup label="Course">
            {courses.map((c) => (
              <option key={c.course_id} value={`c:${c.course_id}`}>
                {c.title}
              </option>
            ))}
          </optgroup>
          <optgroup label="Bundle">
            {bundles.map((b) => (
              <option key={b.id} value={`b:${b.id}`}>
                {b.title}
              </option>
            ))}
          </optgroup>
        </select>
        <Input
          value={maxRed}
          onChange={setMaxRed}
          placeholder="Max redemptions"
          type="number"
          isDark={isDark}
          ink={ink}
          line={line}
        />
        <Input
          value={expiresAt}
          onChange={setExpiresAt}
          placeholder="Expires"
          type="datetime-local"
          isDark={isDark}
          ink={ink}
          line={line}
        />
        <div className="flex gap-2">
          <button
            type="submit"
            style={{
              fontSize: 11,
              fontWeight: 700,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              background: "#1D9E75",
              color: "#fff",
              border: "none",
              borderRadius: 999,
              padding: "6px 14px",
              cursor: "pointer",
              flex: 1,
            }}
          >
            Create
          </button>
          <button
            type="button"
            onClick={onCancel}
            style={{
              fontSize: 11,
              fontWeight: 700,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              background: "transparent",
              color: ink,
              border: `1px solid ${line}`,
              borderRadius: 999,
              padding: "6px 14px",
              cursor: "pointer",
            }}
          >
            Cancel
          </button>
        </div>
      </div>
      <span className="sr-only" style={{ color: muted }}>
        Create a new coupon
      </span>
    </form>
  );
}

// =====================================================================
// Shared empty / skeleton / error
// =====================================================================

function SkeletonRows() {
  return (
    <div className="space-y-2">
      {Array.from({ length: 4 }).map((_, i) => (
        <div
          key={i}
          className={cn("h-16 w-full animate-pulse rounded-xl")}
          style={{ background: "rgba(127,127,127,0.12)" }}
        />
      ))}
    </div>
  );
}

function ErrorCard({
  message,
  isDark,
  line,
}: {
  message: string;
  isDark: boolean;
  line: string;
}) {
  return (
    <div
      className="rounded-xl px-4 py-3"
      style={{
        background: isDark ? "rgba(217,98,82,0.10)" : "rgba(217,98,82,0.08)",
        border: `1px solid ${line}`,
        color: "#d96252",
        fontSize: 13,
      }}
    >
      {message}
    </div>
  );
}

function EmptyCard({
  title,
  body,
  isDark,
  line,
  muted,
}: {
  title: string;
  body: string;
  isDark: boolean;
  line: string;
  muted: string;
}) {
  return (
    <div
      className="rounded-xl px-6 py-10 text-center"
      style={{
        background: isDark
          ? "rgba(255,255,255,0.03)"
          : "rgba(255,255,255,0.6)",
        border: `1px solid ${line}`,
      }}
    >
      <div
        style={{
          fontFamily: "var(--font-fraunces), Georgia, serif",
          fontSize: 18,
          fontWeight: 500,
          letterSpacing: "-0.02em",
        }}
      >
        {title}
      </div>
      <p style={{ color: muted, fontSize: 13, marginTop: 4 }}>{body}</p>
    </div>
  );
}
