"use client";

import {
  type CSSProperties,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { useSetV8Topbar } from "@/components/v8/v8-topbar-context";
import { v8Toast } from "@/components/v8/v8-toast";
import {
  IntakeModal,
  TailoredResumeQuotaChip,
} from "@/components/features/tailored-resume";
import {
  MockInterviewWorkspace,
  isMockInterviewEnabled,
} from "@/components/features/mock-interview";
import {
  DecoderCard as JdDecoderCard,
  isJdDecoderEnabled,
} from "@/components/features/jd-decoder";
import {
  DiagnosticAnchor,
  isReadinessDiagnosticEnabled,
} from "@/components/features/readiness-diagnostic";
import {
  useMyResume,
  useRegenerateResume,
  useFitScore,
  useSaveJd,
  useJdLibrary,
  type JdLibraryItem,
} from "@/lib/hooks/use-career";
import { useMyProgress } from "@/lib/hooks/use-progress";
import {
  useReadinessOverview,
  useReadinessProof,
} from "@/lib/hooks/use-readiness-overview";
import {
  useRecordWorkspaceEvent,
  useFlushWorkspaceEvents,
} from "@/lib/hooks/use-readiness-events";
import {
  useApplicationKits,
  useBuildApplicationKit,
  useDeleteApplicationKit,
  applicationKitDownloadUrl,
} from "@/lib/hooks/use-application-kit";
import {
  useAutopsyList,
  useCreateAutopsy,
} from "@/lib/hooks/use-portfolio-autopsy";
import { useMyMockSessions } from "@/lib/hooks/use-mock-interview";
import type {
  ReadinessNextAction,
  ReadinessOverviewResponse,
  ProofResponse,
  ProofAutopsy,
  ProofMockReport,
  ProofCapstoneArtifact,
  ApplicationKitListItem,
} from "@/lib/api-client";
import { useAuthStore } from "@/stores/auth-store";

type ReadinessView = "overview" | "resume" | "jd" | "interview" | "proof" | "kit";

const VALID_VIEWS: ReadonlyArray<ReadinessView> = [
  "overview",
  "resume",
  "jd",
  "interview",
  "proof",
  "kit",
];

function safeRoute(s: string): ReadinessView {
  return (VALID_VIEWS as ReadonlyArray<string>).includes(s)
    ? (s as ReadinessView)
    : "overview";
}

// Human-readable CTA labels for each route — beats `Open ${route}` because
// "Open Jd" reads wrong.
const ROUTE_LABEL: Record<ReadinessView, string> = {
  overview: "Open Overview",
  resume: "Open Resume Lab",
  jd: "Open JD Match",
  interview: "Open Interview Coach",
  proof: "Open Proof Portfolio",
  kit: "Open Application Kit",
};

interface NavItem {
  id: ReadinessView;
  num: string;
  title: string;
  blurb: string;
}

const NAV_ITEMS: ReadonlyArray<NavItem> = [
  {
    id: "overview",
    num: "1",
    title: "Overview",
    blurb: "Readiness score, top three actions, one clearest next step.",
  },
  {
    id: "resume",
    num: "2",
    title: "Resume Lab",
    blurb: "Build a credible resume from capstones, reviews, and proof.",
  },
  {
    id: "jd",
    num: "3",
    title: "JD Match",
    blurb: "Compare yourself against a real role and map gaps to learning.",
  },
  {
    id: "interview",
    num: "4",
    title: "Interview Coach",
    blurb: "Practice answers using your own proof and get live feedback.",
  },
  {
    id: "proof",
    num: "5",
    title: "Proof Portfolio",
    blurb: "Package your strongest work into recruiter-friendly proof.",
  },
  {
    id: "kit",
    num: "6",
    title: "Application Kit",
    blurb: "Leave with the exact assets you need to apply with confidence.",
  },
];

interface JdPreset {
  text: string;
  score: number;
}

const JD_PRESETS: Record<"python" | "data" | "genai", JdPreset> = {
  python: {
    text:
      "Junior Python Developer — Backend / Tooling. Python, async I/O, API integration, production-quality tools, error handling, rate limits, env config, Git, testing.",
    score: 68,
  },
  data: {
    text:
      "Junior Data Analyst. SQL joins, pandas, reporting dashboards, stakeholder communication, Excel fluency, basic statistics, Python a plus.",
    score: 41,
  },
  genai: {
    text:
      "GenAI Engineer. Prompt engineering, RAG pipelines, vector stores, LLM evaluation, LangChain or similar, production deployment, observability.",
    score: 52,
  },
};

function useAnimatedBars(active: boolean): React.RefObject<HTMLDivElement | null> {
  const ref = useRef<HTMLDivElement | null>(null);
  useLayoutEffect(() => {
    if (!active || !ref.current) return;
    const bars = ref.current.querySelectorAll<HTMLElement>(".rd-bar-fill[data-width]");
    bars.forEach((el) => {
      el.style.width = "0%";
    });
    const raf = requestAnimationFrame(() => {
      window.setTimeout(() => {
        bars.forEach((el) => {
          const w = el.getAttribute("data-width");
          if (w) el.style.width = `${w}%`;
        });
      }, 120);
    });
    return () => cancelAnimationFrame(raf);
  }, [active]);
  return ref;
}

interface ViewProps {
  open: (v: ReadinessView) => void;
  active: boolean;
}

export function ReadinessScreen() {
  const [activeView, setActiveView] = useState<ReadinessView>("overview");
  const { data: progress } = useMyProgress();
  const { data: overview } = useReadinessOverview();
  const recordEvent = useRecordWorkspaceEvent();

  const readinessPct = useMemo(() => {
    if (overview) {
      return Math.max(0, Math.min(100, Math.round(overview.overall_readiness)));
    }
    if (!progress) return 62;
    return Math.max(0, Math.min(100, Math.round(progress.overall_progress)));
  }, [overview, progress]);

  const topbarChips = useMemo(() => {
    const chips: Array<{ label: string; variant: "forest" | "gold" | "ink" | "neutral" }> = [];
    const verdict = overview?.latest_verdict;
    if (verdict) {
      const label = verdict.next_action?.label ?? "";
      chips.push({
        label: `Latest: ${label.slice(0, 28)}`,
        variant: "forest",
      });
    }
    return chips;
  }, [overview]);

  useSetV8Topbar({
    eyebrow: "Career · Job readiness workspace",
    titleHtml: "Turn learning into <i>interviewable proof</i>.",
    chips: topbarChips,
    progress: readinessPct,
  });

  // view_opened telemetry: fires on mount and any subsequent activeView change.
  useEffect(() => {
    recordEvent(activeView, "view_opened");
  }, [activeView, recordEvent]);

  const open = useCallback((v: ReadinessView) => {
    setActiveView(v);
    if (typeof window !== "undefined") {
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  }, []);

  return (
    <section className="screen active" id="screen-readiness">
      <div className="pad">
        <div className="readiness-shell">
          <aside className="readiness-nav reveal in">
            <div className="rn-head">
              <div className="rn-k">Inside this workspace</div>
              <div className="rn-t">Start with diagnosis.</div>
              <div className="rn-s">
                Only one focused tool should be open at a time. The overview stays
                calm; deeper work happens inside dedicated subpages.
              </div>
            </div>
            <div className="rn-list">
              {NAV_ITEMS.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={`rn-btn${activeView === item.id ? " on" : ""}`}
                  onClick={() => open(item.id)}
                >
                  <div className="rn-no">{item.num}</div>
                  <div>
                    <b>{item.title}</b>
                    <span>{item.blurb}</span>
                  </div>
                </button>
              ))}
            </div>
          </aside>

          <div>
            <OverviewView
              open={open}
              active={activeView === "overview"}
              readinessPct={readinessPct}
            />
            <ResumeView open={open} active={activeView === "resume"} />
            <JdMatchView open={open} active={activeView === "jd"} />
            <InterviewCoachView open={open} active={activeView === "interview"} />
            <ProofView open={open} active={activeView === "proof"} />
            <KitView open={open} active={activeView === "kit"} />
          </div>
        </div>
      </div>
    </section>
  );
}

interface OverviewViewProps extends ViewProps {
  readinessPct: number;
}

function OverviewView(props: OverviewViewProps) {
  // Feature-flagged swap. The live overview now renders REAL data from
  // useReadinessOverview() — a hero score card, sub-scores breakdown,
  // top actions, recommended sequence, and the diagnostic anchor at the
  // bottom. The legacy demo block below is kept ONLY for the kill-switch
  // path where the diagnostic flag is off. While the overview hook is
  // loading or the user is unauthenticated we render an honest skeleton
  // — the legacy "62%" demo data would be misleading.
  const isAuthed = useAuthStore((s) => s.isAuthenticated);
  const overviewQuery = useReadinessOverview();

  if (isReadinessDiagnosticEnabled()) {
    if (!isAuthed || overviewQuery.isLoading || !overviewQuery.data) {
      return <OverviewSkeleton active={props.active} />;
    }
    return <OverviewViewLive {...props} data={overviewQuery.data} />;
  }
  return <OverviewViewLegacy {...props} />;
}

interface OverviewSkeletonProps {
  active: boolean;
}

function OverviewSkeleton({ active }: OverviewSkeletonProps) {
  return (
    <div
      className={`view${active ? " active" : ""}`}
      id="rd-overview"
      data-testid="rd-overview-skeleton"
    >
      <section className="rd-hero reveal in">
        <div className="rd-hero-grid">
          <div>
            <div className="eyebrow">Overview · Start here</div>
            <div className="rd-skel rd-skel-line" style={{ width: "75%", height: 28 }} />
            <div className="rd-skel rd-skel-line" style={{ width: "92%", height: 14, marginTop: 12 }} />
            <div className="rd-skel rd-skel-line" style={{ width: "60%", height: 14, marginTop: 8 }} />
          </div>
          <div className="score-card">
            <div className="rd-skel rd-skel-ring" />
            <div className="rd-skel rd-skel-line" style={{ width: "70%", height: 14, marginTop: 12 }} />
            <div className="rd-skel rd-skel-line" style={{ width: "50%", height: 12, marginTop: 6 }} />
          </div>
        </div>
      </section>
      <div className="rd-stack">
        <div className="rd-2col">
          <section className="card pad reveal in delay-1">
            <div className="rd-skel rd-skel-line" style={{ width: "40%", height: 16 }} />
            <div className="rd-skel rd-skel-line" style={{ width: "85%", height: 14, marginTop: 10 }} />
            <div className="rd-skel rd-skel-line" style={{ width: "80%", height: 14, marginTop: 8 }} />
            <div className="rd-skel rd-skel-line" style={{ width: "70%", height: 14, marginTop: 8 }} />
          </section>
          <section className="card pad reveal in delay-2">
            <div className="rd-skel rd-skel-line" style={{ width: "40%", height: 16 }} />
            <div className="rd-skel rd-skel-line" style={{ width: "85%", height: 14, marginTop: 10 }} />
            <div className="rd-skel rd-skel-line" style={{ width: "80%", height: 14, marginTop: 8 }} />
            <div className="rd-skel rd-skel-line" style={{ width: "70%", height: 14, marginTop: 8 }} />
          </section>
        </div>
      </div>
    </div>
  );
}

interface OverviewViewLiveProps extends OverviewViewProps {
  data: ReadinessOverviewResponse;
}

function bandTagline(score: number): string {
  if (score >= 80) return "Apply with confidence.";
  if (score >= 60) return "Promising, not yet polished.";
  if (score >= 40) return "Building real signal.";
  return "Just getting started.";
}

function deltaPill(delta: number): string {
  if (delta > 0) return `▲ +${delta} this week`;
  if (delta < 0) return `▼ ${delta} this week`;
  return `0 this week`;
}

function skillSub(score: number): string {
  if (score >= 70) return "Your lessons and exercises suggest solid fundamentals.";
  if (score >= 40) return "Foundations are forming; one more focused module helps.";
  return "Core skill signal is thin — start a lesson sequence this week.";
}

function proofSub(score: number): string {
  if (score >= 70) return "Your work reads as recruiter-friendly proof.";
  if (score >= 60) return "Real work exists; refine packaging into shareable proof.";
  return "You have meaningful work, but it is not yet shareable proof.";
}

function interviewSub(score: number): string {
  if (score >= 70) return "You explain your work clearly under pressure.";
  if (score >= 50) return "Practice answers; clarity drops when stakes feel real.";
  return "You likely know more than you can currently explain under pressure.";
}

function targetingSub(score: number): string {
  if (score >= 70) return "Your proof aligns with the roles you target.";
  if (score >= 50) return "Tighten the match between proof and the roles you chase.";
  return "Pick one role family and shape every artifact toward it.";
}

interface SparklineProps {
  points: ReadonlyArray<{ score: number }>;
  fallback: number;
}

function Sparkline({ points, fallback }: SparklineProps) {
  const width = 90;
  const height = 28;
  const padX = 2;
  const padY = 6;
  if (points.length < 2) {
    const y = height - padY - ((Math.max(0, Math.min(100, fallback)) / 100) * (height - padY * 2));
    return (
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
        <polyline
          points={`${padX},${y} ${width - padX},${y}`}
          fill="none"
          stroke="#beddc8"
          strokeWidth="2"
          strokeLinecap="round"
        />
        <circle cx={width - padX} cy={y} r="3" fill="#beddc8" />
      </svg>
    );
  }
  const stepX = (width - padX * 2) / (points.length - 1);
  const coords = points.map((p, i) => {
    const x = padX + stepX * i;
    const clamped = Math.max(0, Math.min(100, p.score));
    const y = height - padY - (clamped / 100) * (height - padY * 2);
    return { x, y };
  });
  const polyline = coords.map((c) => `${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(" ");
  const last = coords[coords.length - 1];
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
      <polyline
        points={polyline}
        fill="none"
        stroke="#beddc8"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx={last.x} cy={last.y} r="3" fill="#beddc8" />
    </svg>
  );
}

const FALLBACK_TOP_ACTIONS: ReadinessNextAction[] = [
  {
    kind: "open_resume",
    route: "resume",
    label: "Build resume from proof",
  },
  {
    kind: "open_jd",
    route: "jd",
    label: "Match me to a real JD",
  },
];

function OverviewViewLive({ open, active, data }: OverviewViewLiveProps) {
  const ref = useAnimatedBars(active);
  const recordEvent = useRecordWorkspaceEvent();

  const role = data.target_role?.trim() || "Target role";
  const overall = Math.max(0, Math.min(100, Math.round(data.overall_readiness)));
  const tagline = bandTagline(overall);
  const delta = data.north_star?.delta_week ?? 0;
  const heroHeadline =
    overall < 30
      ? "Just starting your readiness picture."
      : `Hello, ${data.user_first_name}. You are close to interviewable.`;

  // Top two CTAs in the hero. Fall back to a sensible default pair when the
  // backend hasn't yet inferred enough actions to populate two slots.
  const ctaActions: ReadinessNextAction[] =
    data.top_actions.length >= 2
      ? data.top_actions.slice(0, 2)
      : data.top_actions.length === 1
        ? [data.top_actions[0], FALLBACK_TOP_ACTIONS[1]]
        : FALLBACK_TOP_ACTIONS;

  const handleAction = useCallback(
    (action: ReadinessNextAction) => {
      const route = safeRoute(action.route);
      recordEvent("overview", "cta_clicked", {
        kind: action.kind,
        route,
      });
      open(route);
    },
    [open, recordEvent],
  );

  const handleTool = useCallback(
    (tool: "resume" | "jd" | "interview" | "kit") => {
      recordEvent("overview", "cta_clicked", { tool });
      open(tool);
    },
    [open, recordEvent],
  );

  const subs = data.sub_scores;
  const proofTone: MetricRowProps["tone"] = subs.proof < 60 ? "warn" : undefined;
  const interviewTone: MetricRowProps["tone"] =
    subs.interview < 50 ? "low" : subs.interview < 70 ? "warn" : undefined;
  const targetingTone: MetricRowProps["tone"] = subs.targeting < 70 ? "warn" : undefined;

  return (
    <div className={`view${active ? " active" : ""}`} id="rd-overview" ref={ref}>
      <section className="rd-hero reveal in">
        <div className="rd-hero-grid">
          <div>
            <div className="eyebrow">Overview · Start here</div>
            <h3>
              {overall < 30 ? (
                heroHeadline
              ) : (
                <>
                  Hello, {data.user_first_name}. You are <i>close</i> to interviewable.
                </>
              )}
            </h3>
            <p>
              Job readiness is a clear diagnosis, a focused next action, and a
              believable path from today to a real offer.
            </p>
            <div className="rd-hero-actions">
              {ctaActions.map((action, idx) => (
                <button
                  key={`${action.kind}-${idx}`}
                  type="button"
                  className={idx === 0 ? "btn primary" : "btn secondary"}
                  onClick={() => handleAction(action)}
                >
                  {action.label}
                </button>
              ))}
            </div>
          </div>
          <div className="score-card">
            <div className="ring">
              <strong>
                <span className="count">{overall}</span>%
              </strong>
            </div>
            <div className="lbl">{role} readiness</div>
            <div className="tl">{tagline}</div>
            <div
              style={{
                marginTop: 10,
                display: "flex",
                gap: 8,
                alignItems: "center",
                flexWrap: "wrap",
              }}
            >
              <span className="delta-pill">{deltaPill(delta)}</span>
              <Sparkline points={data.trend_8w} fallback={overall} />
            </div>
            <div className="cp">
              Each completed lesson, capstone revision, and review response
              moves this score. Tracked weekly across the last 8 weeks.
            </div>
          </div>
        </div>
      </section>

      <div className="rd-stack">
        <div className="rd-2col">
          <section className="card pad reveal in delay-1">
            <div className="rd-section-k">Top next actions</div>
            <div className="rd-section-t">Do these before anything else.</div>
            <div className="rd-section-c">
              A job-readiness screen should lead with action, not six equally
              weighted tools. These are the next steps the system recommends
              based on your current proof and signal.
            </div>
            <div className="rd-actions">
              {data.top_actions.length === 0 ? (
                <div className="rd-section-c">
                  No new recommendations right now — keep building proof and
                  this list will refresh as your signal grows.
                </div>
              ) : (
                data.top_actions.slice(0, 3).map((action, idx) => (
                  <ActionRow
                    key={`${action.kind}-${idx}`}
                    num={String(idx + 1)}
                    title={action.label}
                    copy={`Recommended next step from your readiness profile (${action.kind.replace(/_/g, " ")}).`}
                    ctaLabel={ROUTE_LABEL[safeRoute(action.route)]}
                    onClick={() => handleAction(action)}
                  />
                ))
              )}
            </div>
          </section>

          <section className="card pad reveal in delay-2">
            <div className="rd-section-k">Readiness breakdown</div>
            <div className="rd-section-t">Make the score explain itself.</div>
            <div className="rd-section-c">
              One number motivates. A breakdown makes it actionable and
              trustworthy.
            </div>
            <div className="rd-metrics">
              <MetricRow
                label="Core skill readiness"
                sub={skillSub(subs.skill)}
                value={subs.skill}
              />
              <MetricRow
                label="Proof and portfolio"
                sub={proofSub(subs.proof)}
                value={subs.proof}
                tone={proofTone}
              />
              <MetricRow
                label="Interview performance"
                sub={interviewSub(subs.interview)}
                value={subs.interview}
                tone={interviewTone}
              />
              <MetricRow
                label="Role targeting"
                sub={targetingSub(subs.targeting)}
                value={subs.targeting}
                tone={targetingTone}
              />
            </div>
          </section>
        </div>

        <section className="card pad reveal in delay-3">
          <div className="rd-section-k">Recommended sequence</div>
          <div className="rd-section-t">One clear path, not a wall of options.</div>
          <div className="rd-section-c">
            Package proof → test against a real job → rehearse your story →
            export an application kit. Each step hands off cleanly to the next.
          </div>
          <div className="rd-tools">
            <ToolCard
              k="Step 1"
              t="Resume Lab"
              s="Build a resume from capstone work, review scores, and the strongest signals already earned inside the platform."
              arrow="Open focused workspace →"
              onClick={() => handleTool("resume")}
            />
            <ToolCard
              k="Step 2"
              t="JD Match"
              s="Paste a real job description and convert the fit analysis into a gap plan tied back to platform learning."
              arrow="Compare to a real role →"
              onClick={() => handleTool("jd")}
            />
            <ToolCard
              k="Step 3"
              t="Interview Coach"
              s="Rehearse answers using your own proof instead of memorizing generic talking points."
              arrow="Practice with live prompts →"
              onClick={() => handleTool("interview")}
            />
            <ToolCard
              k="Step 4"
              t="Application Kit"
              s="Leave with a ready set of assets: resume, project proof, pitch lines, and tailored role language."
              arrow="Assemble final assets →"
              onClick={() => handleTool("kit")}
            />
          </div>
        </section>

        {isReadinessDiagnosticEnabled() ? (
          <section className="card pad reveal in delay-4">
            <div className="rd-section-k">Conversational diagnosis</div>
            <div className="rd-section-t">Talk through where you actually stand.</div>
            <DiagnosticAnchor />
          </section>
        ) : null}
      </div>
    </div>
  );
}

function OverviewViewLegacy({ open, active, readinessPct }: OverviewViewProps) {
  const ref = useAnimatedBars(active);
  return (
    <div className={`view${active ? " active" : ""}`} id="rd-overview" ref={ref}>
      <section className="rd-hero reveal in">
        <div className="rd-hero-grid">
          <div>
            <div className="eyebrow">Overview · Start here</div>
            <h3>
              You are <i>close</i> to interviewable — but your proof is stronger than
              your packaging.
            </h3>
            <p>
              Job readiness does not mean a dashboard of tools. It means a clear
              diagnosis, a focused next action, and a believable path from today to
              an actual offer.
            </p>
            <div className="rd-hero-actions">
              <button
                type="button"
                className="btn primary"
                onClick={() => open("resume")}
              >
                Build resume from proof
              </button>
              <button
                type="button"
                className="btn secondary"
                onClick={() => open("jd")}
              >
                Match me to a real JD
              </button>
            </div>
          </div>
          <div className="score-card">
            <div className="ring">
              <strong>
                <span className="count">{readinessPct}</span>%
              </strong>
            </div>
            <div className="lbl">Python Developer readiness</div>
            <div className="tl">Promising, not yet polished.</div>
            <div
              style={{
                marginTop: 10,
                display: "flex",
                gap: 8,
                alignItems: "center",
                flexWrap: "wrap",
              }}
            >
              <span className="delta-pill">▲ +8 this week</span>
              <svg width="90" height="28" viewBox="0 0 90 28" aria-hidden="true">
                <polyline
                  points="2,22 14,20 26,18 38,15 50,14 62,11 74,8 88,6"
                  fill="none"
                  stroke="#beddc8"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
                <circle cx="88" cy="6" r="3" fill="#beddc8" />
              </svg>
            </div>
            <div className="cp">
              Each completed lesson, capstone revision, and review response lifts
              this score. Last 4 weeks: 44 → 51 → 58 → 62.
            </div>
          </div>
        </div>
      </section>

      <div className="rd-stack">
        <div className="rd-2col">
          <section className="card pad reveal in delay-1">
            <div className="rd-section-k">Top 3 next actions</div>
            <div className="rd-section-t">Do these before anything else.</div>
            <div className="rd-section-c">
              A job-readiness screen should lead with action, not six equally
              weighted tools. This page reduces ambiguity and helps you act with
              confidence.
            </div>
            <div className="rd-actions">
              <ActionRow
                num="1"
                title="Turn your capstone into 3 recruiter-readable bullets"
                copy="Your work is stronger than your current positioning. Package what you built, the APIs you touched, and the errors you handled into resume language."
                ctaLabel="Open Resume Lab"
                onClick={() => open("resume")}
              />
              <ActionRow
                num="2"
                title="Compare yourself against a real Python Developer JD"
                copy="Replace vague anxiety with a role-specific gap plan that connects directly back to lessons, exercises, and interview practice."
                ctaLabel="Open JD Match"
                onClick={() => open("jd")}
              />
              <ActionRow
                num="3"
                title="Practice one live mock answer using your own project"
                copy="Static question banks are not enough. Rehearsal with proof-based storytelling is what creates real readiness."
                ctaLabel="Open Coach"
                onClick={() => open("interview")}
              />
            </div>
          </section>

          <section className="card pad reveal in delay-2">
            <div className="rd-section-k">Readiness breakdown</div>
            <div className="rd-section-t">Make the score explain itself.</div>
            <div className="rd-section-c">
              One number motivates. A breakdown makes it actionable and trustworthy.
            </div>
            <div className="rd-metrics">
              <MetricRow
                label="Core skill readiness"
                sub="Your lessons and exercises suggest solid fundamentals for junior Python roles."
                value={74}
              />
              <MetricRow
                label="Proof and portfolio"
                sub="You have meaningful work, but it is not yet organized as shareable proof."
                value={58}
                tone="warn"
              />
              <MetricRow
                label="Interview performance"
                sub="You likely know more than you can currently explain under pressure."
                value={46}
                tone="low"
              />
              <MetricRow
                label="Role targeting"
                sub="You need a tighter match between your current proof and the jobs you apply to."
                value={61}
                tone="warn"
              />
            </div>
          </section>
        </div>

        <section className="card pad reveal in delay-3">
          <div className="rd-section-k">Recommended sequence</div>
          <div className="rd-section-t">One clear path, not a wall of options.</div>
          <div className="rd-section-c">
            Package proof → test against a real job → rehearse your story → export
            an application kit. Each step hands off cleanly to the next.
          </div>
          <div className="rd-tools">
            <ToolCard
              k="Step 1"
              t="Resume Lab"
              s="Build a resume from capstone work, review scores, and the strongest signals already earned inside the platform."
              arrow="Open focused workspace →"
              onClick={() => open("resume")}
            />
            <ToolCard
              k="Step 2"
              t="JD Match"
              s="Paste a real job description and convert the fit analysis into a gap plan tied back to platform learning."
              arrow="Compare to a real role →"
              onClick={() => open("jd")}
            />
            <ToolCard
              k="Step 3"
              t="Interview Coach"
              s="Rehearse answers using your own proof instead of memorizing generic talking points."
              arrow="Practice with live prompts →"
              onClick={() => open("interview")}
            />
            <ToolCard
              k="Step 4"
              t="Application Kit"
              s="Leave with a ready set of assets: resume, project proof, pitch lines, and tailored role language."
              arrow="Assemble final assets →"
              onClick={() => open("kit")}
            />
          </div>
          <div className="rd-note">
            <b>Design principle</b>
            <span>
              On entry, show only diagnosis, next actions, and one recommended
              path. Deeper tools open inside focused internal pages so the student
              never feels surrounded by too many choices at once.
            </span>
          </div>
        </section>
      </div>
    </div>
  );
}

interface ActionRowProps {
  num: string;
  title: string;
  copy: string;
  ctaLabel: string;
  onClick: () => void;
}

function ActionRow({ num, title, copy, ctaLabel, onClick }: ActionRowProps) {
  return (
    <div className="rd-action">
      <div className="rd-action-no">{num}</div>
      <div>
        <b>{title}</b>
        <span>{copy}</span>
      </div>
      <button type="button" className="rd-action-cta" onClick={onClick}>
        {ctaLabel}
      </button>
    </div>
  );
}

interface MetricRowProps {
  label: string;
  sub: string;
  value: number;
  tone?: "warn" | "low";
}

function MetricRow({ label, sub, value, tone }: MetricRowProps) {
  const fillCls = `rd-bar-fill${tone ? ` ${tone}` : ""}`;
  const initial: CSSProperties = { width: "0%" };
  return (
    <div className="rd-metric">
      <div>
        <b>{label}</b>
        <div className="sub">{sub}</div>
      </div>
      <strong>{value}%</strong>
      <div className="rd-bar">
        <div className={fillCls} data-width={String(value)} style={initial} />
      </div>
    </div>
  );
}

interface ToolCardProps {
  k: string;
  t: string;
  s: string;
  arrow: string;
  onClick: () => void;
}

function ToolCard({ k, t, s, arrow, onClick }: ToolCardProps) {
  return (
    <button type="button" className="rd-tool" onClick={onClick}>
      <div className="k">{k}</div>
      <div className="t">{t}</div>
      <div className="s">{s}</div>
      <div className="arrow">{arrow}</div>
    </button>
  );
}

type ResumeTab = "evidence" | "bullets" | "tailoring" | "export";

const RESUME_TABS: ReadonlyArray<{ id: ResumeTab; label: string }> = [
  { id: "evidence", label: "Evidence" },
  { id: "bullets", label: "Bullets" },
  { id: "tailoring", label: "Role tailoring" },
  { id: "export", label: "Export" },
];

function capstoneEvidenceTone(score: number | null): "good" | "warn" | "low" {
  if (score === null) return "low";
  if (score >= 70) return "good";
  return "warn";
}

function capstoneEvidenceBadge(score: number | null): string {
  if (score === null) return "Building";
  if (score >= 70) return "Strong";
  return "Improve";
}

function ResumeView({ open, active }: ViewProps) {
  const user = useAuthStore((s) => s.user);
  const { data: resume, isLoading: resumeLoading } = useMyResume();
  const { data: proof } = useReadinessProof();
  const regenerate = useRegenerateResume();
  const recordEvent = useRecordWorkspaceEvent();
  const [tailorOpen, setTailorOpen] = useState(false);
  const [tab, setTab] = useState<ResumeTab>("evidence");

  const displayName = user?.full_name ?? "";

  const handleTab = useCallback(
    (next: ResumeTab) => {
      setTab(next);
      recordEvent("resume", "subnav_clicked", { tab: next });
    },
    [recordEvent],
  );

  const handleRegenerate = useCallback(() => {
    regenerate.mutate(true, {
      onSuccess: () => v8Toast("Resume regenerated from latest proof."),
      onError: () => v8Toast("Could not regenerate. Try again in a moment."),
    });
  }, [regenerate]);

  const handleGoToKit = useCallback(() => {
    recordEvent("resume", "cta_clicked", { cta: "go_to_kit" });
    open("kit");
  }, [open, recordEvent]);

  const handleOpenTailor = useCallback(() => {
    setTailorOpen(true);
    recordEvent("resume", "cta_clicked", { cta: "open_tailor" });
  }, [recordEvent]);

  return (
    <div className={`view${active ? " active" : ""}`} id="rd-resume">
      <section className="card pad reveal in">
        <div className="rd-split">
          <div>
            <div className="rd-section-k">Resume Lab</div>
            <div className="rd-section-t">
              Build my resume from <i>proof</i>, not from guesswork.
            </div>
            <div className="rd-section-c">
              A resume builder is helpful only if it translates actual work into
              believable recruiter language. This page converts lessons,
              capstones, review comments, and demonstrated skills into a resume
              that sounds earned.
            </div>
            <div className="rd-subnav">
              {RESUME_TABS.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  className={`rd-subtab${tab === t.id ? " on" : ""}`}
                  onClick={() => handleTab(t.id)}
                >
                  {t.label}
                </button>
              ))}
            </div>
          </div>
          <TailoredResumeQuotaChip enabled={active} />
        </div>

        {tab === "evidence" ? (
          <ResumeEvidenceTab proof={proof} />
        ) : null}
        {tab === "bullets" ? (
          <ResumeBulletsTab
            resume={resume}
            isLoading={resumeLoading}
            onRegenerate={handleRegenerate}
            isRegenerating={regenerate.isPending}
            displayName={displayName}
          />
        ) : null}
        {tab === "tailoring" ? (
          <ResumeTailoringTab
            active={active}
            onGenerate={handleOpenTailor}
          />
        ) : null}
        {tab === "export" ? (
          <ResumeExportTab onGoToKit={handleGoToKit} />
        ) : null}

        <div className="rd-footer">
          <button
            type="button"
            className="btn primary"
            onClick={() => open("jd")}
          >
            Use this against a real JD
          </button>
          <button
            type="button"
            className="btn ghost"
            onClick={handleOpenTailor}
          >
            Generate tailored version
          </button>
        </div>
      </section>
      <IntakeModal open={tailorOpen} onClose={() => setTailorOpen(false)} />
    </div>
  );
}

function ResumeEvidenceTab({ proof }: { proof: ProofResponse | undefined }) {
  if (!proof) {
    return (
      <div className="resume-preview" data-testid="resume-evidence-skeleton">
        <div className="rd-skel rd-skel-line" style={{ width: "60%", height: 14, marginTop: 8 }} />
        <div className="rd-skel rd-skel-line" style={{ width: "80%", height: 14, marginTop: 8 }} />
        <div className="rd-skel rd-skel-line" style={{ width: "70%", height: 14, marginTop: 8 }} />
      </div>
    );
  }
  const capstones: ProofCapstoneArtifact[] = proof.capstone_artifacts ?? [];
  const aiReviews = proof.ai_reviews;
  const lastReviewScore =
    aiReviews?.last_three?.[0]?.score ?? null;
  const autopsyCount = proof.autopsies?.length ?? 0;
  const lastAutopsyScore = proof.autopsies?.[0]?.overall_score ?? null;
  const peerReceived = proof.peer_reviews?.count_received ?? 0;
  return (
    <div className="resume-preview">
      <div className="resume-block">
        <h6>Evidence currently powering this draft</h6>
        <div className="rd-list">
          {capstones.length === 0 ? (
            <EvidenceRow
              title="Capstones"
              copy="No capstones shipped yet — start one in Studio to seed real proof."
              badge="Building"
              tone="low"
            />
          ) : (
            capstones.map((c) => (
              <EvidenceRow
                key={c.exercise_id}
                title={c.title}
                copy={`${c.draft_count} draft${c.draft_count === 1 ? "" : "s"}${
                  c.last_score !== null ? ` · score ${c.last_score}/100` : ""
                }`}
                badge={capstoneEvidenceBadge(c.last_score)}
                tone={capstoneEvidenceTone(c.last_score)}
              />
            ))
          )}
          <EvidenceRow
            title="AI reviews"
            copy={
              aiReviews && aiReviews.count > 0
                ? `${aiReviews.count} review${aiReviews.count === 1 ? "" : "s"}${
                    lastReviewScore !== null
                      ? ` · last score ${lastReviewScore}/100`
                      : ""
                  }`
                : "No AI reviews yet — submit a draft to get one."
            }
            badge={
              aiReviews && aiReviews.count > 0
                ? lastReviewScore !== null && lastReviewScore >= 70
                  ? "Strong"
                  : "Improve"
                : "Building"
            }
            tone={
              aiReviews && aiReviews.count > 0
                ? lastReviewScore !== null && lastReviewScore >= 70
                  ? "good"
                  : "warn"
                : "low"
            }
          />
          <EvidenceRow
            title="Autopsies"
            copy={
              autopsyCount > 0
                ? `${autopsyCount} autopsy${autopsyCount === 1 ? "" : "s"}${
                    lastAutopsyScore !== null
                      ? ` · last overall ${lastAutopsyScore}/100`
                      : ""
                  }`
                : "Run a portfolio autopsy to surface gaps in your shipped work."
            }
            badge={
              autopsyCount > 0
                ? lastAutopsyScore !== null && lastAutopsyScore < 60
                  ? "Improve"
                  : "Strong"
                : "Building"
            }
            tone={
              autopsyCount > 0
                ? lastAutopsyScore !== null && lastAutopsyScore < 60
                  ? "warn"
                  : "good"
                : "low"
            }
          />
          <EvidenceRow
            title="Peer reviews"
            copy={
              peerReceived > 0
                ? `${peerReceived} peer review${peerReceived === 1 ? "" : "s"} received`
                : "No peer reviews yet — share work with the cohort."
            }
            badge={peerReceived > 0 ? "Strong" : "Building"}
            tone={peerReceived > 0 ? "good" : "low"}
          />
        </div>
      </div>
    </div>
  );
}

interface ResumeBulletsTabProps {
  resume: ReturnType<typeof useMyResume>["data"];
  isLoading: boolean;
  onRegenerate: () => void;
  isRegenerating: boolean;
  displayName: string;
}

function ResumeBulletsTab({
  resume,
  isLoading,
  onRegenerate,
  isRegenerating,
  displayName,
}: ResumeBulletsTabProps) {
  if (isLoading && !resume) {
    return (
      <div className="resume-preview" data-testid="resume-bullets-skeleton">
        <div className="rd-skel rd-skel-line" style={{ width: "70%", height: 16, marginTop: 8 }} />
        <div className="rd-skel rd-skel-line" style={{ width: "90%", height: 14, marginTop: 8 }} />
        <div className="rd-skel rd-skel-line" style={{ width: "85%", height: 14, marginTop: 8 }} />
      </div>
    );
  }
  const bullets = resume?.bullets ?? [];
  const summary = resume?.summary ?? "";
  return (
    <div className="resume-preview">
      <div className="resume-head">
        <div>
          <div className="resume-name">{displayName}</div>
          {summary ? <div className="resume-meta">{summary}</div> : null}
        </div>
        <span className="rd-badge good">Built from proof</span>
      </div>
      <div className="resume-block">
        <h6>Bullets</h6>
        {bullets.length === 0 ? (
          <div className="rd-section-c">
            No bullets yet — regenerate from your latest proof to draft them.
          </div>
        ) : (
          <div data-testid="resume-bullets-list">
            {bullets.map((b, i) => (
              <div key={i} className="resume-bullet">
                {b.text}
              </div>
            ))}
          </div>
        )}
        <div className="rd-footer" style={{ marginTop: 12 }}>
          <button
            type="button"
            className="btn primary"
            onClick={onRegenerate}
            disabled={isRegenerating}
          >
            {isRegenerating ? "Regenerating…" : "Regenerate from latest proof"}
          </button>
        </div>
      </div>
    </div>
  );
}

interface ResumeTailoringTabProps {
  active: boolean;
  onGenerate: () => void;
}

function ResumeTailoringTab({ active, onGenerate }: ResumeTailoringTabProps) {
  return (
    <div className="resume-preview">
      <div className="resume-block">
        <h6>Role-tailored versions</h6>
        <div className="rd-section-c">
          Generate a version of your resume shaped to a specific job description.
          Each tailored variant runs against your real proof, not a rewrite of
          generic copy.
        </div>
        <div className="rd-dual" style={{ marginTop: 12 }}>
          <TailoredResumeQuotaChip enabled={active} />
          <div className="rd-panel">
            <div className="t">Generate a tailored version</div>
            <div className="c">
              Paste a JD in the next step. We&apos;ll draft a focused variant
              you can review and download.
            </div>
            <div style={{ marginTop: 10 }}>
              <button
                type="button"
                className="btn primary"
                onClick={onGenerate}
              >
                Generate tailored version
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function ResumeExportTab({ onGoToKit }: { onGoToKit: () => void }) {
  return (
    <div className="resume-preview">
      <div className="resume-block">
        <h6>Export</h6>
        <div className="rd-section-c">
          PDF export of the master resume happens through the Application Kit
          — the same flow that bundles your tailored resume, JD analysis, mock
          report, and autopsy into one downloadable kit.
        </div>
        <div className="rd-footer" style={{ marginTop: 12 }}>
          <button type="button" className="btn primary" onClick={onGoToKit}>
            Build my application kit
          </button>
        </div>
      </div>
    </div>
  );
}

interface EvidenceRowProps {
  title: string;
  copy: string;
  badge: string;
  tone: "good" | "warn" | "low";
}

function EvidenceRow({ title, copy, badge, tone }: EvidenceRowProps) {
  return (
    <div className="rd-li">
      <div>
        <b>{title}</b>
        <span>{copy}</span>
      </div>
      <span className={`rd-badge ${tone}`}>{badge}</span>
    </div>
  );
}

function JdMatchView(props: ViewProps) {
  // Feature-flagged swap. The legacy fallback now collapses to a single
  // disabled placeholder (the old computeFit + EvidenceRow demo block was
  // dropped on rewire) so environments without the decoder flag still
  // render an honest "off" state instead of misleading hard-coded numbers.
  if (isJdDecoderEnabled()) {
    return <JdMatchViewLive {...props} />;
  }
  return <JdMatchViewLegacy {...props} />;
}

function JdMatchViewLive({ open, active }: ViewProps) {
  const [jdText, setJdText] = useState<string>("");
  const [decoderKey, setDecoderKey] = useState(0);
  const recordEvent = useRecordWorkspaceEvent();
  const saveJd = useSaveJd();
  const { data: jdLibrary } = useJdLibrary();

  const presetText = useCallback(
    (key: keyof typeof JD_PRESETS) => {
      const preset = JD_PRESETS[key];
      setJdText(preset.text);
      setDecoderKey((k) => k + 1);
      recordEvent("jd", "jd_preset_selected", { preset: key });
    },
    [recordEvent],
  );

  const loadFromLibrary = useCallback(
    (item: JdLibraryItem) => {
      // The library list endpoint returns metadata only; we don't have the JD
      // text here. Persist title + use it as the textarea seed so the user can
      // re-paste / re-decode without losing the JD they saved earlier.
      setJdText(`# ${item.title}${item.company ? ` — ${item.company}` : ""}\n\n`);
      setDecoderKey((k) => k + 1);
      recordEvent("jd", "jd_library_selected", { jd_id: item.id });
    },
    [recordEvent],
  );

  const handleSave = useCallback(() => {
    const text = jdText.trim();
    if (text.length < 40) return;
    const firstLine = text.split("\n", 1)[0]?.slice(0, 80) ?? "Saved JD";
    const title = firstLine.replace(/^#\s*/, "") || "Saved JD";
    saveJd.mutate(
      { title, jd_text: text },
      {
        onSuccess: () => {
          v8Toast("JD saved to your library.");
          recordEvent("jd", "jd_saved");
        },
        onError: () => v8Toast("Could not save JD. Try again."),
      },
    );
  }, [jdText, saveJd, recordEvent]);

  return (
    <div className={`view${active ? " active" : ""}`} id="rd-jd">
      <section className="card pad reveal in">
        <div className="rd-section-k">JD Match</div>
        <div className="rd-section-t">
          Match me to a real role — then map gaps back to learning.
        </div>

        <div className="jd-paste-row" style={{ gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
          <div className="jd-sample-chips">
            <button
              type="button"
              className="jd-sample-chip"
              onClick={() => presetText("python")}
            >
              Python Developer
            </button>
            <button
              type="button"
              className="jd-sample-chip"
              onClick={() => presetText("data")}
            >
              Data Analyst
            </button>
            <button
              type="button"
              className="jd-sample-chip"
              onClick={() => presetText("genai")}
            >
              GenAI Engineer
            </button>
          </div>
          <button
            type="button"
            className="btn ghost"
            onClick={handleSave}
            disabled={jdText.trim().length < 40 || saveJd.isPending}
          >
            {saveJd.isPending ? "Saving…" : "Save this JD"}
          </button>
        </div>

        <JdDecoderCard key={decoderKey} initialJdText={jdText} />

        {jdLibrary && jdLibrary.length > 0 ? (
          <div className="rd-list" style={{ marginTop: 16 }}>
            <div className="rd-section-k">Saved JDs</div>
            <div className="jd-sample-chips" style={{ flexWrap: "wrap" }}>
              {jdLibrary.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className="jd-sample-chip"
                  onClick={() => loadFromLibrary(item)}
                >
                  {item.title}
                  {item.last_fit_score !== null
                    ? ` · fit:${Math.round(item.last_fit_score)}`
                    : ""}
                </button>
              ))}
            </div>
          </div>
        ) : null}

        <div
          className="rd-actions"
          style={{ marginTop: 24, display: "flex", gap: 8 }}
        >
          <button
            type="button"
            className="btn ghost"
            onClick={() => open("overview")}
          >
            Back to overview
          </button>
        </div>
      </section>
    </div>
  );
}

function JdMatchViewLegacy({ open, active }: ViewProps) {
  const [jdText, setJdText] = useState<string>("");
  const fitScoreMutation = useFitScore();

  const onScore = useCallback(() => {
    const text = jdText.trim();
    if (text.length < 40) {
      v8Toast("Paste a longer JD to score it.");
      return;
    }
    fitScoreMutation.mutate({ jd_text: text, jd_title: "Target role" });
  }, [jdText, fitScoreMutation]);

  const data = fitScoreMutation.data;
  const buckets = data?.verdict?.buckets;

  return (
    <div className={`view${active ? " active" : ""}`} id="rd-jd">
      <section className="card pad reveal in">
        <div className="rd-section-k">JD Match (kill-switch)</div>
        <div className="rd-section-t">
          The decoder is disabled in this environment.
        </div>
        <div className="rd-section-c">
          Falling back to the basic fit-score endpoint. Paste a JD and we&apos;ll
          score it against your current proof.
        </div>
        <textarea
          className="jd-paste"
          placeholder="Paste a JD…"
          value={jdText}
          onChange={(e) => setJdText(e.target.value)}
        />
        <div className="jd-paste-row" style={{ marginTop: 8 }}>
          <button
            type="button"
            className="btn primary"
            onClick={onScore}
            disabled={fitScoreMutation.isPending}
          >
            {fitScoreMutation.isPending ? "Scoring…" : "Score fit"}
          </button>
        </div>
        {data ? (
          <div className="rd-list" style={{ marginTop: 16 }}>
            <div className="rd-section-k">
              Fit: {Math.round(data.fit_score)} / 100
            </div>
            {buckets ? (
              <>
                <EvidenceRow
                  title="Match"
                  copy={
                    buckets.proven.length > 0
                      ? buckets.proven.join(", ")
                      : "No proven skill matches yet."
                  }
                  badge="Match"
                  tone="good"
                />
                <EvidenceRow
                  title="Near match"
                  copy={
                    buckets.unproven.length > 0
                      ? buckets.unproven.join(", ")
                      : "No partial-match skills."
                  }
                  badge="Near match"
                  tone="warn"
                />
                <EvidenceRow
                  title="Gap"
                  copy={
                    buckets.missing.length > 0
                      ? buckets.missing.join(", ")
                      : "No critical gaps detected."
                  }
                  badge="Gap"
                  tone="low"
                />
              </>
            ) : null}
          </div>
        ) : null}

        <div className="rd-footer">
          <button
            type="button"
            className="btn ghost"
            onClick={() => open("overview")}
          >
            Back to overview
          </button>
        </div>
      </section>
    </div>
  );
}

function InterviewCoachView({ active }: ViewProps) {
  const enabled = isMockInterviewEnabled();
  const defaultRole = "Junior Python Developer";

  return (
    <div className={`view${active ? " active" : ""}`} id="rd-interview">
      <section className="card pad reveal in">
        <div className="rd-section-k">Interview Coach</div>
        <div className="rd-section-t">
          Replace the static question bank with <i>live practice</i>.
        </div>
        <div className="rd-section-c">
          A plain interview bank is not enough for true job readiness. This
          coach asks adaptive questions, scores honestly (with confidence —
          not bluffing), and remembers what tripped you up last time so the
          next session is sharper.
        </div>

        <div style={{ marginTop: 18 }}>
          {enabled ? (
            <MockInterviewWorkspace defaultTargetRole={defaultRole} />
          ) : (
            <div className="match-card" style={{ padding: 22 }}>
              <div className="k">Temporarily off</div>
              <div className="big">
                The mock interview coach is disabled in this environment.
              </div>
              <div className="body">
                Re-enable it by removing
                {" "}<code>NEXT_PUBLIC_MOCK_INTERVIEW_DISABLED</code>.
              </div>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const diffMs = Date.now() - then;
  const mins = Math.round(diffMs / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.round(days / 30);
  return `${months}mo ago`;
}

function autopsyTone(score: number): "good" | "warn" | "low" {
  if (score >= 70) return "good";
  if (score >= 50) return "warn";
  return "low";
}

function ProofView({ open, active }: ViewProps) {
  const { data: proof, isLoading } = useReadinessProof();
  const recordEvent = useRecordWorkspaceEvent();
  const [autopsyOpen, setAutopsyOpen] = useState(false);

  const handleUseInKit = useCallback(() => {
    recordEvent("proof", "cta_clicked", { cta: "use_in_kit" });
    open("kit");
  }, [open, recordEvent]);

  const handleTurnIntoBullets = useCallback(() => {
    recordEvent("proof", "cta_clicked", { cta: "turn_into_bullets" });
    open("resume");
  }, [open, recordEvent]);

  const primary = proof?.last_capstone_summary;
  const autopsies: ProofAutopsy[] = (proof?.autopsies ?? []).slice(0, 5);
  const mocks: ProofMockReport[] = (proof?.mock_reports ?? []).slice(0, 3);
  const aiReviewCount = proof?.ai_reviews?.count ?? 0;
  const peerCount = proof?.peer_reviews?.count_received ?? 0;

  return (
    <div className={`view${active ? " active" : ""}`} id="rd-proof">
      <section className="card pad reveal in">
        <div className="rd-section-k">Proof Portfolio</div>
        <div className="rd-section-t">
          Show the work that makes your next role believable.
        </div>
        <div className="rd-section-c">
          The platform already believes in proof — capstones, reviews, promotion
          gates. Job readiness exposes that proof clearly so you can use it in
          resumes, interviews, and applications.
        </div>

        <div className="proof-grid-3">
          <div className="pf proof-linked">
            <div className="k">Primary artifact</div>
            {isLoading && !proof ? (
              <>
                <div className="rd-skel rd-skel-line" style={{ width: "60%", height: 18, marginTop: 6 }} />
                <div className="rd-skel rd-skel-line" style={{ width: "90%", height: 14, marginTop: 8 }} />
                <div className="rd-skel rd-skel-line" style={{ width: "85%", height: 14, marginTop: 8 }} />
              </>
            ) : primary && primary.title ? (
              <>
                <div className="t">{primary.title}</div>
                {primary.snippet ? (
                  <div className="meta" style={{ marginTop: 14 }}>
                    {primary.snippet}
                  </div>
                ) : null}
              </>
            ) : (
              <>
                <div className="t">No primary artifact yet</div>
                <div className="meta" style={{ marginTop: 14 }}>
                  Ship your first capstone to seed your proof.
                </div>
              </>
            )}
          </div>
          <div className="pf">
            <div className="k">Recent autopsies</div>
            {autopsies.length === 0 ? (
              <div className="meta" style={{ marginTop: 14 }}>
                No autopsies yet. Run one to surface what your shipped work is
                missing.
              </div>
            ) : (
              <div className="rd-list" data-testid="proof-autopsy-list">
                {autopsies.map((a) => (
                  <EvidenceRow
                    key={a.id}
                    title={a.project_title}
                    copy={a.headline}
                    badge={`${a.overall_score}/100`}
                    tone={autopsyTone(a.overall_score)}
                  />
                ))}
              </div>
            )}
            <div className="rd-footer" style={{ marginTop: 12 }}>
              <button
                type="button"
                className="btn ghost"
                onClick={() => setAutopsyOpen(true)}
              >
                Run a new autopsy
              </button>
            </div>
          </div>
          <div className="pf">
            <div className="k">Mock interview reports</div>
            {mocks.length === 0 ? (
              <div className="meta" style={{ marginTop: 14 }}>
                No mock interviews yet. Run one in the Interview Coach.
              </div>
            ) : (
              <div className="rd-list">
                {mocks.map((m) => (
                  <EvidenceRow
                    key={m.session_id}
                    title={m.headline ?? "Mock interview"}
                    copy={`${m.verdict ?? "pending"} · ${relativeTime(m.created_at)}`}
                    badge={m.verdict ?? "—"}
                    tone="good"
                  />
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="rd-list" style={{ marginTop: 16, display: "flex", gap: 8 }}>
          <span className="rd-badge good">AI reviews · {aiReviewCount}</span>
          <span className="rd-badge good">Peer reviews · {peerCount}</span>
        </div>

        <div className="rd-footer">
          <button
            type="button"
            className="btn primary"
            onClick={handleUseInKit}
          >
            Use this in application kit
          </button>
          <button
            type="button"
            className="btn ghost"
            onClick={handleTurnIntoBullets}
          >
            Turn proof into bullets
          </button>
        </div>
      </section>
      <AutopsyComposerModal
        open={autopsyOpen}
        onClose={() => setAutopsyOpen(false)}
      />
    </div>
  );
}

interface AutopsyComposerModalProps {
  open: boolean;
  onClose: () => void;
}

function AutopsyComposerModal(props: AutopsyComposerModalProps) {
  // The modal is fully unmounted while closed, so internal state always
  // starts fresh on each open — no reset effect needed (and no cascading
  // re-renders flagged by react-hooks/set-state-in-effect).
  if (!props.open) return null;
  return <AutopsyComposerModalBody onClose={props.onClose} />;
}

function AutopsyComposerModalBody({ onClose }: { onClose: () => void }) {
  const create = useCreateAutopsy();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [whatWentWell, setWhatWentWell] = useState("");
  const [whatWasHard, setWhatWasHard] = useState("");
  const [error, setError] = useState<string | null>(null);

  const onSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      const trimmedTitle = title.trim();
      const trimmedDescription = description.trim();
      if (trimmedTitle.length < 1) {
        setError("Project title is required.");
        return;
      }
      if (trimmedDescription.length < 20) {
        setError("Add at least 20 characters of description.");
        return;
      }
      setError(null);
      create.mutate(
        {
          project_title: trimmedTitle,
          project_description: trimmedDescription,
          what_went_well_self: whatWentWell.trim() || undefined,
          what_was_hard_self: whatWasHard.trim() || undefined,
        },
        {
          onSuccess: (data) => {
            v8Toast(data.headline ?? "Autopsy created.");
            onClose();
          },
          onError: () => {
            setError("Could not create autopsy. Try again.");
          },
        },
      );
    },
    [title, description, whatWentWell, whatWasHard, create, onClose],
  );

  return (
    <div
      className="export-overlay show"
      role="dialog"
      aria-modal="true"
      aria-label="Create portfolio autopsy"
    >
      <div className="export-card">
        <b>Run a new autopsy</b>
        <form
          onSubmit={onSubmit}
          style={{ display: "grid", gap: 10, marginTop: 12 }}
        >
          <label className="rd-section-k" htmlFor="autopsy-title">
            Project title
          </label>
          <input
            id="autopsy-title"
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
            style={{ padding: "8px 10px", borderRadius: 6 }}
          />
          <label className="rd-section-k" htmlFor="autopsy-description">
            What did you build?
          </label>
          <textarea
            id="autopsy-description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={4}
            required
            minLength={20}
            style={{ padding: "8px 10px", borderRadius: 6 }}
          />
          <label className="rd-section-k" htmlFor="autopsy-well">
            What went well? (optional)
          </label>
          <textarea
            id="autopsy-well"
            value={whatWentWell}
            onChange={(e) => setWhatWentWell(e.target.value)}
            rows={2}
            style={{ padding: "8px 10px", borderRadius: 6 }}
          />
          <label className="rd-section-k" htmlFor="autopsy-hard">
            What was hard? (optional)
          </label>
          <textarea
            id="autopsy-hard"
            value={whatWasHard}
            onChange={(e) => setWhatWasHard(e.target.value)}
            rows={2}
            style={{ padding: "8px 10px", borderRadius: 6 }}
          />
          {error ? (
            <div role="alert" style={{ color: "#c14a3f", fontSize: 13 }}>
              {error}
            </div>
          ) : null}
          <div className="rd-footer" style={{ marginTop: 8 }}>
            <button
              type="submit"
              className="btn primary"
              disabled={create.isPending}
            >
              {create.isPending ? "Creating…" : "Create autopsy"}
            </button>
            <button type="button" className="btn ghost" onClick={onClose}>
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function todayISO(): string {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function kitStatusBadge(status: string): "good" | "warn" | "low" {
  if (status === "ready") return "good";
  if (status === "failed") return "low";
  return "warn";
}

function KitView({ open, active }: ViewProps) {
  const overview = useReadinessOverview();
  const { data: kits, refetch: refetchKits } = useApplicationKits();
  const buildKit = useBuildApplicationKit();
  const deleteKit = useDeleteApplicationKit();
  const recordEvent = useRecordWorkspaceEvent();
  const flush = useFlushWorkspaceEvents();
  const { data: jdLibrary } = useJdLibrary();
  const { data: mockSessions } = useMyMockSessions();
  const { data: autopsies } = useAutopsyList();

  const [label, setLabel] = useState<string>(`Kit · ${todayISO()}`);
  const [targetRole, setTargetRole] = useState<string>("");
  const [jdId, setJdId] = useState<string>("");
  const [mockId, setMockId] = useState<string>("");
  const [autopsyId, setAutopsyId] = useState<string>("");

  // Prefill the target role from the overview hook once it lands so the form
  // matches the role the readiness score is keyed on.
  useEffect(() => {
    const inferred = overview.data?.target_role?.trim() ?? "";
    if (inferred && !targetRole) {
      setTargetRole(inferred);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [overview.data?.target_role]);

  // Long-poll while any kit is still building. Three-second cadence — the
  // PDF render takes 5–15s today; tighter polling is wasted requests, looser
  // would feel sluggish. Only runs when this view is the active tab.
  const hasBuilding = (kits ?? []).some((k) => k.status === "building");
  useEffect(() => {
    if (!active || !hasBuilding) return;
    const id = window.setInterval(() => {
      void refetchKits();
    }, 3000);
    return () => window.clearInterval(id);
  }, [active, hasBuilding, refetchKits]);

  const handleBuild = useCallback(() => {
    const trimmedLabel = label.trim() || `Kit · ${todayISO()}`;
    const components: string[] = [];
    if (jdId) components.push("jd");
    if (mockId) components.push("mock");
    if (autopsyId) components.push("autopsy");
    recordEvent("kit", "kit_build_started", { components });
    void flush();
    buildKit.mutate(
      {
        label: trimmedLabel,
        target_role: targetRole.trim() || null,
        jd_library_id: jdId || null,
        mock_session_id: mockId || null,
        autopsy_id: autopsyId || null,
      },
      {
        onSuccess: () => v8Toast("Kit build started."),
        onError: () => v8Toast("Could not start kit build."),
      },
    );
  }, [
    label,
    targetRole,
    jdId,
    mockId,
    autopsyId,
    buildKit,
    recordEvent,
    flush,
  ]);

  const handleDownloadClick = useCallback(
    (id: string) => {
      recordEvent("kit", "kit_downloaded", { kit_id: id });
      void flush();
    },
    [recordEvent, flush],
  );

  const handleDelete = useCallback(
    (id: string) => {
      deleteKit.mutate(id, {
        onSuccess: () => v8Toast("Kit deleted."),
        onError: () => v8Toast("Could not delete kit."),
      });
    },
    [deleteKit],
  );

  const kitsList: ApplicationKitListItem[] = kits ?? [];

  return (
    <div className={`view${active ? " active" : ""}`} id="rd-kit">
      <section className="card pad reveal in">
        <div className="rd-section-k">Application Kit</div>
        <div className="rd-section-t">
          Leave this workspace with everything needed to apply.
        </div>
        <div className="rd-section-c">
          This is the conversion layer. Bundle your resume, JD analysis, mock
          interview report, and portfolio autopsy into one downloadable kit.
        </div>

        <div className="rd-section-k" style={{ marginTop: 16 }}>
          Recent kits
        </div>
        {kitsList.length === 0 ? (
          <div className="rd-section-c" data-testid="kit-empty">
            No kits yet — build your first one below.
          </div>
        ) : (
          <div className="rd-list" data-testid="kit-list">
            {kitsList.map((k) => (
              <div key={k.id} className="rd-li">
                <div>
                  <b>{k.label}</b>
                  <span>
                    {k.status === "building" ? "Building…" : k.status} ·{" "}
                    {k.generated_at
                      ? relativeTime(k.generated_at)
                      : relativeTime(k.created_at)}
                  </span>
                </div>
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  {k.status === "building" ? (
                    <span className="rd-badge warn">Building…</span>
                  ) : null}
                  <span className={`rd-badge ${kitStatusBadge(k.status)}`}>
                    {k.status}
                  </span>
                  {k.status === "ready" ? (
                    <a
                      className="btn primary"
                      href={applicationKitDownloadUrl(k.id)}
                      download={`kit-${k.label}.pdf`}
                      onClick={() => handleDownloadClick(k.id)}
                    >
                      Download
                    </a>
                  ) : null}
                  <button
                    type="button"
                    className="btn ghost"
                    onClick={() => handleDelete(k.id)}
                    disabled={deleteKit.isPending}
                  >
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}

        <div className="rd-section-k" style={{ marginTop: 24 }}>
          Build a new kit
        </div>
        <div className="rd-dual" style={{ marginTop: 8 }}>
          <div className="rd-panel">
            <div className="t">Kit details</div>
            <label className="rd-section-k" htmlFor="kit-label">
              Label
            </label>
            <input
              id="kit-label"
              type="text"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              required
              style={{ padding: "8px 10px", borderRadius: 6, width: "100%" }}
            />
            <label
              className="rd-section-k"
              htmlFor="kit-target"
              style={{ marginTop: 10, display: "block" }}
            >
              Target role (optional)
            </label>
            <input
              id="kit-target"
              type="text"
              value={targetRole}
              onChange={(e) => setTargetRole(e.target.value)}
              style={{ padding: "8px 10px", borderRadius: 6, width: "100%" }}
            />
          </div>
          <div className="rd-panel">
            <div className="t">Source rows (optional)</div>
            <label className="rd-section-k" htmlFor="kit-jd">
              JD from library
            </label>
            <select
              id="kit-jd"
              value={jdId}
              onChange={(e) => setJdId(e.target.value)}
              style={{ padding: "8px 10px", borderRadius: 6, width: "100%" }}
            >
              <option value="">— none —</option>
              {(jdLibrary ?? []).map((j) => (
                <option key={j.id} value={j.id}>
                  {j.title}
                </option>
              ))}
            </select>
            <label
              className="rd-section-k"
              htmlFor="kit-mock"
              style={{ marginTop: 10, display: "block" }}
            >
              Mock session
            </label>
            <select
              id="kit-mock"
              value={mockId}
              onChange={(e) => setMockId(e.target.value)}
              style={{ padding: "8px 10px", borderRadius: 6, width: "100%" }}
            >
              <option value="">— none —</option>
              {(mockSessions ?? []).map((m) => (
                <option key={m.id} value={m.id}>
                  {m.target_role ?? m.mode} · {relativeTime(m.created_at)}
                </option>
              ))}
            </select>
            <label
              className="rd-section-k"
              htmlFor="kit-autopsy"
              style={{ marginTop: 10, display: "block" }}
            >
              Portfolio autopsy
            </label>
            <select
              id="kit-autopsy"
              value={autopsyId}
              onChange={(e) => setAutopsyId(e.target.value)}
              style={{ padding: "8px 10px", borderRadius: 6, width: "100%" }}
            >
              <option value="">— none —</option>
              {(autopsies ?? []).map((a) => (
                <option key={a.id} value={a.id}>
                  {a.project_title}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="rd-footer">
          <button
            type="button"
            className="btn primary"
            onClick={handleBuild}
            disabled={buildKit.isPending || label.trim().length === 0}
          >
            {buildKit.isPending ? "Starting…" : "Build kit"}
          </button>
          <button
            type="button"
            className="btn ghost"
            onClick={() => open("overview")}
          >
            Return to overview
          </button>
        </div>
      </section>
    </div>
  );
}
