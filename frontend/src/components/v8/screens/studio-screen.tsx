"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useSetV8Topbar } from "@/components/v8/v8-topbar-context";
import { v8Toast } from "@/components/v8/v8-toast";
import { useSeniorReview } from "@/lib/hooks/use-senior-review";
import { executeApi } from "@/lib/api-client";
import { useAuthStore } from "@/stores/auth-store";

type StudioTab = "code" | "trace" | "labs" | "tests";

const SAMPLE_CODE = `# CareerForge capstone · CLI AI Tool
import os, asyncio
from anthropic import Anthropic, APIError

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

async def ask_claude(prompt: str) -> str:
    for attempt in range(3):
        try:
            resp = await client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.content[0].text
        except APIError:
            await asyncio.sleep(2 ** attempt)
    raise RuntimeError("Request failed after retries")

async def main():
    while True:
        prompt = input("\\nYou: ")
        reply = await ask_claude(prompt)
        print(f"Claude: {reply}")
`;

interface ReviewItem {
  variant: "good" | "warn" | "todo";
  heading: string;
  body: string;
}

const DEFAULT_REVIEW: ReviewItem[] = [
  {
    variant: "good",
    heading: "What is working",
    body: "The async path is isolated and readable. Retry logic now protects against transient failures.",
  },
  {
    variant: "warn",
    heading: "Close this gap",
    body: "Add one user-friendly failure message when all retries are exhausted so CLI behavior stays calm.",
  },
  {
    variant: "todo",
    heading: "Before submission",
    body: "Extract request settings into a small config block so the tool becomes easier to test and maintain.",
  },
];

export function StudioScreen() {
  useSetV8Topbar({
    eyebrow: "Studio · Capstone draft",
    titleHtml: "Build with feedback that feels <i>senior and calm</i>.",
    chips: [],
    progress: 66,
  });

  const searchParams = useSearchParams();
  const initialTab: StudioTab = searchParams.get("lab") === "B" ? "labs" : "code";
  const [activeTab, setActiveTab] = useState<StudioTab>(initialTab);
  const [revealedCount, setRevealedCount] = useState(0);
  const [score] = useState<number>(87);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const seniorReview = useSeniorReview();
  const timersRef = useRef<number[]>([]);

  useEffect(() => {
    return () => {
      timersRef.current.forEach((id) => window.clearTimeout(id));
      timersRef.current = [];
    };
  }, []);

  const reviewItems = useMemo<ReviewItem[]>(() => {
    const data = seniorReview.data;
    if (!data) return DEFAULT_REVIEW;
    const items: ReviewItem[] = [];
    if (data.strengths.length > 0) {
      items.push({
        variant: "good",
        heading: "What is working",
        body: data.strengths[0],
      });
    } else {
      items.push(DEFAULT_REVIEW[0]);
    }
    const concern = data.comments.find(
      (c) => c.severity === "concern" || c.severity === "blocking",
    );
    items.push({
      variant: "warn",
      heading: "Close this gap",
      body: concern?.message ?? DEFAULT_REVIEW[1].body,
    });
    items.push({
      variant: "todo",
      heading: "Before submission",
      body: data.next_step || DEFAULT_REVIEW[2].body,
    });
    return items;
  }, [seniorReview.data]);

  const revealReviewSequence = useCallback(() => {
    setRevealedCount(0);
    timersRef.current.forEach((id) => window.clearTimeout(id));
    timersRef.current = [];
    for (let i = 1; i <= 3; i += 1) {
      const id = window.setTimeout(() => {
        setRevealedCount((c) => Math.max(c, i));
      }, i * 120);
      timersRef.current.push(id);
    }
  }, []);

  const handleRunAndReview = useCallback(async () => {
    revealReviewSequence();
    if (isAuthenticated) {
      try {
        await executeApi.run({ code: SAMPLE_CODE });
      } catch {
        // Sandbox execution is best-effort visual wiring; fall through to toast.
      }
    }
    v8Toast("Review revealed in a calm sequence.");
  }, [isAuthenticated, revealReviewSequence]);

  const handleRequestReview = useCallback(() => {
    if (!isAuthenticated) {
      revealReviewSequence();
      v8Toast("Review revealed in a calm sequence.");
      return;
    }
    seniorReview.mutate(
      { code: SAMPLE_CODE, problemContext: "CareerForge capstone CLI" },
      {
        onSuccess: () => {
          revealReviewSequence();
          v8Toast("Senior review delivered.");
        },
        onError: () => {
          revealReviewSequence();
          v8Toast("Review revealed in a calm sequence.");
        },
      },
    );
  }, [isAuthenticated, revealReviewSequence, seniorReview]);

  const scoreDeg = Math.max(0, Math.min(100, score)) * 3.6;
  const scoreWheelStyle: React.CSSProperties = {
    background: `conic-gradient(var(--forest) 0 ${scoreDeg}deg, #dfe9e1 ${scoreDeg}deg 360deg)`,
  };

  return (
    <section className="screen active" id="screen-studio">
      <div className="pad">
        <div className="grid studio-grid">
          <section className="editor reveal">
            <div className="editor-bar">
              <div className="editor-tabs">
                <div
                  className={`editor-tab${activeTab === "code" ? " active" : ""}`}
                  data-studio-tab="code"
                  onClick={() => setActiveTab("code")}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") setActiveTab("code");
                  }}
                >
                  Code
                </div>
                <div
                  className={`editor-tab${activeTab === "trace" ? " active" : ""}`}
                  data-studio-tab="trace"
                  onClick={() => setActiveTab("trace")}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") setActiveTab("trace");
                  }}
                >
                  Trace
                </div>
                <div
                  className={`editor-tab labs-tab${activeTab === "labs" ? " active" : ""}`}
                  data-studio-tab="labs"
                  onClick={() => setActiveTab("labs")}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") setActiveTab("labs");
                  }}
                >
                  Labs<span className="new-pill">NEW</span>
                </div>
                <div
                  className={`editor-tab${activeTab === "tests" ? " active" : ""}`}
                  data-studio-tab="tests"
                  onClick={() => setActiveTab("tests")}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") setActiveTab("tests");
                  }}
                >
                  Tests
                </div>
              </div>
              <div className="editor-actions">
                <button
                  className="editor-btn"
                  type="button"
                  onClick={handleRequestReview}
                  disabled={seniorReview.isPending}
                >
                  {seniorReview.isPending ? "Requesting…" : "Request review"}
                </button>
                <button
                  className="editor-btn run"
                  type="button"
                  onClick={handleRunAndReview}
                >
                  Run and review
                </button>
              </div>
            </div>

            <div
              className="code"
              id="studioCode"
              style={{ display: activeTab === "code" ? undefined : "none" }}
            >
              <div className="line">
                <span className="ln">1</span>
                <span className="cm"># CareerForge capstone · CLI AI Tool</span>
              </div>
              <div className="line">
                <span className="ln">2</span>
                <span>
                  <span className="kw">import</span> <span className="vr">os</span>,{" "}
                  <span className="vr">asyncio</span>
                </span>
              </div>
              <div className="line">
                <span className="ln">3</span>
                <span>
                  <span className="kw">from</span> <span className="vr">anthropic</span>{" "}
                  <span className="kw">import</span> <span className="vr">Anthropic</span>,{" "}
                  <span className="vr">APIError</span>
                </span>
              </div>
              <div className="line">
                <span className="ln">4</span>
                <span></span>
              </div>
              <div className="line">
                <span className="ln">5</span>
                <span>
                  <span className="vr">client</span> = <span className="fn">Anthropic</span>(
                  <span className="vr">api_key</span>=<span className="vr">os</span>.
                  <span className="fn">getenv</span>(
                  <span className="st">&quot;ANTHROPIC_API_KEY&quot;</span>))
                </span>
              </div>
              <div className="line">
                <span className="ln">6</span>
                <span></span>
              </div>
              <div className="line">
                <span className="ln">7</span>
                <span>
                  <span className="kw">async def</span> <span className="fn">ask_claude</span>(
                  <span className="vr">prompt</span>: <span className="vr">str</span>) -&gt;{" "}
                  <span className="vr">str</span>:
                </span>
              </div>
              <div className="line">
                <span className="ln">8</span>
                <span>
                  {"    "}
                  <span className="kw">for</span> <span className="vr">attempt</span>{" "}
                  <span className="kw">in</span> <span className="fn">range</span>(
                  <span className="nm">3</span>):
                </span>
              </div>
              <div className="line">
                <span className="ln">9</span>
                <span>
                  {"        "}
                  <span className="kw">try</span>:
                </span>
              </div>
              <div className="line">
                <span className="ln">10</span>
                <span>
                  {"            "}
                  <span className="vr">resp</span> = <span className="kw">await</span>{" "}
                  <span className="vr">client</span>.<span className="vr">messages</span>.
                  <span className="fn">create</span>(
                </span>
              </div>
              <div className="line">
                <span className="ln">11</span>
                <span>
                  {"                "}
                  <span className="vr">model</span>=
                  <span className="st">&quot;claude-sonnet-4-5&quot;</span>,
                </span>
              </div>
              <div className="line">
                <span className="ln">12</span>
                <span>
                  {"                "}
                  <span className="vr">max_tokens</span>=<span className="nm">1024</span>,
                </span>
              </div>
              <div className="line">
                <span className="ln">13</span>
                <span>
                  {"                "}
                  <span className="vr">messages</span>=[{"{"}
                  <span className="st">&quot;role&quot;</span>:{" "}
                  <span className="st">&quot;user&quot;</span>,{" "}
                  <span className="st">&quot;content&quot;</span>:{" "}
                  <span className="vr">prompt</span>
                  {"}"}],
                </span>
              </div>
              <div className="line">
                <span className="ln">14</span>
                <span>{"            "})</span>
              </div>
              <div className="line">
                <span className="ln">15</span>
                <span>
                  {"            "}
                  <span className="kw">return</span> <span className="vr">resp</span>.
                  <span className="vr">content</span>[<span className="nm">0</span>].
                  <span className="vr">text</span>
                </span>
              </div>
              <div className="line">
                <span className="ln">16</span>
                <span>
                  {"        "}
                  <span className="kw">except</span> <span className="vr">APIError</span>:
                </span>
              </div>
              <div className="line">
                <span className="ln">17</span>
                <span>
                  {"            "}
                  <span className="kw">await</span> <span className="vr">asyncio</span>.
                  <span className="fn">sleep</span>(<span className="nm">2</span> **{" "}
                  <span className="vr">attempt</span>)
                </span>
              </div>
              <div className="line">
                <span className="ln">18</span>
                <span>
                  {"    "}
                  <span className="kw">raise</span> <span className="vr">RuntimeError</span>(
                  <span className="st">&quot;Request failed after retries&quot;</span>)
                </span>
              </div>
              <div className="line">
                <span className="ln">19</span>
                <span></span>
              </div>
              <div className="line">
                <span className="ln">20</span>
                <span>
                  <span className="kw">async def</span> <span className="fn">main</span>():
                </span>
              </div>
              <div className="line">
                <span className="ln">21</span>
                <span>
                  {"    "}
                  <span className="kw">while</span> <span className="vr">True</span>:
                </span>
              </div>
              <div className="line">
                <span className="ln">22</span>
                <span>
                  {"        "}
                  <span className="vr">prompt</span> = <span className="fn">input</span>(
                  <span className="st">&quot;\nYou: &quot;</span>)
                </span>
              </div>
              <div className="line">
                <span className="ln">23</span>
                <span>
                  {"        "}
                  <span className="vr">reply</span> = <span className="kw">await</span>{" "}
                  <span className="fn">ask_claude</span>(<span className="vr">prompt</span>)
                </span>
              </div>
              <div className="line">
                <span className="ln">24</span>
                <span>
                  {"        "}
                  <span className="fn">print</span>(
                  <span className="st">f&quot;Claude: {"{"}reply{"}"}&quot;</span>)
                </span>
              </div>
            </div>

            <div
              className={`labs-view${activeTab === "labs" ? " active" : ""}`}
              id="studioLabs"
              style={{ display: activeTab === "labs" ? "block" : "none" }}
            >
              <div className="labs-view-head">
                <div>
                  <div className="k">Labs workspace</div>
                  <h4>Hands-on reps between lesson and capstone.</h4>
                  <p>
                    Each lab is a mini-project with real tests. Finishing all three in a lesson
                    noticeably lifts your production readiness score — that&apos;s the number
                    graders care about.
                  </p>
                </div>
                <div className="chip forest">1 of 3 done</div>
              </div>
              <div className="lab-card-grid">
                <article className="lab-card done">
                  <div className="idx">A</div>
                  <div>
                    <b>Retry with exponential backoff</b>
                    <span className="desc">
                      Wrap a flaky call so it retries up to 3 times, doubling the wait each
                      attempt. Tests check for timing + attempt count.
                    </span>
                    <div className="tags">
                      <span className="tag good">✓ 25 min · 94/100</span>
                      <span className="tag">async</span>
                      <span className="tag">error handling</span>
                    </div>
                  </div>
                  <button className="lab-btn ghost" type="button">
                    Review
                  </button>
                </article>
                <article className="lab-card live">
                  <div className="idx">B</div>
                  <div>
                    <b>Rate-limit aware queue</b>
                    <span className="desc">
                      Build a queue that throttles outbound requests to stay under a 10/min
                      ceiling without dropping calls. Tests check ordering + throughput.
                    </span>
                    <div className="tags">
                      <span className="tag warn">● In progress</span>
                      <span className="tag">40 min</span>
                      <span className="tag">concurrency</span>
                    </div>
                  </div>
                  <button className="lab-btn" type="button">
                    Open workspace
                  </button>
                </article>
                <article className="lab-card locked">
                  <div className="idx">C</div>
                  <div>
                    <b>Concurrent batch processor</b>
                    <span className="desc">
                      Fan out 50 prompts through{" "}
                      <code style={{ fontFamily: "var(--mono)", fontSize: ".9em" }}>
                        asyncio.gather
                      </code>{" "}
                      and collect ordered results. Tests check deterministic ordering.
                    </span>
                    <div className="tags">
                      <span className="tag">○ Locked</span>
                      <span className="tag">55 min</span>
                      <span className="tag">gather</span>
                    </div>
                  </div>
                  <button className="lab-btn lock" type="button">
                    Unlocks after B
                  </button>
                </article>
              </div>
            </div>

            {activeTab === "trace" && (
              <div className="code" style={{ padding: 22 }}>
                <div className="line">
                  <span className="ln">·</span>
                  <span className="cm">
                    # Trace events appear here once you press &quot;Run and review&quot;.
                  </span>
                </div>
              </div>
            )}

            {activeTab === "tests" && (
              <div className="code" style={{ padding: 22 }}>
                <div className="line">
                  <span className="ln">·</span>
                  <span className="cm">
                    # Tests panel — author rubric checks alongside your draft.
                  </span>
                </div>
              </div>
            )}
          </section>

          <aside className="review-panel reveal delay-1">
            <div className="mentor-pulse">Senior review mode</div>
            <h4>Responsive guidance, not noisy grading</h4>
            <p>
              The review panel now reveals feedback progressively so the student feels coached,
              not flooded.
            </p>

            <div className="score-ring">
              <div className="score-wheel" style={scoreWheelStyle}>
                <strong>
                  <span className="count">{score}</span>
                </strong>
              </div>
              <div>
                <strong>Production readiness</strong>
                <div className="small" style={{ marginTop: 6 }}>
                  This draft now feels much closer to a credible senior submission.
                </div>
              </div>
            </div>

            <div className="review-stack" id="reviewStack">
              {reviewItems.map((item, idx) => (
                <div
                  key={item.variant}
                  className={`review-item ${item.variant}${idx < revealedCount ? " show" : ""}`}
                >
                  <strong>{item.heading}</strong>
                  <span>{item.body}</span>
                </div>
              ))}
            </div>

            <div className="ask-box">
              <textarea
                placeholder="Ask the reviewer how to strengthen this draft..."
                aria-label="Ask the reviewer"
              />
            </div>
          </aside>
        </div>
      </div>
    </section>
  );
}
