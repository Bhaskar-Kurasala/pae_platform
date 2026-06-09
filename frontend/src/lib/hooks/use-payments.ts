"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  paymentsApi,
  type CatalogResponse,
  type ConfirmOrderRequest,
  type ConfirmOrderResponse,
  type CreateOrderRequest,
  type CreateOrderResponse,
  type FreeEnrollRequest,
  type FreeEnrollResponse,
  type OrderDetailResponse,
  type OrderListItem,
} from "@/lib/api-client";
import { useAuthStore } from "@/stores/auth-store";

export function useOrders() {
  const isAuthed = useAuthStore((s) => s.isAuthenticated);
  return useQuery<OrderListItem[]>({
    queryKey: ["payments", "orders"],
    queryFn: () => paymentsApi.listOrders(),
    enabled: isAuthed,
    staleTime: 30_000,
  });
}

export function useOrder(id: string | null) {
  const isAuthed = useAuthStore((s) => s.isAuthenticated);
  return useQuery<OrderDetailResponse>({
    queryKey: ["payments", "orders", id],
    queryFn: () => {
      // `enabled` keeps this from firing when id is null; the cast is safe.
      return paymentsApi.getOrder(id as string);
    },
    enabled: isAuthed && !!id,
    staleTime: 15_000,
  });
}

export function useCreateOrder() {
  // No cache invalidation: the order is unfulfilled until confirm fires.
  return useMutation<CreateOrderResponse, Error, CreateOrderRequest>({
    mutationFn: (body) => paymentsApi.createOrder(body),
  });
}

interface ConfirmOrderVars {
  orderId: string;
  body: ConfirmOrderRequest;
}

/**
 * Instant-unlock seam. On success, optimistically flips the matching courses
 * in the catalog cache to `is_unlocked=true` so the UI updates immediately
 * without waiting on a refetch. The orders list is invalidated so the order
 * status reflects the just-paid state.
 */
export function useConfirmOrder() {
  const qc = useQueryClient();
  return useMutation<ConfirmOrderResponse, Error, ConfirmOrderVars>({
    mutationFn: ({ orderId, body }) =>
      paymentsApi.confirmOrder(orderId, body),
    onSuccess: (data) => {
      qc.setQueryData<CatalogResponse>(["catalog"], (prev) => {
        if (!prev) return prev;
        const unlocked = new Set(data.entitlements_granted);
        return {
          ...prev,
          courses: prev.courses.map((c) =>
            unlocked.has(c.id) ? { ...c, is_unlocked: true } : c,
          ),
        };
      });
      qc.invalidateQueries({ queryKey: ["payments", "orders"] });
    },
  });
}

/**
 * Free enrollment for $0 courses. Same optimistic pattern as confirm-order:
 * flip the matching course to `is_unlocked=true` in the catalog cache so the
 * UI updates synchronously.
 */
export function useFreeEnroll() {
  const qc = useQueryClient();
  return useMutation<FreeEnrollResponse, Error, FreeEnrollRequest>({
    mutationFn: (body) => paymentsApi.freeEnroll(body),
    onSuccess: (data) => {
      qc.setQueryData<CatalogResponse>(["catalog"], (prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          courses: prev.courses.map((c) =>
            c.id === data.course_id ? { ...c, is_unlocked: true } : c,
          ),
        };
      });
    },
  });
}
