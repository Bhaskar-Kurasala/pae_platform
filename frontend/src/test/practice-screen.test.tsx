/**
 * Practice screen (P-Practice1) — verifies the merged Exercises/Capstone
 * surface:
 *
 *  - mode toggle wires the URL search params
 *  - Capstone mode renders the file tree from path/summary labs
 *  - Exercises mode renders the catalog grouped by difficulty
 *  - selecting an exercise pre-seeds the Monaco editor with starter_code
 *  - "Run & review" calls executeApi.run AND seniorReview.mutate with
 *    problemContext derived from the active task
 *  - "Save to Notebook" opens the dialog, accepts a note, and POSTs
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  cleanup,
} from "@testing-library/react";

import { PracticeScreen } from "@/components/v8/screens/practice-screen";

// ── Mocks ───────────────────────────────────────────────────────────
const mockReplace = vi.fn();
const mockPush = vi.fn();
const mockSearchParams = new URLSearchParams("");

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockReplace, push: mockPush }),
  useSearchParams: () => mockSearchParams,
}));

vi.mock("next-themes", () => ({
  useTheme: () => ({ resolvedTheme: "light" }),
}));

// The real Monaco component pulls in browser-only modules. Replace it with
// a textarea so tests can read/write the code state.
vi.mock("@monaco-editor/react", () => ({
  default: ({
    value,
    onChange,
  }: {
    value: string;
    onChange: (v: string | undefined) => void;
  }) => (
    <textarea
      data-testid="monaco-stub"
      value={value}
      onChange={(e) => onChange(e.target.value)}
    />
  ),
}));

vi.mock("@/components/v8/v8-topbar-context", () => ({
  useSetV8Topbar: vi.fn(),
}));

const mockToast = vi.fn();
vi.mock("@/components/v8/v8-toast", () => ({
  v8Toast: (...args: unknown[]) => mockToast(...args),
}));

const mockSeniorReviewMutate = vi.fn();
vi.mock("@/lib/hooks/use-senior-review", () => ({
  useSeniorReview: () => ({
    mutate: mockSeniorReviewMutate,
    data: undefined,
    isPending: false,
    isError: false,
  }),
}));

const mockUseWorkspace = vi.fn();
vi.mock("@/lib/hooks/use-practice-workspace", () => ({
  usePracticeWorkspace: () => mockUseWorkspace(),
}));

const mockExecuteRun = vi.fn();
const mockExerciseGet = vi.fn();
vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>(
    "@/lib/api-client",
  );
  return {
    ...actual,
    executeApi: { run: (...args: unknown[]) => mockExecuteRun(...args) },
    exercisesApi: {
      ...actual.exercisesApi,
      get: (...args: unknown[]) => mockExerciseGet(...args),
    },
  };
});

const mockSaveNotebook = vi.fn();
vi.mock("@/lib/chat-api", () => ({
  chatApi: {
    saveToNotebook: (...args: unknown[]) => mockSaveNotebook(...args),
  },
}));

vi.mock("@/stores/auth-store", () => ({
  useAuthStore: (selector: (s: { isAuthenticated: boolean }) => unknown) =>
    selector({ isAuthenticated: true }),
}));

// ── Helpers ─────────────────────────────────────────────────────────

function defaultWorkspace() {
  return {
    isAuthed: true,
    isLoading: false,
    error: null,
    exercises: [
      {
        id: "ex-1",
        title: "Retry with backoff",
        description: "Retry a flaky API call.",
        difficulty: "intermediate",
        points: 50,
        order: 0,
        starter_code: "# starter\ndef call(): pass\n",
        is_capstone: false,
        pass_score: 70,
        due_at: null,
        created_at: "2026-04-28T00:00:00Z",
      },
      {
        id: "ex-2",
        title: "Hello world",
        description: "First exercise.",
        difficulty: "beginner",
        points: 10,
        order: 1,
        starter_code: "print('hi')\n",
        is_capstone: false,
        pass_score: 70,
        due_at: null,
        created_at: "2026-04-28T00:00:00Z",
      },
    ],
    capstone: {
      title: "CLI AI Tool",
      blurb: "Build a CLI greeter.",
      labs: [
        {
          id: "lab-a",
          title: "main.py",
          description: "Entry point",
          duration_minutes: 30,
          status: "current",
        },
        {
          id: "lab-b",
          title: "retry.py",
          description: "Retry helper",
          duration_minutes: 20,
          status: "locked",
        },
      ],
      primaryLabId: "lab-a",
    },
    activeCourseTitle: "Python Foundations",
  };
}

beforeEach(() => {
  mockReplace.mockReset();
  mockPush.mockReset();
  mockSeniorReviewMutate.mockReset();
  mockExecuteRun.mockReset();
  mockExerciseGet.mockReset();
  mockSaveNotebook.mockReset();
  mockToast.mockReset();
  // Reset URL params to default.
  for (const key of Array.from(mockSearchParams.keys())) {
    mockSearchParams.delete(key);
  }
  mockUseWorkspace.mockReturnValue(defaultWorkspace());
});

afterEach(() => {
  cleanup();
});

// ── Tests ───────────────────────────────────────────────────────────

describe("PracticeScreen", () => {
  it("defaults to capstone mode and renders the file tree", () => {
    render(<PracticeScreen />);
    expect(screen.getByTestId("capstone-rail")).toBeInTheDocument();
    // Two `main.py` strings exist (rail tree + editor tab); we assert via
    // the rail-scoped data-testid so we're testing structure, not text.
    expect(screen.getByTestId("capstone-lab-lab-a")).toHaveTextContent(
      "main.py",
    );
    expect(screen.getByTestId("capstone-lab-lab-b")).toHaveTextContent(
      "retry.py",
    );
  });

  it("switches to exercises mode and lists exercises grouped by difficulty", () => {
    render(<PracticeScreen />);
    fireEvent.click(screen.getByTestId("mode-exercises"));
    expect(screen.getByTestId("exercise-rail")).toBeInTheDocument();
    expect(screen.getByText("Retry with backoff")).toBeInTheDocument();
    expect(screen.getByText("Hello world")).toBeInTheDocument();
    // Mode toggle pushed mode=exercises into the URL.
    expect(mockReplace).toHaveBeenCalledWith(
      expect.stringContaining("mode=exercises"),
    );
  });

  it("seeds the Monaco editor with starter_code when an exercise is selected", async () => {
    mockExerciseGet.mockResolvedValue({
      id: "ex-1",
      title: "Retry with backoff",
      description: "Retry a flaky API call.",
      difficulty: "intermediate",
      points: 50,
      order: 0,
      starter_code: "# starter\ndef call(): pass\n",
      is_capstone: false,
      pass_score: 70,
      due_at: null,
      created_at: "2026-04-28T00:00:00Z",
    });
    render(<PracticeScreen />);
    fireEvent.click(screen.getByTestId("mode-exercises"));
    fireEvent.click(screen.getByTestId("exercise-task-ex-1"));
    await waitFor(() => {
      expect(mockExerciseGet).toHaveBeenCalledWith("ex-1");
    });
    await waitFor(() => {
      const ta = screen.getByTestId("monaco-stub") as HTMLTextAreaElement;
      expect(ta.value).toContain("# starter");
    });
  });

  it("Run & review calls execute then senior review with capstone problem context", async () => {
    mockExecuteRun.mockResolvedValue({
      stdout: "ok",
      stderr: "",
      exit_code: 0,
      timed_out: false,
      error: null,
      events: [],
      quality: { issues: [], score: 90, summary: "clean" },
    });
    render(<PracticeScreen />);
    fireEvent.click(screen.getByTestId("run-and-review"));
    await waitFor(() => {
      expect(mockExecuteRun).toHaveBeenCalled();
    });
    await waitFor(() => {
      expect(mockSeniorReviewMutate).toHaveBeenCalledWith(
        expect.objectContaining({
          problemContext: expect.stringContaining("Capstone: CLI AI Tool"),
        }),
      );
    });
  });

  it("Save dialog opens, accepts a note, and POSTs to notebook", async () => {
    mockSaveNotebook.mockResolvedValue({ id: "n-1" });
    render(<PracticeScreen />);
    fireEvent.click(screen.getByTestId("save-to-notebook"));
    expect(screen.getByTestId("save-dialog")).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("save-note-input"), {
      target: { value: "remember exponential backoff" },
    });
    fireEvent.click(screen.getByTestId("save-confirm"));
    await waitFor(() => {
      expect(mockSaveNotebook).toHaveBeenCalledWith(
        expect.objectContaining({
          userNote: "remember exponential backoff",
          sourceType: "studio",
          tags: ["capstone"],
        }),
      );
    });
  });

  it("falls back to a friendly empty state when the capstone has no labs", () => {
    mockUseWorkspace.mockReturnValue({
      ...defaultWorkspace(),
      capstone: null,
    });
    render(<PracticeScreen />);
    expect(screen.getByText(/No capstone yet/i)).toBeInTheDocument();
  });

  it("Request review only fires senior review without running code", async () => {
    render(<PracticeScreen />);
    fireEvent.click(screen.getByTestId("request-review"));
    await waitFor(() => {
      expect(mockSeniorReviewMutate).toHaveBeenCalled();
    });
    expect(mockExecuteRun).not.toHaveBeenCalled();
  });
});
