"use client";

/**
 * P-Path1 (2026-04-27) — Path screen rewired against the new
 * `/api/v1/path/summary` aggregator.
 *
 * Removes:
 *   - DEFAULT_STARS / DEFAULT_LESSONS / hardcoded labs A/B/C
 *   - hardcoded "$89 one time" track-unlock pricing
 *   - hardcoded "Senior GenAI Eng." goal star copy
 *   - Priya / Marcus proof-wall samples
 *
 * The constellation, ladder rungs (with real labs from `Exercise` rows),
 * upsell pricing (from `courses.price_cents`), goal label (from
 * `goal_contracts.target_role`), and proof wall (from peer-shared
 * `exercise_submissions`) all flow from a single round-trip.
 */

import { useMemo, useState, type MouseEvent } from "react";
import { useRouter } from "next/navigation";

import { useSetV8Topbar } from "@/components/v8/v8-topbar-context";
import { usePathSummary } from "@/lib/hooks/use-path-summary";
import type {
  PathLab,
  PathLevel,
  PathLesson,
  PathStar,
} from "@/lib/api-client";

interface StarProps {
  star: PathStar;
}

function StarNode({ star }: StarProps) {
  const cls =
    star.state === "done"
      ? "star done"
      : star.state === "current"
        ? "star current"
        : star.state === "goal"
          ? "star goal"
          : "star";
  // The aggregator emits `\n` — split into a paragraph so we don't need
  // dangerouslySetInnerHTML and we keep the same two-line visual.
  const lines = star.label.split("\n");
  return (
    <div className="star-node">
      <div className={cls}>{star.badge}</div>
      <div className="star-label">
        {lines.map((line, idx) => (
          <span key={idx}>
            {line}
            {idx < lines.length - 1 ? <br /> : null}
          </span>
        ))}
      </div>
      <div className="star-sub">{star.sub}</div>
    </div>
  );
}

interface LessonRowProps {
  row: PathLesson;
  expanded: boolean;
  onToggle: () => void;
  onOpenLab: (labId: string) => void;
}

function LessonRow({ row, expanded, onToggle, onOpenLab }: LessonRowProps) {
  if (row.status === "current") {
    return (
      <>
        <div
          className={`lesson-row has-labs${expanded ? " open" : ""}`}
          onClick={onToggle}
          role="button"
          tabIndex={0}
          aria-expanded={expanded}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              onToggle();
            }
          }}
        >
          <div className="lesson-icon">●</div>
          <div>
            <strong>{row.title}</strong>
            <span>{row.meta}</span>
          </div>
          <div className="small">{row.duration_minutes}m</div>
          <span className="lab-caret" aria-hidden="true">
            ›
          </span>
        </div>
        <div className={`lab-tray${expanded ? " open" : ""}`}>
          <div className="lab-tray-inner">
            <div className="lab-tray-head">
              <div>
                <div className="k">Labs for this lesson</div>
                <div className="s" style={{ marginTop: 4 }}>
                  Short hands-on builds that bridge the lesson to your
                  capstone. Do at least one before Studio.
                </div>
              </div>
              {row.labs.length > 0 ? (
                <div className="s">
                  <span className="count" data-to={row.labs_completed}>
                    {row.labs_completed}
                  </span>{" "}
                  of <span className="count" data-to={row.labs.length}>{row.labs.length}</span>{" "}
                  complete
                </div>
              ) : null}
            </div>
            {row.labs.length === 0 ? (
              <div className="lab-item" style={{ opacity: 0.7 }}>
                <div className="lab-icon lock">○</div>
                <div className="lab-body">
                  <b>Labs coming soon</b>
                  <span>
                    The course author is still wiring hands-on builds for
                    this lesson. Watch the lesson, then ping the tutor for
                    practice prompts.
                  </span>
                </div>
              </div>
            ) : (
              row.labs.map((lab) => <LabItem key={lab.id} lab={lab} onOpen={onOpenLab} />)
            )}
          </div>
        </div>
      </>
    );
  }

  const icon = row.status === "done" ? "✓" : "○";
  return (
    <div className="lesson-row">
      <div className="lesson-icon">{icon}</div>
      <div>
        <strong>{row.title}</strong>
        <span>{row.meta}</span>
      </div>
      <div className="small">{row.duration_minutes}m</div>
    </div>
  );
}

function LabItem({ lab, onOpen }: { lab: PathLab; onOpen: (id: string) => void }) {
  const iconClass =
    lab.status === "done" ? "done" : lab.status === "current" ? "live" : "lock";
  const iconChar = lab.status === "done" ? "✓" : lab.status === "current" ? "●" : "○";
  return (
    <div className="lab-item">
      <div className={`lab-icon ${iconClass}`}>{iconChar}</div>
      <div className="lab-body">
        <b>{lab.title}</b>
        <span>
          {lab.description ?? "Hands-on build linked to this lesson."}
        </span>
      </div>
      <div className="lab-meta">
        <span className="lab-time">{lab.duration_minutes} min</span>
        {lab.status === "done" ? (
          <button
            className="lab-btn ghost"
            onClick={(e: MouseEvent<HTMLButtonElement>) => e.stopPropagation()}
          >
            Review
          </button>
        ) : lab.status === "current" ? (
          <button
            className="lab-btn"
            onClick={(e: MouseEvent<HTMLButtonElement>) => {
              e.stopPropagation();
              onOpen(lab.id);
            }}
          >
            Open in Studio
          </button>
        ) : (
          <button
            className="lab-btn lock"
            onClick={(e: MouseEvent<HTMLButtonElement>) => e.stopPropagation()}
          >
            Locked
          </button>
        )}
      </div>
    </div>
  );
}

function formatPrice(cents: number, currency: string): string {
  const amount = cents / 100;
  // Whole-dollar amounts render without ".00"; partial cents keep two decimals.
  const isWhole = Number.isInteger(amount);
  const symbol = currency.toUpperCase() === "INR" ? "₹" : "$";
  return `${symbol}${isWhole ? amount.toString() : amount.toFixed(2)}`;
}

interface CurrentLevelProps {
  level: PathLevel;
  expandedLessonId: string | null;
  onToggleLesson: (id: string) => void;
  onOpenLab: (id: string) => void;
}

function CurrentLevelCard({
  level,
  expandedLessonId,
  onToggleLesson,
  onOpenLab,
}: CurrentLevelProps) {
  return (
    <article className="role-step current">
      <div className="role-badge">{level.badge}</div>
      <div>
        <h5>{level.title}</h5>
        <p>{level.blurb}</p>
        <div className="lesson-list">
          {level.lessons.length === 0 ? (
            <p className="small" style={{ opacity: 0.7 }}>
              No lessons yet — your active course will populate here once
              you enroll.
            </p>
          ) : (
            level.lessons.map((row) => (
              <LessonRow
                key={row.id}
                row={row}
                expanded={
                  row.status === "current" && expandedLessonId === row.id
                }
                onToggle={() => onToggleLesson(row.id)}
                onOpenLab={onOpenLab}
              />
            ))
          )}
        </div>
      </div>
      <div className="pct">
        <span className="count" data-to={level.progress_percentage}>
          {level.progress_percentage}
        </span>
        %
      </div>
    </article>
  );
}

interface UpsellProps {
  level: PathLevel;
  onUnlock: () => void;
}

function UpsellCard({ level, onUnlock }: UpsellProps) {
  const priceLabel =
    level.unlock_price_cents != null
      ? formatPrice(level.unlock_price_cents, level.unlock_currency ?? "USD")
      : null;
  const lessonLabel =
    level.unlock_lesson_count != null && level.unlock_lab_count != null
      ? `${level.unlock_lesson_count} lessons · ${level.unlock_lab_count} labs · 1 capstone · mentor reviews`
      : "Curriculum, labs, and a capstone graded by a working practitioner.";

  return (
    <article className="role-step">
      <div className="role-badge">{level.badge}</div>
      <div>
        <h5>{level.title}</h5>
        <p>{level.blurb}</p>
        <div className="track-unlock">
          <div>
            <div className="k">Unlock this track</div>
            <b>{lessonLabel}</b>
            <span>{level.blurb}</span>
          </div>
          <div className="track-actions">
            {priceLabel ? (
              <div className="track-price">
                <span className="cur">
                  {priceLabel.replace(/[\d.,]/g, "").trim()}
                </span>
                <span className="amt">
                  {priceLabel.replace(/[^\d.,]/g, "")}
                </span>
                <span className="per">one time</span>
              </div>
            ) : null}
            <button
              className="btn primary"
              onClick={onUnlock}
              aria-label={`Unlock ${level.title}`}
            >
              Unlock track
            </button>
          </div>
        </div>
      </div>
    </article>
  );
}

function GoalCard({ level }: { level: PathLevel }) {
  return (
    <article className="role-step goal">
      <div className="role-badge">{level.badge}</div>
      <div>
        <h5>{level.title}</h5>
        <p>{level.blurb}</p>
      </div>
    </article>
  );
}

export function PathScreen() {
  const router = useRouter();
  const { data, isLoading } = usePathSummary();

  useSetV8Topbar({
    eyebrow: "Your path",
    titleHtml:
      "A believable ladder from your current role to your <i>future one</i>.",
    chips: [],
    progress: data?.overall_progress ?? 0,
  });

  const [expandedLessonId, setExpandedLessonId] = useState<string | null>(null);

  const handleOpenLab = (labId: string) => {
    router.push(`/studio?lab=${labId}`);
  };

  const handleUnlockTrack = () => {
    router.push("/catalog");
  };

  const handleToggleLesson = (id: string) => {
    setExpandedLessonId((prev) => (prev === id ? null : id));
  };

  const currentLevel = useMemo(
    () => data?.levels.find((l) => l.state === "current"),
    [data],
  );
  const upsellLevel = useMemo(
    () => data?.levels.find((l) => l.state === "upcoming"),
    [data],
  );
  const goalLevel = useMemo(
    () => data?.levels.find((l) => l.state === "goal"),
    [data],
  );

  return (
    <section className="screen active">
      <div className="pad">
        <div className="grid path-grid">
          <div className="grid">
            <section className="card path-hero reveal">
              <div className="eyebrow">Your path</div>
              <h3>
                From who you are now to who you are <i>becoming</i>.
              </h3>
              <p>
                The path keeps aspiration visible, but lets the journey read
                as a believable sequence of roles, lessons, and evidence —
                not a wall of competing motivation.
              </p>
              {isLoading || !data ? (
                <div className="path-constellation" aria-busy="true">
                  {Array.from({ length: 6 }).map((_, i) => (
                    <div key={i} className="star-node" style={{ opacity: 0.4 }}>
                      <div className="star">·</div>
                      <div className="star-label">Loading…</div>
                      <div className="star-sub">&nbsp;</div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="path-constellation">
                  {data.constellation.map((s, i) => (
                    <StarNode key={`${s.badge}-${i}`} star={s} />
                  ))}
                </div>
              )}
            </section>

            <section className="card pad reveal">
              <div className="section-title">
                <div>
                  <h4>
                    Level 1 ·{" "}
                    {currentLevel?.title ?? data?.active_course_title ?? "Your active course"}
                  </h4>
                  <p>The role you are solidifying before promotion.</p>
                </div>
                <div className="chip forest">
                  <span
                    className="count"
                    data-to={currentLevel?.progress_percentage ?? data?.overall_progress ?? 0}
                  >
                    {currentLevel?.progress_percentage ?? data?.overall_progress ?? 0}
                  </span>
                  % complete
                </div>
              </div>
              <div className="role-ladder">
                {currentLevel ? (
                  <CurrentLevelCard
                    level={currentLevel}
                    expandedLessonId={expandedLessonId}
                    onToggleLesson={handleToggleLesson}
                    onOpenLab={handleOpenLab}
                  />
                ) : (
                  <article className="role-step">
                    <div className="role-badge">1</div>
                    <div>
                      <h5>Pick a starting course</h5>
                      <p>
                        Enroll in any track from the catalog and your active
                        ladder will appear here.
                      </p>
                      <div className="hero-actions" style={{ marginTop: 12 }}>
                        <button
                          className="btn primary"
                          onClick={() => router.push("/catalog")}
                        >
                          Browse the catalog
                        </button>
                      </div>
                    </div>
                  </article>
                )}

                {upsellLevel ? (
                  <UpsellCard level={upsellLevel} onUnlock={handleUnlockTrack} />
                ) : null}

                {goalLevel ? <GoalCard level={goalLevel} /> : null}
              </div>
            </section>
          </div>

          <aside className="grid">
            <section className="card pad reveal">
              <div className="section-title">
                <div>
                  <h4>Proof wall</h4>
                  <p>Examples from peers — should inspire, not overwhelm.</p>
                </div>
              </div>
              {data && data.proof_wall.length > 0 ? (
                <div
                  className="proof-wall"
                  style={{ gridTemplateColumns: "1fr" }}
                >
                  {data.proof_wall.map((entry) => (
                    <article key={entry.submission_id} className="proof-card">
                      <pre>{entry.code_snippet}</pre>
                      <div className="meta">
                        <strong>{entry.author_name}</strong>
                        <span className="small">
                          {entry.score}/100
                          {entry.promoted ? " · promoted" : ""}
                        </span>
                      </div>
                    </article>
                  ))}
                </div>
              ) : (
                <p className="small" style={{ opacity: 0.7 }}>
                  No peer-shared submissions yet. Be the first — share a
                  capstone build and other students will see it here.
                </p>
              )}
            </section>
          </aside>
        </div>
      </div>
    </section>
  );
}
