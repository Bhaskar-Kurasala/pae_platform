/**
 * Notebook screen — verifies the rewire to live data:
 *  - the FALLBACK_NOTES static lies are gone
 *  - eyebrow says "Graduated · …" when graduated_at is set, "In review · …" when null
 *  - ghost count comes from notebook summary (notes still in review), not all SRS due cards
 *  - filter chips swap the visible entries
 *  - empty-state copy adapts to the active filter
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { NotebookScreen } from "@/components/v8/screens/notebook-screen";
import type {
  NotebookEntryOut,
  NotebookSummaryResponse,
} from "@/lib/chat-api";

const mockEntries = vi.fn();
const mockSummary = vi.fn();
const mockDueCards = vi.fn();

vi.mock("@/lib/hooks/use-notebook", () => ({
  useNotebookEntries: (opts: unknown) => mockEntries(opts),
  useNotebookSummary: () => mockSummary(),
}));

vi.mock("@/lib/hooks/use-srs", () => ({
  useDueCards: () => mockDueCards(),
}));

vi.mock("@/components/v8/v8-topbar-context", () => ({
  useSetV8Topbar: vi.fn(),
}));

vi.mock("@/stores/auth-store", () => ({
  useAuthStore: (selector?: (s: unknown) => unknown) => {
    const state = { isAuthenticated: true };
    return selector ? selector(state) : state;
  },
}));

function makeEntry(overrides: Partial<NotebookEntryOut> = {}): NotebookEntryOut {
  return {
    id: "e1",
    message_id: "m1",
    conversation_id: "c1",
    content: "Type hints make Python feel like a contract with future-me.",
    title: "Type hints",
    user_note: null,
    source_type: "chat",
    topic: "Python",
    tags: [],
    last_reviewed_at: null,
    graduated_at: null,
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

function makeSummary(
  overrides: Partial<NotebookSummaryResponse> = {},
): NotebookSummaryResponse {
  return {
    total: 5,
    graduated: 2,
    in_review: 3,
    graduation_percentage: 40,
    latest_graduated_at: new Date().toISOString(),
    by_source: [
      { source: "chat", count: 4 },
      { source: "quiz", count: 1 },
    ],
    tags: ["python"],
    ...overrides,
  };
}

describe("NotebookScreen", () => {
  beforeEach(() => {
    mockEntries.mockReset();
    mockSummary.mockReset();
    mockDueCards.mockReset();
    mockDueCards.mockReturnValue({ data: [] });
  });

  it("renders entries from the API and labels graduated vs in-review correctly", () => {
    mockEntries.mockReturnValue({
      data: [
        makeEntry({
          id: "g1",
          title: "Async basics",
          topic: "Async",
          graduated_at: new Date().toISOString(),
        }),
        makeEntry({ id: "r1", title: "Decorators", topic: "Decorators" }),
      ],
      isLoading: false,
    });
    mockSummary.mockReturnValue({ data: makeSummary() });

    render(<NotebookScreen />);
    expect(screen.getByText(/Graduated · Chat · Async/)).toBeInTheDocument();
    expect(screen.getByText(/In review · Chat · Decorators/)).toBeInTheDocument();
  });

  it("shows the ghost count from notebook summary, not from total SRS due cards", () => {
    mockEntries.mockReturnValue({ data: [], isLoading: false });
    mockSummary.mockReturnValue({ data: makeSummary({ in_review: 7 }) });
    mockDueCards.mockReturnValue({ data: new Array(50).fill({}) });

    render(<NotebookScreen />);
    // Ghost card uses notebook in_review (7), not 50 from SRS.
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.getByText(/notes still in review/i)).toBeInTheDocument();
  });

  it("switches visible entries when a filter chip is clicked", () => {
    mockEntries.mockImplementation((opts: { graduated?: string }) => {
      if (opts.graduated === "graduated") {
        return {
          data: [
            makeEntry({
              id: "g1",
              title: "Closures",
              topic: "Closures",
              graduated_at: new Date().toISOString(),
            }),
          ],
          isLoading: false,
        };
      }
      return {
        data: [
          makeEntry({ id: "g1", title: "Closures", topic: "Closures", graduated_at: new Date().toISOString() }),
          makeEntry({ id: "r1", title: "Generators", topic: "Generators" }),
        ],
        isLoading: false,
      };
    });
    mockSummary.mockReturnValue({ data: makeSummary() });

    render(<NotebookScreen />);
    expect(screen.getByText(/Generators/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^Graduated$/ }));
    // After re-query the in-review entry should not be present.
    expect(screen.queryByText(/Generators/)).not.toBeInTheDocument();
    expect(screen.getByText(/Closures/)).toBeInTheDocument();
  });

  it("renders an empty-state hint matching the active filter", () => {
    mockEntries.mockReturnValue({ data: [], isLoading: false });
    mockSummary.mockReturnValue({ data: makeSummary({ total: 0, graduated: 0, in_review: 0 }) });
    render(<NotebookScreen />);
    expect(
      screen.getByText(/Bookmark an assistant reply/i),
    ).toBeInTheDocument();
  });
});
