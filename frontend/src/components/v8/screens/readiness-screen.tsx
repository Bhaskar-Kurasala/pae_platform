"use client";

import {
  type CSSProperties,
  type ReactNode,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { useSetV8Topbar } from "@/components/v8/v8-topbar-context";
import { v8Toast } from "@/components/v8/v8-toast";
import { useMyResume, useFitScore } from "@/lib/hooks/use-career";
import { useStartSession, useSubmitAnswer } from "@/lib/hooks/use-interview";
import { useMyProgress } from "@/lib/hooks/use-progress";
import { useAuthStore } from "@/stores/auth-store";

type ReadinessView = "overview" | "resume" | "jd" | "interview" | "proof" | "kit";

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

const DEFAULT_JD_TEXT =
  "Junior Python Developer — Backend / Tooling. We need a developer comfortable with Python, async I/O, API integration, and writing small production-quality tools. Must know how to handle errors, rate limits, and environment-based configuration. Git collaboration, basic testing, and clear written communication required.";

function computeFit(text: string): number {
  const t = text.toLowerCase();
  const signals: Record<string, number> = {
    python: 15,
    async: 12,
    api: 12,
    retry: 8,
    error: 6,
    env: 5,
    git: 4,
    test: 5,
    pandas: -6,
    sql: -6,
    rag: -10,
    vector: -8,
    langchain: -6,
  };
  let base = 42;
  for (const [k, v] of Object.entries(signals)) {
    if (t.includes(k)) base += v;
  }
  return Math.max(20, Math.min(92, base));
}

function scoreInterviewAnswer(text: string): string[] {
  const txt = text.trim();
  const words = txt.split(/\s+/).filter(Boolean).length;
  const mentionsProject = /(capstone|cli|async|api|python|project)/i.test(txt);
  const mentionsOutcome = /(learned|shipped|proved|improved|reduced|faster|fixed)/i.test(
    txt,
  );
  const out: string[] = [];
  out.push(
    words < 60
      ? "Too short — aim for 80–140 words. Add context and one specific decision."
      : words > 220
        ? "A little long. Tighten to 140–180 words so it feels confident, not padded."
        : "Length is in the interview sweet spot (80–180 words).",
  );
  out.push(
    mentionsProject
      ? "Good: you anchored the answer in real project vocabulary."
      : "Missing specifics — name the project, tools, or one code decision.",
  );
  out.push(
    mentionsOutcome
      ? "Strong close: you mentioned a learning or outcome."
      : "End with what this proved, fixed, or taught — the answer trails off otherwise.",
  );
  return out;
}

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
  useSetV8Topbar({
    eyebrow: "Career · Job readiness workspace",
    titleHtml: "Turn learning into <i>interviewable proof</i>.",
    chips: [],
    progress: 82,
  });

  const [activeView, setActiveView] = useState<ReadinessView>("overview");
  const { data: progress } = useMyProgress();

  const readinessPct = useMemo(() => {
    if (!progress) return 62;
    return Math.max(0, Math.min(100, Math.round(progress.overall_progress)));
  }, [progress]);

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

function OverviewView({ open, active, readinessPct }: OverviewViewProps) {
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

function ResumeView({ open, active }: ViewProps) {
  const user = useAuthStore((s) => s.user);
  const { data: resume } = useMyResume();
  const displayName = user?.full_name ?? "Your Name";
  const summary =
    resume?.summary ??
    "Python Developer candidate · Async APIs · Error handling · CLI tooling";
  const bullets = resume?.bullets?.slice(0, 3).map((b) => b.text) ?? [
    "Built a CLI AI tool in Python using asynchronous API calls, structured prompting, and response handling inside a project-based learning environment.",
    "Implemented production-minded patterns including isolated API logic, retry planning, and environment-based configuration from senior review feedback.",
    "Demonstrated practical understanding of async / await workflows, modular code structure, and debugging-oriented iteration across guided capstone milestones.",
  ];

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
              believable recruiter language. This page converts lessons, capstones,
              review comments, and demonstrated skills into a resume that sounds
              earned.
            </div>
            <div className="rd-subnav">
              <button type="button" className="rd-subtab on">
                Evidence
              </button>
              <button type="button" className="rd-subtab">
                Bullets
              </button>
              <button type="button" className="rd-subtab">
                Role tailoring
              </button>
              <button type="button" className="rd-subtab">
                Export
              </button>
            </div>
          </div>
          <div className="rd-mini">
            <div className="k">Resume confidence</div>
            <div className="v">71%</div>
            <div className="s">
              Strong proof base, needs tighter wording for job-market readability.
            </div>
          </div>
        </div>

        <div className="rd-dual">
          <div className="rd-panel">
            <div className="t">What this section should do</div>
            <div className="c">
              Students should not start with a blank document. The system surfaces
              their best evidence, drafts strong bullets, shows what still feels
              thin, and helps create role-specific versions.
            </div>
          </div>
          <div className="rd-panel">
            <div className="t">Highest-value outputs</div>
            <div className="c">
              One polished master resume, one role-tailored version, three strong
              project bullets, and one concise profile summary that matches how
              recruiters scan.
            </div>
          </div>
        </div>

        <div className="resume-preview">
          <div className="resume-head">
            <div>
              <div className="resume-name">{displayName}</div>
              <div className="resume-meta">
                {summary}
                <br />
                Portfolio summary generated from capstone proof and platform
                performance.
              </div>
            </div>
            <span className="rd-badge good">Built from proof</span>
          </div>
          <div className="resume-block">
            <h6>Suggested profile</h6>
            {bullets.map((b, i) => (
              <div key={i} className="resume-bullet">
                {b}
              </div>
            ))}
          </div>
          <div className="resume-block">
            <h6>Evidence currently powering this draft</h6>
            <div className="rd-list">
              <EvidenceRow
                title="Capstone draft"
                copy="CLI AI tool with async request flow and review score of 84/100."
                badge="Strong"
                tone="good"
              />
              <EvidenceRow
                title="Lesson completion"
                copy="Python fundamentals, OOP, APIs and async progression visible in the path."
                badge="Solid"
                tone="good"
              />
              <EvidenceRow
                title="Proof depth"
                copy="Needs one clearer accomplishment story and one quantified outcome or scope line."
                badge="Improve"
                tone="warn"
              />
            </div>
          </div>
        </div>

        <div className="rd-footer">
          <button
            type="button"
            className="btn primary"
            onClick={() => open("jd")}
          >
            Use this against a real JD
          </button>
          <button type="button" className="btn ghost">
            Generate tailored version
          </button>
        </div>
      </section>
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

function JdMatchView({ open, active }: ViewProps) {
  const [jdText, setJdText] = useState<string>(DEFAULT_JD_TEXT);
  const [score, setScore] = useState<number>(68);
  const [recomputing, setRecomputing] = useState(false);
  const fitScoreMutation = useFitScore();

  const rescore = useCallback(
    (target?: number) => {
      const next = target ?? computeFit(jdText);
      setRecomputing(true);
      window.setTimeout(() => {
        setScore(next);
        setRecomputing(false);
        v8Toast(`Re-scored to ${next}%`);
      }, 500);
      // Fire real backend call non-blocking when JD has substance.
      if (jdText.trim().length > 40) {
        fitScoreMutation.mutate(
          { jd_text: jdText, jd_title: "Target role" },
          {
            onSuccess: (data) => {
              if (typeof data.fit_score === "number") {
                setScore(Math.round(data.fit_score));
              }
            },
          },
        );
      }
    },
    [jdText, fitScoreMutation],
  );

  const onChip = useCallback(
    (key: keyof typeof JD_PRESETS) => {
      const preset = JD_PRESETS[key];
      setJdText(preset.text);
      rescore(preset.score);
    },
    [rescore],
  );

  return (
    <div className={`view${active ? " active" : ""}`} id="rd-jd">
      <section className="card pad reveal in">
        <div className="rd-section-k">JD Match</div>
        <div className="rd-section-t">
          Match me to a real role — then map gaps back to learning.
        </div>
        <div className="rd-section-c">
          This turns abstract readiness into target-role readiness. Paste a real
          job description and get a truthful gap analysis connected directly to
          what you can do next in the platform.
        </div>

        <div className="jd-grid">
          <div className="match-card" style={{ gridColumn: "1 / -1" }}>
            <div className="k">Paste a job description</div>
            <div className="big">Live fit analysis</div>
            <div className="body">
              Drop any job description below. The fit score and gaps re-score in
              real time against your current proof.
            </div>
            <textarea
              className="jd-paste"
              placeholder="Paste the full JD here — requirements, responsibilities, tech stack, everything."
              value={jdText}
              onChange={(e) => setJdText(e.target.value)}
            />
            <div className="jd-paste-row">
              <button
                type="button"
                className="btn primary"
                onClick={() => rescore()}
              >
                Re-score fit
              </button>
              <div className="jd-sample-chips">
                <button
                  type="button"
                  className="jd-sample-chip"
                  onClick={() => onChip("python")}
                >
                  Python Developer
                </button>
                <button
                  type="button"
                  className="jd-sample-chip"
                  onClick={() => onChip("data")}
                >
                  Data Analyst
                </button>
                <button
                  type="button"
                  className="jd-sample-chip"
                  onClick={() => onChip("genai")}
                >
                  GenAI Engineer
                </button>
              </div>
            </div>
          </div>
          <div className={`match-card${recomputing ? " rd-recomputing" : ""}`}>
            <div className="k">Target role</div>
            <div className="big">Junior Python Developer · Backend / Tooling</div>
            <div className="body">
              Sample job requires Python fundamentals, API integration, async
              familiarity, debugging, Git collaboration, and ability to explain
              project work clearly.
            </div>
            <div className="rd-list">
              <EvidenceRow
                title="Python fundamentals"
                copy="Core readiness clearly supported by completed lessons and current capstone direction."
                badge="Match"
                tone="good"
              />
              <EvidenceRow
                title="APIs and async"
                copy="Good emerging fit — stronger if translated into clean resume bullets and a clearer project explanation."
                badge="Near match"
                tone="good"
              />
              <EvidenceRow
                title="Testing / debugging"
                copy="Needs stronger proof or at least a concise example of how you diagnosed and fixed an issue."
                badge="Gap"
                tone="warn"
              />
              <EvidenceRow
                title="Git / collaboration"
                copy="Weakly signaled today. Needs project narrative or future coursework surfaced in profile."
                badge="Gap"
                tone="low"
              />
            </div>
          </div>
          <div className={`match-card${recomputing ? " rd-recomputing" : ""}`}>
            <div className="k">Role fit</div>
            <div className="fit-score">
              <span className="count">{score}</span>%
            </div>
            <div className="body">
              Strong enough to target selective junior roles if you improve
              packaging and interview clarity. Not yet strong enough to apply
              broadly without role filtering.
            </div>
            <div className="rd-timeline">
              <TimelineStep
                num="1"
                title="Tighten proof"
                copy="Convert capstone into cleaner evidence with clearer responsibilities and decisions."
              />
              <TimelineStep
                num="2"
                title="Close one explicit gap"
                copy="Complete testing / debugging practice and surface it in the resume and proof portfolio."
              />
              <TimelineStep
                num="3"
                title="Rehearse project explanation"
                copy="Practice the “Tell me about your project” answer with the Interview Coach."
              />
            </div>
          </div>
        </div>

        <div className="rd-note">
          <b>Design principle</b>
          <span>
            Do not stop at a fit score. Help students understand why they fit, why
            they do not, and exactly where to go next inside the product to close
            the highest-impact gaps.
          </span>
        </div>

        <div className="rd-footer">
          <button
            type="button"
            className="btn primary"
            onClick={() => open("interview")}
          >
            Practice likely interview gaps
          </button>
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

interface TimelineStepProps {
  num: string;
  title: string;
  copy: string;
}

function TimelineStep({ num, title, copy }: TimelineStepProps) {
  return (
    <div className="rd-step">
      <div className="rd-step-no">{num}</div>
      <div className="rd-step-b">
        <b>{title}</b>
        <span>{copy}</span>
      </div>
    </div>
  );
}

function InterviewCoachView({ active }: ViewProps) {
  const [recording, setRecording] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [answer, setAnswer] = useState("");
  const [scorerOut, setScorerOut] = useState<string[] | null>(null);
  const startSession = useStartSession();
  const submitAnswer = useSubmitAnswer();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [currentQuestion, setCurrentQuestion] = useState<string>(
    "Tell me about a project where you used Python to solve a real problem.",
  );
  const intervalRef = useRef<number | null>(null);
  const startedAtRef = useRef<number>(0);

  useEffect(() => {
    return () => {
      if (intervalRef.current !== null) {
        window.clearInterval(intervalRef.current);
      }
    };
  }, []);

  const toggleRec = useCallback(() => {
    if (recording) {
      if (intervalRef.current !== null) {
        window.clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
      setRecording(false);
      v8Toast("Recording paused. Score when you are ready.");
    } else {
      startedAtRef.current = Date.now();
      setRecording(true);
      intervalRef.current = window.setInterval(() => {
        setElapsed(Math.floor((Date.now() - startedAtRef.current) / 1000));
      }, 250);
      if (!sessionId) {
        startSession.mutate(
          { mode: "behavioral" },
          {
            onSuccess: (data) => {
              setSessionId(data.id);
              if (data.first_question) setCurrentQuestion(data.first_question);
            },
          },
        );
      }
    }
  }, [recording, sessionId, startSession]);

  const score = useCallback(() => {
    setScorerOut(scoreInterviewAnswer(answer));
    if (sessionId && answer.trim().length > 0) {
      submitAnswer.mutate(
        { session_id: sessionId, question: currentQuestion, answer },
        {
          onSuccess: (data) => {
            if (data.next_question) setCurrentQuestion(data.next_question);
          },
        },
      );
    }
  }, [answer, currentQuestion, sessionId, submitAnswer]);

  const timerDisplay = `${Math.floor(elapsed / 60)}:${String(elapsed % 60).padStart(2, "0")}`;

  return (
    <div className={`view${active ? " active" : ""}`} id="rd-interview">
      <section className="card pad reveal in">
        <div className="rd-section-k">Interview Coach</div>
        <div className="rd-section-t">
          Replace the static question bank with <i>live practice</i>.
        </div>
        <div className="rd-section-c">
          A plain interview bank is not enough for true job readiness. This
          section helps you rehearse answers, use your own proof, receive
          structure feedback, and build calm under pressure.
        </div>

        <div className="rd-2col" style={{ marginTop: 18 }}>
          <div className="match-card">
            <div className="k">Live prompt</div>
            <div className="big">“{currentQuestion}”</div>
            <div className="body">
              The coach pushes you toward a simple structure: context, what you
              built, technical decisions, challenge handled, and result or
              learning.
            </div>
            <div className="qa-set">
              <div className="qa-item">
                <div className="qa-q">Suggested answer structure</div>
                <div className="qa-a">
                  I built a CLI AI tool in Python as part of a capstone. The goal
                  was to send prompts to an API and return useful responses through
                  a simple terminal interface. I isolated the API logic in its own
                  async function, then improved the design based on review feedback
                  around retry logic and environment-based configuration. The main
                  thing I learned was how to structure async work cleanly and think
                  about production gaps, not just getting the first version
                  running.
                </div>
              </div>
              <div className="qa-item">
                <div className="qa-q">Coach feedback</div>
                <div className="qa-a">
                  Good technical signal. Stronger if you name the problem more
                  concretely, explain one debugging moment, and finish with what
                  this project proves about how you work.
                </div>
              </div>
            </div>
          </div>
          <div className="match-card">
            <div className="k">Performance snapshot</div>
            <div className="big">
              <span className="count">57</span>% answer readiness
            </div>
            <div className="rd-list">
              <EvidenceRow
                title="Clarity"
                copy="Your technical ideas are there, but the story arc still meanders."
                badge="Improve"
                tone="warn"
              />
              <EvidenceRow
                title="Proof usage"
                copy="You refer to real work, much better than generic theory answers."
                badge="Strong"
                tone="good"
              />
              <EvidenceRow
                title="Outcome framing"
                copy="Needs a sharper ending — what did the project prove, fix, or teach?"
                badge="Improve"
                tone="warn"
              />
            </div>
            <div className="coach-rec">
              <div className="rec-head">
                <b>Rehearse your answer</b>
                <span className="rec-timer">{timerDisplay}</span>
              </div>
              <textarea
                className="coach-answer"
                placeholder="Type or dictate your answer here. Aim for context → build → decision → challenge → result."
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
              />
              <div className={`rec-wave${recording ? " live" : ""}`}>
                {Array.from({ length: 10 }).map((_, i) => (
                  <div key={i} className="rec-bar" />
                ))}
              </div>
              <div className="rd-footer" style={{ marginTop: 12 }}>
                <button type="button" className="btn primary" onClick={toggleRec}>
                  {recording ? "Stop recording" : "Start mock interview"}
                </button>
                <button type="button" className="btn ghost" onClick={score}>
                  Score my answer
                </button>
              </div>
              <div className={`scorer-out${scorerOut ? " show" : ""}`}>
                <b>Coach feedback</b>
                <ul>
                  {(scorerOut ?? []).map((b, i) => (
                    <li key={i}>{b}</li>
                  ))}
                </ul>
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}

function ProofView({ open, active }: ViewProps) {
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
            <div className="t">CLI AI Tool</div>
            <pre>{`async def ask_claude(prompt):
    for attempt in range(3):
        try:
            resp = await client.messages.create(...)
            return resp.content[0].text
        except APIError:
            await asyncio.sleep(2 ** attempt)
    raise RuntimeError("failed after retries")`}</pre>
            <div className="meta">
              Pulled live from your Studio capstone · 84/100 review · last edited
              today. Signals async thinking, retry logic, isolated API surface.
            </div>
          </div>
          <div className="pf">
            <div className="k">Review signal</div>
            <div className="t">84 / 100 review</div>
            <div className="meta" style={{ marginTop: 14 }}>
              Working strengths: async flow, function isolation, practical project
              direction.
              <br />
              <br />
              Gaps called out: error handling, env config, stronger retry
              behavior.
            </div>
          </div>
          <div className="pf">
            <div className="k">Interview use</div>
            <div className="t">What this proves</div>
            <div className="meta" style={{ marginTop: 14 }}>
              You can talk about an API-based project, explain async choices,
              discuss iteration from review feedback, and show that you think
              beyond the happy path.
            </div>
          </div>
        </div>

        <div className="rd-footer">
          <button
            type="button"
            className="btn primary"
            onClick={() => open("kit")}
          >
            Use this in application kit
          </button>
          <button
            type="button"
            className="btn ghost"
            onClick={() => open("resume")}
          >
            Turn proof into bullets
          </button>
        </div>
      </section>
    </div>
  );
}

interface KitCardData {
  title: string;
  copy: string;
}

const KIT_CARDS: ReadonlyArray<KitCardData> = [
  {
    title: "Role-tailored resume",
    copy: "Built from proof, then shaped for a specific Python Developer job family.",
  },
  {
    title: "Project proof card",
    copy: "A concise summary of your capstone with stack, challenge, approach, and what it proves.",
  },
  {
    title: "Interview story set",
    copy: "Three strong answers: project walkthrough, debugging story, and technical growth arc.",
  },
  {
    title: "Target-role summary",
    copy: "A plain-language note explaining what kinds of roles you should apply for right now.",
  },
  {
    title: "Gap plan",
    copy: "The one or two most valuable things to improve for stronger conversion over the next two weeks.",
  },
  {
    title: "Apply with confidence",
    copy: "A final signal indicating whether you are ready to apply now or should complete one more readiness pass first.",
  },
];

const EXPORT_STEPS: ReadonlyArray<string> = [
  "Compiling resume from proof",
  "Packaging capstone artifact",
  "Bundling interview answers",
  "Finalizing application kit",
];

function KitView({ open, active }: ViewProps) {
  const [showOverlay, setShowOverlay] = useState(false);
  const [pct, setPct] = useState(0);
  const [done, setDone] = useState(false);
  const intervalRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (intervalRef.current !== null) {
        window.clearInterval(intervalRef.current);
      }
    };
  }, []);

  const startExport = useCallback(() => {
    setShowOverlay(true);
    setPct(0);
    setDone(false);
    if (intervalRef.current !== null) {
      window.clearInterval(intervalRef.current);
    }
    intervalRef.current = window.setInterval(() => {
      setPct((p) => {
        const next = Math.min(100, p + 3);
        if (next >= 100) {
          if (intervalRef.current !== null) {
            window.clearInterval(intervalRef.current);
            intervalRef.current = null;
          }
          setDone(true);
          v8Toast("Application kit ready.");
        }
        return next;
      });
    }, 90);
  }, []);

  const closeOverlay = useCallback(() => {
    setShowOverlay(false);
  }, []);

  const download = useCallback(() => {
    const blob = new Blob(
      [
        "CareerForge Application Kit\n\n• Role-tailored resume\n• Capstone proof card\n• 3 interview answers\n• Target-role summary\n• Gap plan\n",
      ],
      { type: "text/plain" },
    );
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "CareerForge-ApplicationKit.txt";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    v8Toast("Downloaded. Good luck.");
  }, []);

  const ringStyle: CSSProperties = {
    background: `conic-gradient(var(--forest) ${pct * 3.6}deg, #e4dbc8 ${pct * 3.6}deg)`,
  };

  const stepStates: ReadonlyArray<boolean> = [25, 50, 75, 100].map((t) => pct >= t);

  return (
    <div className={`view${active ? " active" : ""}`} id="rd-kit">
      <section className="card pad reveal in">
        <div className="rd-section-k">Application Kit</div>
        <div className="rd-section-t">
          Leave this workspace with everything needed to apply.
        </div>
        <div className="rd-section-c">
          This is the conversion layer. The point of Job Readiness is not to
          display tools — it is to help you leave with a clear, usable set of
          assets that support actual applications.
        </div>

        <div className="kit-grid">
          {KIT_CARDS.map((c) => (
            <div key={c.title} className="kit-card">
              <b>{c.title}</b>
              <span>{c.copy}</span>
            </div>
          ))}
        </div>

        <div className="rd-note">
          <b>How this page should feel</b>
          <span>
            Not like a careers dashboard. Not like a modal stack. It should feel
            like a calm operating workspace that diagnoses readiness, guides one
            focused action at a time, and helps the student leave with tangible,
            real-world outputs.
          </span>
        </div>

        <div className="rd-footer">
          <button type="button" className="btn primary" onClick={startExport}>
            Export application kit
          </button>
          <button
            type="button"
            className="btn ghost"
            onClick={() => open("overview")}
          >
            Return to overview
          </button>
        </div>
        <div className="rd-helper">
          Recommended default loop: Overview → Resume Lab → JD Match → Interview
          Coach → Application Kit.
        </div>
      </section>

      {showOverlay ? (
        <ExportOverlay
          pct={pct}
          ringStyle={ringStyle}
          stepStates={stepStates}
          done={done}
          onClose={closeOverlay}
          onDownload={download}
        />
      ) : null}
    </div>
  );
}

interface ExportOverlayProps {
  pct: number;
  ringStyle: CSSProperties;
  stepStates: ReadonlyArray<boolean>;
  done: boolean;
  onClose: () => void;
  onDownload: () => void;
}

function ExportOverlay({
  pct,
  ringStyle,
  stepStates,
  done,
  onClose,
  onDownload,
}: ExportOverlayProps): ReactNode {
  return (
    <div className="export-overlay show" role="dialog" aria-modal="true">
      <div className="export-card">
        <div className="export-ring" style={ringStyle}>
          <span>{pct}%</span>
        </div>
        <b>Building your application kit</b>
        <div className="export-steps">
          {EXPORT_STEPS.map((label, i) => (
            <div
              key={label}
              className={`export-step${stepStates[i] ? " done" : ""}`}
            >
              {label}
            </div>
          ))}
          {done ? (
            <div className="export-step done">Download ready</div>
          ) : null}
        </div>
        <div className="rd-footer" style={{ marginTop: 14 }}>
          {done ? (
            <button type="button" className="btn primary" onClick={onDownload}>
              Download kit
            </button>
          ) : null}
          {done ? (
            <button type="button" className="btn ghost" onClick={onClose}>
              Close
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
