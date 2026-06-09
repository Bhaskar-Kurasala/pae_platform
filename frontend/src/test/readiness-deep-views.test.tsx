/**
 * Deep views (Resume / JD Match / Proof / Application Kit) — verifies
 * the rewire from hard-coded fixture content to real backend data.
 * Mirrors the module-level mock pattern from `today-screen.test.tsx`
 * and `readiness-overview.test.tsx`.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { ReadinessScreen } from "@/components/v8/screens/readiness-screen";

const mockOverview = vi.fn();
const mockProof = vi.fn();
const mockResume = vi.fn();
const mockKitsList = vi.fn();
const mockAutopsyList = vi.fn();
const mockMockSessions = vi.fn();
const mockJdLibrary = vi.fn();

const recordEventSpy = vi.fn();
const flushSpy = vi.fn();
const buildKitMutate = vi.fn();
const deleteKitMutate = vi.fn();
const createAutopsyMutate = vi.fn();
const regenerateMutate = vi.fn();
const fitScoreMutate = vi.fn();
const saveJdMutate = vi.fn();
const refetchKitsSpy = vi.fn();

vi.mock("@/lib/hooks/use-readiness-overview", () => ({
  useReadinessOverview: () => mockOverview(),
  useReadinessProof: () => mockProof(),
}));

vi.mock("@/lib/hooks/use-readiness-events", () => ({
  useRecordWorkspaceEvent: () => recordEventSpy,
  useFlushWorkspaceEvents: () => flushSpy,
}));

vi.mock("@/lib/hooks/use-progress", () => ({
  useMyProgress: () => ({ data: undefined }),
}));

vi.mock("@/lib/hooks/use-career", () => ({
  useMyResume: () => mockResume(),
  useRegenerateResume: () => ({
    mutate: (force: boolean, opts?: { onSuccess?: () => void }) => {
      regenerateMutate(force);
      opts?.onSuccess?.();
    },
    isPending: false,
  }),
  useFitScore: () => ({
    mutate: fitScoreMutate,
    data: undefined,
    isPending: false,
  }),
  useSaveJd: () => ({
    mutate: saveJdMutate,
    isPending: false,
  }),
  useJdLibrary: () => mockJdLibrary(),
}));

vi.mock("@/lib/hooks/use-application-kit", () => ({
  useApplicationKits: () => ({
    data: mockKitsList(),
    refetch: refetchKitsSpy,
  }),
  useBuildApplicationKit: () => ({
    mutate: buildKitMutate,
    isPending: false,
  }),
  useDeleteApplicationKit: () => ({
    mutate: deleteKitMutate,
    isPending: false,
  }),
  applicationKitDownloadUrl: (id: string) =>
    `http://localhost:8000/api/v1/readiness/kit/${id}/download`,
}));

vi.mock("@/lib/hooks/use-portfolio-autopsy", () => ({
  useAutopsyList: () => ({ data: mockAutopsyList() }),
  useCreateAutopsy: () => ({
    mutate: (
      payload: unknown,
      opts?: {
        onSuccess?: (data: { headline: string }) => void;
      },
    ) => {
      createAutopsyMutate(payload);
      opts?.onSuccess?.({ headline: "Created." });
    },
    isPending: false,
  }),
}));

vi.mock("@/lib/hooks/use-mock-interview", () => ({
  useMyMockSessions: () => ({ data: mockMockSessions() }),
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
  isReadinessDiagnosticEnabled: () => false,
}));

vi.mock("@/components/features/jd-decoder", () => ({
  DecoderCard: () => <div data-testid="jd-decoder" />,
  isJdDecoderEnabled: () => true,
}));

vi.mock("@/components/features/mock-interview", () => ({
  MockInterviewWorkspace: () => <div />,
  isMockInterviewEnabled: () => false,
}));

vi.mock("@/components/features/tailored-resume", () => ({
  IntakeModal: () => <div />,
  TailoredResumeQuotaChip: () => <div data-testid="quota-chip" />,
}));

function defaultProof() {
  return {
    capstone_artifacts: [
      {
        exercise_id: "e1",
        title: "CLI AI tool",
        draft_count: 2,
        last_score: 84,
        days_since_last_edit: 1,
      },
    ],
    ai_reviews: {
      count: 3,
      last_three: [
        {
          id: "r1",
          problem_title: "Async APIs",
          score: 82,
          created_at: new Date().toISOString(),
        },
      ],
    },
    mock_reports: [
      {
        session_id: "ms1",
        headline: "Solid story arc",
        verdict: "pass",
        created_at: new Date(Date.now() - 60_000).toISOString(),
        target_role: "Python Developer",
      },
    ],
    autopsies: [
      {
        id: "a1",
        project_title: "CLI AI tool",
        headline: "Strong async, weak observability",
        overall_score: 72,
        created_at: new Date(Date.now() - 86_400_000).toISOString(),
      },
    ],
    peer_reviews: { count_received: 2, count_given: 1 },
    last_capstone_summary: {
      title: "CLI AI tool",
      snippet: "Async API client with retries.",
    },
  };
}

function defaultOverview() {
  return {
    user_first_name: "Demo",
    target_role: "Python Developer",
    overall_readiness: 67,
    sub_scores: { skill: 72, proof: 55, interview: 48, targeting: 64 },
    north_star: { current: 67, prior: 60, delta_week: 7 },
    top_actions: [
      { kind: "build_resume", route: "resume", label: "Build resume from proof" },
    ],
    latest_verdict: null,
    trend_8w: [],
  };
}

beforeEach(() => {
  mockOverview.mockReset();
  mockProof.mockReset();
  mockResume.mockReset();
  mockKitsList.mockReset();
  mockAutopsyList.mockReset();
  mockMockSessions.mockReset();
  mockJdLibrary.mockReset();
  recordEventSpy.mockReset();
  flushSpy.mockReset();
  buildKitMutate.mockReset();
  deleteKitMutate.mockReset();
  createAutopsyMutate.mockReset();
  regenerateMutate.mockReset();
  fitScoreMutate.mockReset();
  saveJdMutate.mockReset();
  refetchKitsSpy.mockReset();

  mockOverview.mockReturnValue({ data: defaultOverview(), isLoading: false });
  mockProof.mockReturnValue({ data: defaultProof(), isLoading: false });
  mockResume.mockReturnValue({
    data: {
      id: "r1",
      title: "Resume",
      summary: "Python · Async APIs",
      bullets: [
        { text: "Built CLI AI tool with retries.", evidence_id: "apis", ats_keywords: [] },
        { text: "Wrote async client with isolation.", evidence_id: "async", ats_keywords: [] },
      ],
      skills_snapshot: null,
      linkedin_blurb: null,
      ats_keywords: [],
      verdict: "good_fit",
    },
    isLoading: false,
  });
  mockKitsList.mockReturnValue([]);
  mockAutopsyList.mockReturnValue([]);
  mockMockSessions.mockReturnValue([]);
  mockJdLibrary.mockReturnValue([]);
});

describe("ReadinessScreen — Resume tab subnav", () => {
  it("clicking the Bullets tab records subnav_clicked and reveals real bullet rows", () => {
    render(<ReadinessScreen />);
    // Open the Resume view from the side nav.
    fireEvent.click(
      screen.getByRole("button", { name: /^2\s*Resume Lab/ }),
    );
    // Click the "Bullets" subtab.
    fireEvent.click(screen.getByRole("button", { name: /^Bullets$/i }));
    expect(recordEventSpy).toHaveBeenCalledWith(
      "resume",
      "subnav_clicked",
      expect.objectContaining({ tab: "bullets" }),
    );
    // Real bullet text from the mocked useMyResume() shows up.
    expect(
      screen.getByText(/Built CLI AI tool with retries\./i),
    ).toBeInTheDocument();
  });
});

describe("ReadinessScreen — Proof view", () => {
  it("renders autopsy rows from useReadinessProof", () => {
    render(<ReadinessScreen />);
    fireEvent.click(
      screen.getByRole("button", { name: /^5\s*Proof Portfolio/ }),
    );
    expect(screen.getByTestId("proof-autopsy-list")).toBeInTheDocument();
    expect(
      screen.getByText(/Strong async, weak observability/i),
    ).toBeInTheDocument();
  });

  it("clicking 'Run a new autopsy' opens the modal and submitting calls useCreateAutopsy.mutate", () => {
    render(<ReadinessScreen />);
    fireEvent.click(
      screen.getByRole("button", { name: /^5\s*Proof Portfolio/ }),
    );
    fireEvent.click(screen.getByRole("button", { name: /Run a new autopsy/i }));
    // Modal title input should now exist.
    const titleInput = screen.getByLabelText(/Project title/i);
    fireEvent.change(titleInput, { target: { value: "Capstone v2" } });
    fireEvent.change(screen.getByLabelText(/What did you build\?/i), {
      target: {
        value:
          "An async CLI AI tool that calls Claude with retries and structured prompts.",
      },
    });
    fireEvent.click(screen.getByRole("button", { name: /Create autopsy/i }));
    expect(createAutopsyMutate).toHaveBeenCalledWith(
      expect.objectContaining({
        project_title: "Capstone v2",
        project_description: expect.stringContaining("async CLI"),
      }),
    );
  });
});

describe("ReadinessScreen — Kit view", () => {
  it("shows empty-state copy when no kits are returned", () => {
    render(<ReadinessScreen />);
    // Side-nav button — the one whose accessible name starts with "6 Application Kit".
    fireEvent.click(
      screen.getByRole("button", { name: /^6\s*Application Kit/ }),
    );
    expect(screen.getByTestId("kit-empty")).toHaveTextContent(/No kits yet/i);
  });

  it("'Build kit' calls useBuildApplicationKit.mutate with the form values", () => {
    render(<ReadinessScreen />);
    // Side-nav button — the one whose accessible name starts with "6 Application Kit".
    fireEvent.click(
      screen.getByRole("button", { name: /^6\s*Application Kit/ }),
    );
    const labelInput = screen.getByLabelText(/^Label$/i);
    fireEvent.change(labelInput, { target: { value: "Q2 sprint kit" } });
    fireEvent.click(screen.getByRole("button", { name: /^Build kit$/i }));
    expect(buildKitMutate).toHaveBeenCalledWith(
      expect.objectContaining({
        label: "Q2 sprint kit",
        target_role: "Python Developer",
      }),
      expect.anything(),
    );
    // Telemetry should have fired before the network call.
    expect(recordEventSpy).toHaveBeenCalledWith(
      "kit",
      "kit_build_started",
      expect.objectContaining({ components: expect.any(Array) }),
    );
  });

  it("download anchor uses the applicationKitDownloadUrl(id) format", () => {
    mockKitsList.mockReturnValue([
      {
        id: "kit-123",
        label: "Demo kit",
        target_role: "Python Developer",
        status: "ready",
        generated_at: new Date().toISOString(),
        created_at: new Date().toISOString(),
        manifest_keys: [],
      },
    ]);
    render(<ReadinessScreen />);
    // Side-nav button — the one whose accessible name starts with "6 Application Kit".
    fireEvent.click(
      screen.getByRole("button", { name: /^6\s*Application Kit/ }),
    );
    const link = screen.getByRole("link", { name: /Download/i });
    expect(link).toHaveAttribute(
      "href",
      "http://localhost:8000/api/v1/readiness/kit/kit-123/download",
    );
  });
});
