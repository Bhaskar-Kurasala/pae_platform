/**
 * Catalog screen — verifies the rewire to live data:
 *  - skeleton shows while loading
 *  - real titles + prices come from useCatalog payload (no static CARDS lies)
 *  - free courses render <FreeEnrollButton>; paid render <RazorpayCheckoutButton>
 *  - is_unlocked=true short-circuits to the disabled "✓ Enrolled" CTA
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";

import { CatalogScreen } from "@/components/v8/screens/catalog-screen";
import type {
  CatalogBundleResponse,
  CatalogCourseResponse,
  CatalogResponse,
} from "@/lib/api-client";

const mockCatalog = vi.fn();
const mockFreeEnroll = vi.fn();

vi.mock("@/lib/hooks/use-catalog", () => ({
  useCatalog: () => mockCatalog(),
}));

vi.mock("@/lib/hooks/use-payments", () => ({
  useFreeEnroll: () => mockFreeEnroll(),
}));

vi.mock("@/components/v8/v8-topbar-context", () => ({
  useSetV8Topbar: vi.fn(),
}));

vi.mock("@/components/v8/v8-toast", () => ({
  v8Toast: vi.fn(),
}));

vi.mock("@/stores/auth-store", () => ({
  useAuthStore: (selector?: (s: unknown) => unknown) => {
    const state = { isAuthenticated: true, user: { id: "u1" } };
    return selector ? selector(state) : state;
  },
}));

vi.mock("@/components/features/razorpay-checkout/checkout-button", () => ({
  RazorpayCheckoutButton: (props: {
    targetType: string;
    targetId: string;
    label: string;
  }) => (
    <button
      type="button"
      data-testid="razorpay-button"
      data-target-type={props.targetType}
      data-target-id={props.targetId}
    >
      {props.label}
    </button>
  ),
}));

vi.mock("@/components/features/razorpay-checkout/free-enroll-button", () => ({
  FreeEnrollButton: (props: { courseId: string; label: string }) => (
    <button
      type="button"
      data-testid="free-enroll-button"
      data-course-id={props.courseId}
    >
      {props.label}
    </button>
  ),
}));

function makeCourse(
  overrides: Partial<CatalogCourseResponse> = {},
): CatalogCourseResponse {
  return {
    id: "course-1",
    slug: "python-developer",
    title: "Python Developer",
    description: "Clean functions, async I/O, error handling.",
    price_cents: 0,
    currency: "USD",
    is_published: true,
    difficulty: "beginner",
    bullets: [
      { text: "6 lessons", included: true },
      { text: "18 labs", included: true },
    ],
    metadata: { lesson_count: 6, lab_count: 18 },
    is_unlocked: false,
    ...overrides,
  };
}

function makeBundle(
  overrides: Partial<CatalogBundleResponse> = {},
): CatalogBundleResponse {
  return {
    id: "bundle-1",
    slug: "career-arc",
    title: "Data Analyst → GenAI Engineer",
    description: "All four paid tracks in sequence.",
    price_cents: 50800,
    currency: "USD",
    course_ids: ["course-2", "course-3"],
    metadata: {},
    is_published: true,
    ...overrides,
  };
}

function setCatalog(data: CatalogResponse | undefined, opts: { isLoading?: boolean; error?: Error | null } = {}) {
  mockCatalog.mockReturnValue({
    data,
    isLoading: opts.isLoading ?? false,
    error: opts.error ?? null,
  });
}

describe("CatalogScreen", () => {
  beforeEach(() => {
    mockCatalog.mockReset();
    mockFreeEnroll.mockReset();
    mockFreeEnroll.mockReturnValue({
      mutate: vi.fn(),
      mutateAsync: vi.fn(),
      isPending: false,
    });
  });

  it("renders skeleton while loading", () => {
    setCatalog(undefined, { isLoading: true });
    render(<CatalogScreen />);
    const skeletons = screen.getAllByTestId("catalog-skeleton-card");
    expect(skeletons.length).toBe(5);
  });

  it("renders cards from real catalog data with correct titles and prices", () => {
    setCatalog({
      courses: [
        makeCourse({
          id: "c-paid",
          slug: "data-analyst",
          title: "Data Analyst",
          description: "SQL, pandas, dashboards.",
          price_cents: 12900,
          currency: "USD",
          difficulty: "intermediate",
        }),
      ],
      bundles: [makeBundle()],
    });
    render(<CatalogScreen />);
    expect(screen.getByRole("heading", { name: "Data Analyst" })).toBeInTheDocument();
    // Price: $129.00 — amt span gets the numeric portion.
    expect(screen.getByText("129.00")).toBeInTheDocument();
    // Bundle title + price.
    expect(
      screen.getByRole("heading", { name: "Data Analyst → GenAI Engineer" }),
    ).toBeInTheDocument();
    expect(screen.getByText("508.00")).toBeInTheDocument();
  });

  it("renders FreeEnrollButton for free courses and RazorpayCheckoutButton for paid", () => {
    setCatalog({
      courses: [
        makeCourse({
          id: "c-free",
          slug: "python-foundation",
          title: "Python Foundation",
          price_cents: 0,
        }),
        makeCourse({
          id: "c-paid",
          slug: "ml-engineer",
          title: "ML Engineer",
          price_cents: 24900,
        }),
      ],
      bundles: [],
    });
    render(<CatalogScreen />);
    const freeBtn = screen.getByTestId("free-enroll-button");
    expect(freeBtn).toHaveAttribute("data-course-id", "c-free");
    expect(freeBtn.textContent).toBe("Enroll free");

    const razorBtn = screen.getByTestId("razorpay-button");
    expect(razorBtn).toHaveAttribute("data-target-type", "course");
    expect(razorBtn).toHaveAttribute("data-target-id", "c-paid");
    expect(razorBtn.textContent).toBe("Unlock track");
  });

  it("shows '✓ Enrolled' (disabled) when course.is_unlocked is true", () => {
    setCatalog({
      courses: [
        makeCourse({
          id: "c-unlocked",
          title: "Already Mine",
          price_cents: 12900,
          is_unlocked: true,
        }),
      ],
      bundles: [],
    });
    render(<CatalogScreen />);
    const card = screen.getByRole("heading", { name: "Already Mine" }).closest("article");
    expect(card).not.toBeNull();
    const enrolled = within(card as HTMLElement).getByRole("button", {
      name: "✓ Enrolled",
    });
    expect(enrolled).toBeDisabled();
    // Neither of the action buttons should appear for unlocked courses.
    expect(within(card as HTMLElement).queryByTestId("free-enroll-button")).toBeNull();
    expect(within(card as HTMLElement).queryByTestId("razorpay-button")).toBeNull();
  });
});
