export type SignalKind = "job" | "incident" | "shift" | "bench" | "tool";

export interface Signal {
  kind: SignalKind;
  headline: string;
  body: string;
  source: string;
  sourceUrl?: string;
  recordedAt: string; // ISO date
}

/**
 * Seed fixture of "signals from reality" — curated industry observations that
 * connect what a student is learning to what the market actually wants.
 *
 * These are deliberately evergreen and source-attributed so they don't rot
 * faster than we can replace them. Later phases will replace this with
 * a live feed (job-board scraping, postmortem aggregation, etc.).
 */
export const SIGNALS: Signal[] = [
  {
    kind: "job",
    headline: "RAG evaluation skills show up in 68% of senior AI engineer listings",
    body: "Companies no longer ask 'can you prompt'. They ask for retrieval quality metrics, embedding evaluation, and A/B pipelines.",
    source: "Job-board scan, top-50 AI hires",
    recordedAt: "2026-04-10",
  },
  {
    kind: "incident",
    headline: "A production LLM app shipped with prompt injection — full postmortem",
    body: "A support bot was tricked into exposing customer PII through a multi-turn jailbreak. The team's RCA lists defenses most teams haven't added yet.",
    source: "Public postmortem, eng blog",
    recordedAt: "2026-04-12",
  },
  {
    kind: "shift",
    headline: "Long-context windows don't replace retrieval — they amplify it",
    body: "Teams that tried 'just dump everything into context' are now measuring 4× cost for equivalent quality vs. well-tuned retrieval. The bar is rising, not falling.",
    source: "Independent benchmark study",
    recordedAt: "2026-04-08",
  },
  {
    kind: "bench",
    headline: "Claude Opus 4.6 beats gpt-5 on code-editing by 11 points",
    body: "SWE-bench verified results published last week. If you're building agentic coding, this is the week to re-evaluate your model choice.",
    source: "SWE-bench leaderboard",
    recordedAt: "2026-04-14",
  },
  {
    kind: "tool",
    headline: "LangGraph 0.3 ships interrupt-resume semantics",
    body: "Long-running agent workflows can now pause, await human input, and resume deterministically. This is the unlock for production agent apps.",
    source: "LangChain changelog",
    recordedAt: "2026-04-11",
  },
  {
    kind: "job",
    headline: "AI platform roles now pay 18% more than 'ML engineer' on average",
    body: "The shift is explicit: companies want the person who operates the model in production, not the one who trained it.",
    source: "Levels.fyi aggregate data",
    recordedAt: "2026-04-05",
  },
  {
    kind: "incident",
    headline: "A startup lost $300k to a runaway agent cost loop in 4 hours",
    body: "Their agent retried tool calls on 429s without exponential backoff. Budget alerts didn't fire because the provider billed in arrears.",
    source: "Founder Twitter thread",
    recordedAt: "2026-04-09",
  },
  {
    kind: "shift",
    headline: "Evaluation harnesses are the new CI — not optional",
    body: "Top teams now gate deploys on regression scores across a curated eval set. If you can't show a passing eval run in PR, you don't ship.",
    source: "Industry survey, 40 AI teams",
    recordedAt: "2026-04-07",
  },
  {
    kind: "tool",
    headline: "Pinecone vs pgvector: the answer is 'it depends' — again",
    body: "A new head-to-head benchmark shows pgvector has closed the gap for <10M vectors. For >100M it still loses on latency. Pick by scale, not by hype.",
    source: "Benchmark study, public repo",
    recordedAt: "2026-04-13",
  },
  {
    kind: "bench",
    headline: "Agents with tool-use now pass 47% of real bug-fix tasks",
    body: "That's up from 31% six months ago. The gap between 'cool demo' and 'shipped feature' is closing faster than most teams realize.",
    source: "SWE-bench Verified",
    recordedAt: "2026-04-15",
  },
];
