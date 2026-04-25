"use client";

import { useMemo, useState, type MouseEvent } from "react";
import { useRouter } from "next/navigation";
import { useSetV8Topbar } from "@/components/v8/v8-topbar-context";
import {
  useMySkillStates,
  useSavedSkillPath,
  useSkillGraph,
} from "@/lib/hooks/use-skills";
import { useMyProgress } from "@/lib/hooks/use-progress";
import { useMyGoal } from "@/lib/hooks/use-goal";
import { useAuthStore } from "@/stores/auth-store";
import type {
  CourseProgress,
  LessonProgressItem,
  MasteryLevel,
  SkillNode,
  UserSkillState,
} from "@/lib/api-client";

type StarState = "done" | "current" | "upcoming" | "goal";

interface ConstellationStar {
  label: string;
  sub: string;
  state: StarState;
  badge: string;
}

interface LessonRowData {
  id: string;
  title: string;
  meta: string;
  duration: string;
  status: "done" | "current" | "upcoming";
}

const DEFAULT_STARS: ConstellationStar[] = [
  { label: "Python<br>Developer", sub: "Current base", state: "done", badge: "1" },
  { label: "Data<br>Analyst", sub: "58 days", state: "current", badge: "2" },
  { label: "Data<br>Scientist", sub: "Next arc", state: "upcoming", badge: "3" },
  { label: "ML<br>Engineer", sub: "Later", state: "upcoming", badge: "4" },
  { label: "GenAI<br>Engineer", sub: "Advanced", state: "upcoming", badge: "5" },
  { label: "Senior<br>GenAI Eng.", sub: "Destination", state: "goal", badge: "★" },
];

const DEFAULT_LESSONS: LessonRowData[] = [
  {
    id: "default-1",
    title: "Python fundamentals",
    meta: "Required · complete · 2 labs finished",
    duration: "45m",
    status: "done",
  },
  {
    id: "default-2",
    title: "OOP and modules",
    meta: "Required · complete · 2 labs finished",
    duration: "50m",
    status: "done",
  },
  {
    id: "default-3",
    title: "APIs and async programming",
    meta: "Required · today · 3 labs · tap to expand",
    duration: "45m",
    status: "current",
  },
  {
    id: "default-4",
    title: "Testing and debugging",
    meta: "Required · upcoming · 3 labs queued",
    duration: "40m",
    status: "upcoming",
  },
];

function masteryToState(level: MasteryLevel | undefined): StarState {
  if (!level) return "upcoming";
  if (level === "mastered") return "done";
  if (level === "proficient") return "current";
  return "upcoming";
}

function pickConstellation(
  graph: SkillNode[] | undefined,
  states: UserSkillState[] | undefined,
  saved: string[] | undefined,
  goalStatement: string | undefined,
): ConstellationStar[] {
  if (!graph || graph.length === 0) {
    return withGoal(DEFAULT_STARS, goalStatement);
  }
  const stateById = new Map<string, MasteryLevel>(
    (states ?? []).map((s) => [s.skill_id, s.mastery_level]),
  );
  const ordered: SkillNode[] = (() => {
    if (saved && saved.length > 0) {
      const byId = new Map(graph.map((n) => [n.id, n]));
      const fromSaved = saved.map((id) => byId.get(id)).filter((n): n is SkillNode => !!n);
      if (fromSaved.length >= 5) return fromSaved.slice(0, 5);
    }
    return [...graph].sort((a, b) => a.difficulty - b.difficulty).slice(0, 5);
  })();

  const stars: ConstellationStar[] = ordered.map((node, idx) => {
    const state = masteryToState(stateById.get(node.id));
    return {
      label: node.name.replace(/\s+/, "<br>"),
      sub: state === "done" ? "Mastered" : state === "current" ? "In progress" : "Upcoming",
      state,
      badge: String(idx + 1),
    };
  });

  return withGoal(stars, goalStatement);
}

function withGoal(stars: ConstellationStar[], goalStatement: string | undefined): ConstellationStar[] {
  const goal: ConstellationStar = {
    label: goalStatement
      ? truncateGoal(goalStatement)
      : "Senior<br>GenAI Eng.",
    sub: "Destination",
    state: "goal",
    badge: "★",
  };
  const trimmed = stars.slice(0, 5);
  while (trimmed.length < 5) {
    trimmed.push(DEFAULT_STARS[trimmed.length]);
  }
  return [...trimmed, goal];
}

function truncateGoal(s: string): string {
  const words = s.trim().split(/\s+/).slice(0, 3);
  if (words.length <= 1) return words.join(" ");
  const half = Math.ceil(words.length / 2);
  return `${words.slice(0, half).join(" ")}<br>${words.slice(half).join(" ")}`;
}

function pickPythonCourse(progress: CourseProgress[] | undefined): CourseProgress | undefined {
  if (!progress || progress.length === 0) return undefined;
  return (
    progress.find((c) => /python/i.test(c.course_title)) ?? progress[0]
  );
}

function lessonsFromCourse(course: CourseProgress | undefined): LessonRowData[] {
  if (!course || course.lessons.length === 0) return DEFAULT_LESSONS;
  const items = course.lessons.slice(0, 4);
  const firstUnfinished = items.findIndex((l) => l.status !== "completed");
  return items.map((l: LessonProgressItem, idx) => {
    const isCurrent = idx === firstUnfinished;
    const status: LessonRowData["status"] =
      l.status === "completed" ? "done" : isCurrent ? "current" : "upcoming";
    return {
      id: l.id,
      title: l.title,
      meta:
        status === "done"
          ? "Required · complete"
          : status === "current"
            ? "Required · today · tap for labs"
            : "Required · upcoming",
      duration: `${30 + (idx % 3) * 10}m`,
      status,
    };
  });
}

interface StarProps {
  star: ConstellationStar;
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
  return (
    <div className="star-node">
      <div className={cls}>{star.badge}</div>
      <div className="star-label" dangerouslySetInnerHTML={{ __html: star.label }} />
      <div className="star-sub">{star.sub}</div>
    </div>
  );
}

interface LessonRowProps {
  row: LessonRowData;
  expanded: boolean;
  onToggle: () => void;
  onOpenLab: (lab: string) => void;
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
          <div className="small">{row.duration}</div>
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
                  Short hands-on builds that bridge the lesson to your capstone. Do at least one
                  before Studio.
                </div>
              </div>
              <div className="s">
                <span className="count" data-to={1}>
                  1
                </span>{" "}
                of <span className="count" data-to={3}>3</span> complete
              </div>
            </div>
            <div className="lab-item">
              <div className="lab-icon done">✓</div>
              <div className="lab-body">
                <b>Lab A · Retry with exponential backoff</b>
                <span>
                  Write a function that retries a flaky API call up to 3 times, doubling the wait
                  each attempt.
                </span>
              </div>
              <div className="lab-meta">
                <span className="lab-time">25 min</span>
                <button
                  className="lab-btn ghost"
                  onClick={(e: MouseEvent<HTMLButtonElement>) => e.stopPropagation()}
                >
                  Review
                </button>
              </div>
            </div>
            <div className="lab-item">
              <div className="lab-icon live">●</div>
              <div className="lab-body">
                <b>Lab B · Rate-limit aware queue</b>
                <span>
                  Build a small queue that throttles outbound requests to stay under a 10/min
                  ceiling without dropping calls.
                </span>
              </div>
              <div className="lab-meta">
                <span className="lab-time">40 min</span>
                <button
                  className="lab-btn"
                  onClick={(e: MouseEvent<HTMLButtonElement>) => {
                    e.stopPropagation();
                    onOpenLab("B");
                  }}
                >
                  Open in Studio
                </button>
              </div>
            </div>
            <div className="lab-item">
              <div className="lab-icon lock">○</div>
              <div className="lab-body">
                <b>Lab C · Concurrent batch processor</b>
                <span>
                  Fan out 50 prompts through{" "}
                  <code style={{ fontFamily: "var(--mono)", fontSize: ".9em" }}>
                    asyncio.gather
                  </code>{" "}
                  and collect results without losing ordering.
                </span>
              </div>
              <div className="lab-meta">
                <span className="lab-time">55 min</span>
                <button
                  className="lab-btn lock"
                  onClick={(e: MouseEvent<HTMLButtonElement>) => e.stopPropagation()}
                >
                  Unlocks after Lab B
                </button>
              </div>
            </div>
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
      <div className="small">{row.duration}</div>
    </div>
  );
}

export function PathScreen() {
  useSetV8Topbar({
    eyebrow: "Your path",
    titleHtml: "A believable ladder from your current role to your <i>future one</i>.",
    chips: [],
    progress: 40,
  });

  const router = useRouter();
  const isAuthed = useAuthStore((s) => s.isAuthenticated);
  const graphQ = useSkillGraph();
  const statesQ = useMySkillStates();
  const savedPathQ = useSavedSkillPath();
  const progressQ = useMyProgress();
  const goalQ = useMyGoal();

  const [expanded, setExpanded] = useState(false);

  const stars = useMemo(
    () =>
      pickConstellation(
        graphQ.data?.nodes,
        isAuthed ? statesQ.data : undefined,
        isAuthed ? savedPathQ.data?.skill_ids : undefined,
        isAuthed ? goalQ.data?.success_statement : undefined,
      ),
    [graphQ.data, statesQ.data, savedPathQ.data, goalQ.data, isAuthed],
  );

  const pythonCourse = useMemo(
    () => pickPythonCourse(isAuthed ? progressQ.data?.courses : undefined),
    [progressQ.data, isAuthed],
  );

  const lessons = useMemo(() => lessonsFromCourse(pythonCourse), [pythonCourse]);

  const overall = isAuthed
    ? Math.round(pythonCourse?.progress_percentage ?? progressQ.data?.overall_progress ?? 33)
    : 33;

  const handleOpenLab = (lab: string) => {
    router.push(`/studio?lab=${lab}`);
  };

  const handleUnlockTrack = () => {
    router.push("/catalog");
  };

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
                The path page is calmer in v5. It keeps aspiration visible, but lets the student
                read the journey as a believable sequence of roles, lessons, and evidence — not as
                a wall of competing motivation.
              </p>
              <div className="path-constellation">
                {stars.map((s, i) => (
                  <StarNode key={`${s.badge}-${i}`} star={s} />
                ))}
              </div>
            </section>

            <section className="card pad reveal">
              <div className="section-title">
                <div>
                  <h4>Level 1 · {pythonCourse?.course_title ?? "Python Developer"}</h4>
                  <p>The role you are solidifying before promotion.</p>
                </div>
                <div className="chip forest">
                  <span className="count" data-to={overall}>
                    {overall}
                  </span>
                  % complete
                </div>
              </div>
              <div className="role-ladder">
                <article className="role-step current">
                  <div className="role-badge">1</div>
                  <div>
                    <h5>{pythonCourse?.course_title ?? "Python Developer"}</h5>
                    <p>
                      Clean functions, async I/O, error handling, and working habits every role
                      ahead will depend on.
                    </p>
                    <div className="lesson-list">
                      {lessons.map((row) => (
                        <LessonRow
                          key={row.id}
                          row={row}
                          expanded={row.status === "current" && expanded}
                          onToggle={() => setExpanded((v) => !v)}
                          onOpenLab={handleOpenLab}
                        />
                      ))}
                    </div>
                  </div>
                  <div className="pct">
                    <span className="count" data-to={overall}>
                      {overall}
                    </span>
                    %
                  </div>
                </article>

                <article className="role-step">
                  <div className="role-badge">2</div>
                  <div>
                    <h5>Data Analyst</h5>
                    <p>
                      SQL joins that feel natural, pandas that scales, and dashboards a stakeholder
                      reads without a walkthrough.
                    </p>
                    <div className="track-unlock">
                      <div>
                        <div className="k">Unlock this track</div>
                        <b>8 lessons · 22 labs · 1 capstone · mentor reviews</b>
                        <span>
                          Includes SQL fundamentals, pandas at scale, dashboard design, and a
                          capstone graded by a working analyst.
                        </span>
                      </div>
                      <div className="track-actions">
                        <div className="track-price">
                          <span className="cur">$</span>
                          <span className="amt">89</span>
                          <span className="per">one time</span>
                        </div>
                        <button
                          className="btn primary"
                          onClick={handleUnlockTrack}
                          aria-label="Unlock Data Analyst track"
                        >
                          Unlock track
                        </button>
                      </div>
                    </div>
                  </div>
                </article>

                <article className="role-step goal">
                  <div className="role-badge">★</div>
                  <div>
                    <h5>Senior GenAI Engineer</h5>
                    <p>
                      Agentic systems, production RAG, LLMOps, and the credibility that comes from
                      repeated role-earned growth.
                    </p>
                  </div>
                </article>
              </div>
            </section>
          </div>

          <aside className="grid">
            <section className="card pad reveal">
              <div className="section-title">
                <div>
                  <h4>Proof wall</h4>
                  <p>Examples should inspire, not overwhelm.</p>
                </div>
              </div>
              <div className="proof-wall" style={{ gridTemplateColumns: "1fr" }}>
                <article className="proof-card">
                  <pre>{`async def ask(prompt):
    try:
        resp = await client.messages.create(...)
        return resp.content[0].text
    except APIError:
        return await retry(prompt)`}</pre>
                  <div className="meta">
                    <strong>Priya V.</strong>
                    <span className="small">87/100 · promoted</span>
                  </div>
                </article>
                <article className="proof-card">
                  <pre>{`class RateLimiter:
    async def wait(self):
        while self.full():
            await asyncio.sleep(1)
        return True`}</pre>
                  <div className="meta">
                    <strong>Marcus K.</strong>
                    <span className="small">91/100 · promoted</span>
                  </div>
                </article>
              </div>
            </section>
          </aside>
        </div>
      </div>
    </section>
  );
}
