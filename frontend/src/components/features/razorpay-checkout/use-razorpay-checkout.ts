"use client";

import { useCallback, useRef, useState } from "react";

import {
  useConfirmOrder,
  useCreateOrder,
} from "@/lib/hooks/use-payments";
import { v8Toast } from "@/components/v8/v8-toast";
import type {
  ConfirmOrderResponse,
  CreateOrderResponse,
} from "@/lib/api-client";

import { loadRazorpayScript } from "./load-script";
import { signMockPayment } from "./mock-signature";

export interface StartCheckoutOpts {
  targetType: "course" | "bundle";
  targetId: string;
  onSuccess?: (entitlementCourseIds: string[]) => void;
  onCancel?: () => void;
  onError?: (err: Error) => void;
}

export interface UseRazorpayCheckoutResult {
  startCheckout: (opts: StartCheckoutOpts) => Promise<void>;
  isWorking: boolean;
  lastError: string | null;
}

interface RazorpayHandlerResponse {
  razorpay_order_id: string;
  razorpay_payment_id: string;
  razorpay_signature: string;
}

interface RazorpayOptions {
  key: string;
  amount: number;
  currency: string;
  name: string;
  description: string;
  order_id: string;
  prefill: { email: string; name: string };
  theme: { color: string };
  handler: (response: RazorpayHandlerResponse) => void;
  modal: { ondismiss: () => void };
}

interface RazorpayInstance {
  open: () => void;
  on: (event: string, cb: (resp: unknown) => void) => void;
}

interface RazorpayConstructor {
  new (options: RazorpayOptions): RazorpayInstance;
}

interface RazorpayWindow {
  Razorpay?: RazorpayConstructor;
}

function getRazorpayCtor(): RazorpayConstructor | undefined {
  if (typeof window === "undefined") return undefined;
  return (window as unknown as RazorpayWindow).Razorpay;
}

function isMockOrder(order: CreateOrderResponse): boolean {
  return (
    order.razorpay_key_id === null ||
    order.provider_order_id.startsWith("mock_order_")
  );
}

function newMockPaymentId(): string {
  // crypto.randomUUID is available in modern browsers and Node 19+.
  const uuid =
    typeof globalThis.crypto?.randomUUID === "function"
      ? globalThis.crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `mock_pay_${uuid.replace(/-/g, "").slice(0, 12)}`;
}

export function useRazorpayCheckout(): UseRazorpayCheckoutResult {
  const createOrder = useCreateOrder();
  const confirmOrder = useConfirmOrder();
  const [isWorking, setIsWorking] = useState(false);
  const [lastError, setLastError] = useState<string | null>(null);

  // Guard against re-entrant clicks while a checkout is mid-flight.
  const inflight = useRef(false);

  const startCheckout = useCallback(
    async (opts: StartCheckoutOpts): Promise<void> => {
      if (inflight.current) return;
      inflight.current = true;
      setIsWorking(true);
      setLastError(null);

      const fail = (err: Error) => {
        setLastError(err.message);
        opts.onError?.(err);
      };

      const finish = () => {
        inflight.current = false;
        setIsWorking(false);
      };

      let order: CreateOrderResponse;
      try {
        order = await createOrder.mutateAsync({
          target_type: opts.targetType,
          target_id: opts.targetId,
          provider: "razorpay",
        });
      } catch (err) {
        fail(err instanceof Error ? err : new Error("Failed to create order"));
        finish();
        return;
      }

      // ── Mock path ──────────────────────────────────────────────
      if (isMockOrder(order)) {
        try {
          const paymentId = newMockPaymentId();
          const signature = await signMockPayment(
            order.provider_order_id,
            paymentId,
          );
          const result: ConfirmOrderResponse =
            await confirmOrder.mutateAsync({
              orderId: order.order_id,
              body: {
                razorpay_order_id: order.provider_order_id,
                razorpay_payment_id: paymentId,
                razorpay_signature: signature,
              },
            });
          v8Toast("Demo mode payment captured");
          opts.onSuccess?.(result.entitlements_granted);
        } catch (err) {
          fail(
            err instanceof Error
              ? err
              : new Error("Mock checkout confirm failed"),
          );
        } finally {
          finish();
        }
        return;
      }

      // ── Real Razorpay path ─────────────────────────────────────
      const loaded = await loadRazorpayScript();
      if (!loaded) {
        fail(new Error("Razorpay failed to load."));
        finish();
        return;
      }

      const Ctor = getRazorpayCtor();
      if (!Ctor) {
        fail(new Error("Razorpay failed to load."));
        finish();
        return;
      }

      // Razorpay returns a real key when not in mock mode; this cast is safe.
      const keyId = order.razorpay_key_id as string;

      try {
        const options: RazorpayOptions = {
          key: keyId,
          amount: order.amount_cents,
          currency: order.currency,
          name: "CareerForge",
          description: order.target_title,
          order_id: order.provider_order_id,
          prefill: { email: order.user_email, name: order.user_name },
          theme: { color: "#1D9E75" },
          handler: (response) => {
            void (async () => {
              try {
                const result = await confirmOrder.mutateAsync({
                  orderId: order.order_id,
                  body: {
                    razorpay_order_id: response.razorpay_order_id,
                    razorpay_payment_id: response.razorpay_payment_id,
                    razorpay_signature: response.razorpay_signature,
                  },
                });
                opts.onSuccess?.(result.entitlements_granted);
              } catch (err) {
                fail(
                  err instanceof Error
                    ? err
                    : new Error("Order confirmation failed"),
                );
              } finally {
                finish();
              }
            })();
          },
          modal: {
            ondismiss: () => {
              opts.onCancel?.();
              finish();
            },
          },
        };

        const rzp = new Ctor(options);
        rzp.on("payment.failed", () => {
          fail(new Error("Payment failed"));
          finish();
        });
        rzp.open();
        // Hand control to the Razorpay modal; flip isWorking off so the CTA
        // is interactive again if the user dismisses without paying.
        setIsWorking(false);
      } catch (err) {
        fail(
          err instanceof Error ? err : new Error("Could not open Razorpay"),
        );
        finish();
      }
    },
    [createOrder, confirmOrder],
  );

  return { startCheckout, isWorking, lastError };
}
