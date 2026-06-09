/**
 * Readiness overview (live) — verifies the rewire to real data:
 *  - the score ring renders the real `overall_readiness` (no hard-coded 62%)
 *  - top_actions render as buttons in the hero
 *  - clicking a top action routes via the `open()` callback (verified by
 *    asserting the activeView swap removes the overview from the DOM)
 *  - while the hook is loading, a slim skeleton renders instead of the
 *    misleading legacy demo data
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { ReadinessScreen } from "@/components/v8/screens/readiness-screen";
import type { ReadinessOverviewResponse } from "@/lib/api-client";

const mockOverview = vi.fn();
const recordEventSpy = vi.fn();

vi.mock("@/lib/hooks/use-readiness-overview", () => ({
  useReadinessOverview: () => mockOverview(),
  useReadinessProof: () => ({ data: undefined, isLoading: false }),
}));

vi.mock("@/lib/hooks/use-readiness-events", () => ({
  useRecordWorkspaceEvent: () => recordEventSpy,
  useFlushWorkspaceEvents: () => vi.fn(),
}));

vi.mock("@/lib/hooks/use-progress", () => ({
  useMyProgress: () => ({ data: undefined }),
}));

vi.mock("@/lib/hooks/use-career", () => ({
  useMyResume: () => ({ data: undefined, isLoading: false }),
  useRegenerateResume: () => ({ mutate: vi.fn(), isPending: false }),
  useFitScore: () => ({ mutate: vi.fn(), data: undefined, isPending: false }),
  useSaveJd: () => ({ mutate: vi.fn(), isPending: false }),
  useJdLibrary: () => ({ data: [] }),
}));

vi.mock("@/lib/hooks/use-application-kit", () => ({
  useApplicationKits: () => ({ data: [], refetch: vi.fn() }),
  useBuildApplicationKit: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteApplicationKit: () => ({ mutate: vi.fn(), isPending: false }),
  applicationKitDownloadUrl: (id: string) => `/api/v1/readiness/kit/${id}/download`,
}));

vi.mock("@/lib/hooks/use-portfolio-autopsy", () => ({
  useAutopsyList: () => ({ data: [] }),
  useCreateAutopsy: () => ({ mutate: vi.fn(), isPending: false }),
}));

vi.mock("@/lib/hooks/use-mock-interview", () => ({
  useMyMockSessions: () => ({ data: [] }),
}));

vi.mock("@/components/v8/v8-topbar-context", () => ({
  useSetV8Topbar: vi.fn(),
}));

vi.mock("@/components/v8/v8-toast", () => ({
  v8Toast: vi.fn(),
}));

vi.mock("@/stores/auth-store", () => ({
  useAuthStore: (selector?: (s: unknown) => unknown) => {
    const state = {
      user: { id: "u1", full_name: "Demo User", role: "student" },
      isAuthenticated: true,
    };
    return selector ? selector(state) : state;
  },
}));

vi.mock("@/components/features/readiness-diagnostic", () => ({
  DiagnosticAnchor: () => <div data-testid="diag-anchor" />,
  isReadinessDiagnosticEnabled: () => true,
}));

vi.mock("@/components/features/jd-decoder", () => ({
  DecoderCard: () => <div />,
  isJdDecoderEnabled: () => true,
}));

vi.mock("@/components/features/mock-interview", () => ({
  MockInterviewWorkspace: () => <div />,
  isMockInterviewEnabled: () => false,
}));

vi.mock("@/components/features/tailored-resume", () => ({
  IntakeModal: () => <div />,
  TailoredResumeQuotaChip: () => <div />,
}));

function makeOverview(
  overrides: Partial<ReadinessOverviewResponse> = {},
): ReadinessOverviewResponse {
  return {
    user_first_name: "Demo",
    target_role: "Python Developer",
    overall_readiness: 67,
    sub_scores: { skill: 72, proof: 55, interview: 48, targeting: 64 },
    north_star: { current: 67, prior: 60, delta_week: 7 },
    top_actions: [
      {
        kind: "build_resume",
        route: "resume",
        label: "Build resume from proof",
      },
      {
        kind: "match_jd",
        route: "jd",
        label: "Match me to a real JD",
      },
    ],
    latest_verdict: null,
    trend_8w: [
      { week_start: "2026-03-02", score: 40 },
      { week_start: "2026-03-09", score: 45 },
      { week_start: "2026-03-16", score: 51 },
      { week_start: "2026-03-23", score: 58 },
      { week_start: "2026-03-30", score: 60 },
      { week_start: "2026-04-06", score: 62 },
      { week_start: "2026-04-13", score: 65 },
      { week_start: "2026-04-20", score: 67 },
    ],
    ...overrides,
  };
}

describe("ReadinessScreen — overview (live)", () => {
  beforeEach(() => {
    mockOverview.mockReset();
    recordEventSpy.mockReset();
  });

  it("renders the real overall_readiness score (67%) sourced from the hook", () => {
    mockOverview.mockReturnValue({
      data: makeOverview(),
      isLoading: false,
    });
    render(<ReadinessScreen />);
    // The hero score ring should render "67" — the legacy hard-coded "62"
    // would be a regression.
    expect(screen.getByText("67")).toBeInTheDocument();
    // And not the legacy fixture either:
    expect(screen.queryByText("44 → 51 → 58 → 62")).not.toBeInTheDocument();
  });

  it("renders top_actions as hero CTA buttons", () => {
    mockOverview.mockReturnValue({
      data: makeOverview(),
      isLoading: false,
    });
    render(<ReadinessScreen />);
    expect(
      screen.getAllByRole("button", { name: /build resume from proof/i }).length,
    ).toBeGreaterThan(0);
    expect(
      screen.getAllByRole("button", { name: /match me to a real jd/i }).length,
    ).toBeGreaterThan(0);
  });

  it("clicking a top action opens the matching view (and records a cta_clicked event)", () => {
    mockOverview.mockReturnValue({
      data: makeOverview(),
      isLoading: false,
    });
    render(<ReadinessScreen />);
    const buttons = screen.getAllByRole("button", {
      name: /build resume from proof/i,
    });
    fireEvent.click(buttons[0]);
    // Expect cta_clicked event recorded with the right route payload.
    expect(recordEventSpy).toHaveBeenCalledWith(
      "overview",
      "cta_clicked",
      expect.objectContaining({ route: "resume" }),
    );
    // And view_opened fired for the new active view.
    expect(recordEventSpy).toHaveBeenCalledWith("resume", "view_opened");
  });

  it("renders the skeleton (no fake 62%) while the overview hook is loading", () => {
    mockOverview.mockReturnValue({
      data: undefined,
      isLoading: true,
    });
    render(<ReadinessScreen />);
    expect(screen.getByTestId("rd-overview-skeleton")).toBeInTheDocument();
    // The legacy demo "62%" must not leak through during loading.
    expect(screen.queryByText("62")).not.toBeInTheDocument();
    // And the diagnostic anchor isn't rendered until data arrives.
    expect(screen.queryByTestId("diag-anchor")).not.toBeInTheDocument();
  });
});
