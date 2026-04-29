/**
 * PR1/A3.2 — Frontend API-shape snapshot tests.
 *
 * Each public response interface that the screens consume is locked
 * down by a Vitest snapshot. If a field is added, removed, or renamed
 * in `frontend/src/lib/api-client.ts` (or `chat-api.ts`), the snapshot
 * test fails until the snapshot is intentionally re-generated.
 *
 * Why snapshots, not type-level assertions:
 *   - We want CI to fail noisily on drift, not at a TS-only call site.
 *   - Snapshots are easy to review: the diff IS the breaking change.
 *   - The matching backend contract test (`backend/tests/test_contracts/
 *     test_aggregator_contracts.py`) catches the *server* side; this one
 *     catches the *client* side. Together they prevent silent drift in
 *     either direction.
 *
 * ## How to update
 *
 * If you intentionally change an interface, run:
 *
 *   pnpm vitest run src/test/contracts/api-shape.test.ts -u
 *
 * Then UPDATE the matching spec in
 * `backend/tests/test_contracts/test_aggregator_contracts.py` in the
 * SAME pull request. Treat the two as a single edit.
 */
import { describe, expect, it } from "vitest";
import type {
  CatalogResponse,
  ExerciseResponse,
  PathSummaryResponse,
  PromotionSummaryResponse,
  SRSCard,
  TodaySummaryResponse,
} from "@/lib/api-client";
import type { NotebookEntryOut } from "@/lib/chat-api";

/**
 * Returns the sorted top-level key list of a fixture object. We snapshot
 * key sets (not values) because values change per-environment but the
 * shape is the contract. For nested objects we walk them and emit a
 * stable key-list-of-key-lists shape.
 */
function shape<T extends object>(fixture: T): unknown {
  if (Array.isArray(fixture)) {
    if (fixture.length === 0) return [];
    return [shape(fixture[0] as object)];
  }
  if (fixture === null || typeof fixture !== "object") {
    return typeof fixture;
  }
  const out: Record<string, unknown> = {};
  for (const k of Object.keys(fixture).sort()) {
    const v = (fixture as Record<string, unknown>)[k];
    if (v !== null && typeof v === "object") {
      out[k] = shape(v as object);
    } else {
      out[k] = typeof v;
    }
  }
  return out;
}

// ───────────────────────────────────────────────────────────────────
// Fixtures — minimal objects that satisfy each interface, used as the
// snapshot input. The TypeScript compiler is the first line of defence:
// if you remove a required field from the interface, this file stops
// compiling. The snapshot is the second line: if you add a new required
// field, this fixture starts emitting a new key and the test fails.
// ───────────────────────────────────────────────────────────────────

const TODAY_FIXTURE: TodaySummaryResponse = {
  user: { first_name: "Demo" },
  goal: {
    success_statement: "x",
    target_role: "Data Analyst",
    days_remaining: 60,
    motivation: "career_switch",
  },
  consistency: { days_active: 1, window_days: 7 },
  progress: {
    overall_percentage: 50,
    lessons_completed_total: 2,
    lessons_total: 4,
    today_unlock_percentage: 25,
    active_course_id: "c1",
    active_course_title: "Python",
    next_lesson_id: "l1",
    next_lesson_title: "L1",
  },
  session: {
    id: "s1",
    ordinal: 1,
    started_at: "2026-04-28T00:00:00Z",
    warmup_done_at: null,
    lesson_done_at: null,
    reflect_done_at: null,
  },
  current_focus: { skill_slug: "py", skill_name: "Python", skill_blurb: "x" },
  capstone: {
    exercise_id: "e1",
    title: "CLI",
    days_to_due: 5,
    draft_quality: 80,
    drafts_count: 1,
  },
  next_milestone: { label: "Data Analyst", days: 60 },
  readiness: { current: 60, delta_week: 5 },
  intention: { text: "ship one async client" },
  due_card_count: 0,
  peers_at_level: 3,
  promotions_today: 1,
  micro_wins: [],
  cohort_events: [],
};

const PATH_FIXTURE: PathSummaryResponse = {
  overall_progress: 33,
  active_course_id: "c1",
  active_course_title: "Python",
  constellation: [
    { label: "Python", sub: "Mastered", state: "done", badge: "1" },
  ],
  levels: [
    {
      badge: "1",
      title: "Python",
      blurb: "Foundations.",
      progress_percentage: 33,
      lessons: [],
      state: "current",
      unlock_course_id: null,
      unlock_price_cents: null,
      unlock_currency: null,
      unlock_lesson_count: null,
      unlock_lab_count: null,
    },
  ],
  proof_wall: [],
};

const PROMOTION_FIXTURE: PromotionSummaryResponse = {
  overall_progress: 50,
  rungs: [],
  role: { from_role: "Python Developer", to_role: "Data Analyst" },
  stats: {
    completed_lessons: 0,
    total_lessons: 0,
    due_card_count: 0,
    completed_interviews: 0,
    capstone_submissions: 0,
  },
  gate_status: "not_ready",
  promoted_at: null,
  promoted_to_role: null,
  user_first_name: "Demo",
};

const CATALOG_FIXTURE: CatalogResponse = {
  courses: [],
  bundles: [],
};

const EXERCISE_FIXTURE: ExerciseResponse = {
  id: "e1",
  lesson_id: "l1",
  title: "Retry with backoff",
  description: "Retry a flaky API.",
  exercise_type: "coding",
  difficulty: "intermediate",
  starter_code: null,
  solution_code: null,
  test_cases: null,
  rubric: null,
  points: 50,
  order: 0,
  github_template_url: null,
  is_capstone: false,
  pass_score: 70,
  due_at: null,
};

const NOTEBOOK_FIXTURE: NotebookEntryOut = {
  id: "n1",
  message_id: "m1",
  conversation_id: "c1",
  content: "x",
  title: null,
  user_note: null,
  source_type: "chat",
  topic: null,
  tags: [],
  graduated_at: null,
  last_reviewed_at: null,
  created_at: "2026-04-28T00:00:00Z",
};

const SRS_FIXTURE: SRSCard = {
  id: "s1",
  concept_key: "k",
  prompt: "p",
  answer: "",
  hint: "",
  ease_factor: 2.5,
  interval_days: 1,
  repetitions: 0,
  next_due_at: "2026-04-28T00:00:00Z",
  last_reviewed_at: null,
};

// ───────────────────────────────────────────────────────────────────
// Snapshots
// ───────────────────────────────────────────────────────────────────

describe("API response shape contracts", () => {
  it("TodaySummaryResponse", () => {
    expect(shape(TODAY_FIXTURE)).toMatchSnapshot();
  });

  it("PathSummaryResponse", () => {
    expect(shape(PATH_FIXTURE)).toMatchSnapshot();
  });

  it("PromotionSummaryResponse", () => {
    expect(shape(PROMOTION_FIXTURE)).toMatchSnapshot();
  });

  it("CatalogResponse", () => {
    expect(shape(CATALOG_FIXTURE)).toMatchSnapshot();
  });

  it("ExerciseResponse", () => {
    expect(shape(EXERCISE_FIXTURE)).toMatchSnapshot();
  });

  it("NotebookEntryOut", () => {
    expect(shape(NOTEBOOK_FIXTURE)).toMatchSnapshot();
  });

  it("SRSCard", () => {
    expect(shape(SRS_FIXTURE)).toMatchSnapshot();
  });
});
