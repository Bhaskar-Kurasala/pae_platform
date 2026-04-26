/**
 * Payments-v2 hook tests — verify the instant-unlock seam:
 *  - useConfirmOrder onSuccess flips matching courses to is_unlocked=true
 *    in the ["catalog"] cache synchronously after the mutation resolves.
 *  - useFreeEnroll mirrors that optimistic update for the single course path.
 *  - useEntitlements derives the unlocked-set from the catalog cache.
 *
 * The api-client surface is mocked at the module level so no network I/O
 * runs and we can keep these as pure unit tests against the hooks themselves.
 */
import * as React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import {
  useConfirmOrder,
  useFreeEnroll,
} from "@/lib/hooks/use-payments";
import { useEntitlements } from "@/lib/hooks/use-entitlements";
import type {
  CatalogResponse,
  ConfirmOrderResponse,
  FreeEnrollResponse,
} from "@/lib/api-client";

const mockPaymentsApi = vi.hoisted(() => ({
  createOrder: vi.fn(),
  confirmOrder: vi.fn(),
  listOrders: vi.fn(),
  getOrder: vi.fn(),
  freeEnroll: vi.fn(),
  receiptUrl: vi.fn(),
}));

const mockCatalogApi = vi.hoisted(() => ({
  get: vi.fn(),
}));

vi.mock("@/lib/api-client", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/api-client")>(
      "@/lib/api-client",
    );
  return {
    ...actual,
    paymentsApi: mockPaymentsApi,
    catalogApi: mockCatalogApi,
  };
});

vi.mock("@/stores/auth-store", () => ({
  useAuthStore: (selector: (s: { isAuthenticated: boolean }) => unknown) =>
    selector({ isAuthenticated: true }),
}));

const COURSE_A = "11111111-1111-1111-1111-111111111111";
const COURSE_B = "22222222-2222-2222-2222-222222222222";

function makeCatalog(): CatalogResponse {
  return {
    courses: [
      {
        id: COURSE_A,
        slug: "course-a",
        title: "Course A",
        description: null,
        price_cents: 4900,
        currency: "INR",
        is_published: true,
        difficulty: "intermediate",
        bullets: [],
        metadata: {},
        is_unlocked: false,
      },
      {
        id: COURSE_B,
        slug: "course-b",
        title: "Course B",
        description: null,
        price_cents: 0,
        currency: "INR",
        is_published: true,
        difficulty: "beginner",
        bullets: [],
        metadata: {},
        is_unlocked: false,
      },
    ],
    bundles: [],
  };
}

function makeWrapper(qc: QueryClient) {
  const Wrapper = ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: qc }, children);
  return Wrapper;
}

function freshClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("useConfirmOrder", () => {
  it("flips is_unlocked=true on the granted course in the catalog cache", async () => {
    const qc = freshClient();
    qc.setQueryData<CatalogResponse>(["catalog"], makeCatalog());

    const confirmResponse: ConfirmOrderResponse = {
      order_id: "order-1",
      status: "paid",
      paid_at: "2026-04-26T10:00:00Z",
      fulfilled_at: "2026-04-26T10:00:01Z",
      entitlements_granted: [COURSE_A],
    };
    mockPaymentsApi.confirmOrder.mockResolvedValueOnce(confirmResponse);

    const { result } = renderHook(() => useConfirmOrder(), {
      wrapper: makeWrapper(qc),
    });

    result.current.mutate({
      orderId: "order-1",
      body: {
        razorpay_order_id: "rzp_o_1",
        razorpay_payment_id: "rzp_p_1",
        razorpay_signature: "sig",
      },
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const cached = qc.getQueryData<CatalogResponse>(["catalog"]);
    expect(cached).toBeDefined();
    const courseA = cached!.courses.find((c) => c.id === COURSE_A);
    const courseB = cached!.courses.find((c) => c.id === COURSE_B);
    expect(courseA?.is_unlocked).toBe(true);
    // Untouched courses stay locked.
    expect(courseB?.is_unlocked).toBe(false);
  });
});

describe("useFreeEnroll", () => {
  it("flips is_unlocked=true on the enrolled course in the catalog cache", async () => {
    const qc = freshClient();
    qc.setQueryData<CatalogResponse>(["catalog"], makeCatalog());

    const enrollResponse: FreeEnrollResponse = {
      course_id: COURSE_B,
      entitlement_id: "ent-1",
      granted_at: "2026-04-26T10:05:00Z",
    };
    mockPaymentsApi.freeEnroll.mockResolvedValueOnce(enrollResponse);

    const { result } = renderHook(() => useFreeEnroll(), {
      wrapper: makeWrapper(qc),
    });

    result.current.mutate({ course_id: COURSE_B });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const cached = qc.getQueryData<CatalogResponse>(["catalog"]);
    expect(cached).toBeDefined();
    const courseA = cached!.courses.find((c) => c.id === COURSE_A);
    const courseB = cached!.courses.find((c) => c.id === COURSE_B);
    expect(courseB?.is_unlocked).toBe(true);
    expect(courseA?.is_unlocked).toBe(false);
  });
});

describe("useEntitlements", () => {
  it("derives the entitled-course set from the catalog response", async () => {
    const qc = freshClient();
    const catalog = makeCatalog();
    catalog.courses[0].is_unlocked = true; // Course A is unlocked
    mockCatalogApi.get.mockResolvedValueOnce(catalog);

    const { result } = renderHook(() => useEntitlements(), {
      wrapper: makeWrapper(qc),
    });

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.entitledCourseIds.has(COURSE_A)).toBe(true);
    expect(result.current.entitledCourseIds.has(COURSE_B)).toBe(false);
    expect(result.current.entitledCourseIds.size).toBe(1);
  });
});
