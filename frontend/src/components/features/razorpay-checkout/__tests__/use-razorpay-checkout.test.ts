import { act, renderHook, waitFor } from "@testing-library/react";
import {
  beforeEach,
  describe,
  expect,
  it,
  vi,
  type Mock,
} from "vitest";

const {
  createOrderMutate,
  confirmOrderMutate,
  loadRazorpayScriptMock,
  v8ToastMock,
} = vi.hoisted(() => ({
  createOrderMutate: vi.fn(),
  confirmOrderMutate: vi.fn(),
  loadRazorpayScriptMock: vi.fn(),
  v8ToastMock: vi.fn(),
}));

vi.mock("@/lib/hooks/use-payments", () => ({
  useCreateOrder: () => ({ mutateAsync: createOrderMutate }),
  useConfirmOrder: () => ({ mutateAsync: confirmOrderMutate }),
  useFreeEnroll: () => ({ mutateAsync: vi.fn() }),
}));

vi.mock("../load-script", () => ({
  loadRazorpayScript: loadRazorpayScriptMock,
  isRazorpayReadyOnClient: () => true,
}));

vi.mock("@/components/v8/v8-toast", () => ({
  v8Toast: v8ToastMock,
}));

import { useRazorpayCheckout } from "../use-razorpay-checkout";

interface RazorpayHandlerResponse {
  razorpay_order_id: string;
  razorpay_payment_id: string;
  razorpay_signature: string;
}

interface RazorpayOptions {
  handler: (resp: RazorpayHandlerResponse) => void;
  modal: { ondismiss: () => void };
  order_id: string;
}

interface MockRazorpayInstance {
  open: Mock;
  on: Mock;
  options: RazorpayOptions;
}

beforeEach(() => {
  createOrderMutate.mockReset();
  confirmOrderMutate.mockReset();
  loadRazorpayScriptMock.mockReset();
  v8ToastMock.mockReset();
  delete (globalThis as { Razorpay?: unknown }).Razorpay;
});

describe("useRazorpayCheckout — mock path", () => {
  it("skips loadRazorpayScript and immediately confirms with a valid signature", async () => {
    createOrderMutate.mockResolvedValue({
      order_id: "ord_local_1",
      provider: "mock",
      provider_order_id: "mock_order_abc",
      amount_cents: 4900,
      currency: "INR",
      receipt_number: "RCP-1",
      razorpay_key_id: null,
      user_email: "u@example.com",
      user_name: "U",
      target_title: "Course",
    });
    confirmOrderMutate.mockResolvedValue({
      order_id: "ord_local_1",
      status: "paid",
      paid_at: "2026-04-26T00:00:00Z",
      fulfilled_at: "2026-04-26T00:00:00Z",
      entitlements_granted: ["course-uuid-1", "course-uuid-2"],
    });

    const onSuccess = vi.fn();
    const { result } = renderHook(() => useRazorpayCheckout());

    await act(async () => {
      await result.current.startCheckout({
        targetType: "course",
        targetId: "course-uuid-1",
        onSuccess,
      });
    });

    expect(loadRazorpayScriptMock).not.toHaveBeenCalled();
    expect(confirmOrderMutate).toHaveBeenCalledTimes(1);

    const confirmCall = confirmOrderMutate.mock.calls[0][0];
    expect(confirmCall.orderId).toBe("ord_local_1");
    expect(confirmCall.body.razorpay_order_id).toBe("mock_order_abc");
    expect(confirmCall.body.razorpay_payment_id).toMatch(/^mock_pay_/);
    expect(confirmCall.body.razorpay_signature).toMatch(/^[0-9a-f]{64}$/);

    expect(onSuccess).toHaveBeenCalledWith(["course-uuid-1", "course-uuid-2"]);
    expect(v8ToastMock).toHaveBeenCalledWith("Demo mode payment captured");
    expect(result.current.isWorking).toBe(false);
    expect(result.current.lastError).toBeNull();
  });
});

describe("useRazorpayCheckout — real path", () => {
  it("loads the script, opens Razorpay, and runs the handler through confirm", async () => {
    createOrderMutate.mockResolvedValue({
      order_id: "ord_real_1",
      provider: "razorpay",
      provider_order_id: "order_RZ123",
      amount_cents: 9900,
      currency: "INR",
      receipt_number: "RCP-2",
      razorpay_key_id: "rzp_test_key",
      user_email: "u@example.com",
      user_name: "U",
      target_title: "Bundle",
    });
    confirmOrderMutate.mockResolvedValue({
      order_id: "ord_real_1",
      status: "paid",
      paid_at: "2026-04-26T00:00:00Z",
      fulfilled_at: "2026-04-26T00:00:00Z",
      entitlements_granted: ["course-A", "course-B"],
    });
    loadRazorpayScriptMock.mockResolvedValue(true);

    const instances: MockRazorpayInstance[] = [];
    class FakeRazorpay {
      options: RazorpayOptions;
      open: Mock;
      on: Mock;
      constructor(options: RazorpayOptions) {
        this.options = options;
        this.open = vi.fn(() => {
          // Razorpay invokes handler when the user pays.
          options.handler({
            razorpay_order_id: options.order_id,
            razorpay_payment_id: "pay_real_1",
            razorpay_signature: "sig_real_1",
          });
        });
        this.on = vi.fn();
        instances.push(this);
      }
    }
    (globalThis as { Razorpay?: unknown }).Razorpay = FakeRazorpay;

    const onSuccess = vi.fn();
    const { result } = renderHook(() => useRazorpayCheckout());

    await act(async () => {
      await result.current.startCheckout({
        targetType: "bundle",
        targetId: "bundle-1",
        onSuccess,
      });
    });

    expect(loadRazorpayScriptMock).toHaveBeenCalledTimes(1);
    expect(instances).toHaveLength(1);
    const captured = instances[0];
    expect(captured.open).toHaveBeenCalledTimes(1);
    expect(captured.on).toHaveBeenCalledWith(
      "payment.failed",
      expect.any(Function),
    );

    await waitFor(() => {
      expect(confirmOrderMutate).toHaveBeenCalledTimes(1);
    });
    const confirmCall = confirmOrderMutate.mock.calls[0][0];
    expect(confirmCall.orderId).toBe("ord_real_1");
    expect(confirmCall.body).toEqual({
      razorpay_order_id: "order_RZ123",
      razorpay_payment_id: "pay_real_1",
      razorpay_signature: "sig_real_1",
    });

    await waitFor(() => {
      expect(onSuccess).toHaveBeenCalledWith(["course-A", "course-B"]);
    });
  });
});

describe("useRazorpayCheckout — confirm failure", () => {
  it("calls onError when confirm rejects in mock mode", async () => {
    createOrderMutate.mockResolvedValue({
      order_id: "ord_local_2",
      provider: "mock",
      provider_order_id: "mock_order_xyz",
      amount_cents: 1000,
      currency: "INR",
      receipt_number: "RCP-3",
      razorpay_key_id: null,
      user_email: "u@example.com",
      user_name: "U",
      target_title: "Course",
    });
    const boom = new Error("Signature mismatch");
    confirmOrderMutate.mockRejectedValue(boom);

    const onError = vi.fn();
    const onSuccess = vi.fn();
    const { result } = renderHook(() => useRazorpayCheckout());

    await act(async () => {
      await result.current.startCheckout({
        targetType: "course",
        targetId: "course-uuid-9",
        onSuccess,
        onError,
      });
    });

    expect(onSuccess).not.toHaveBeenCalled();
    expect(onError).toHaveBeenCalledWith(boom);
    expect(result.current.lastError).toBe("Signature mismatch");
    expect(result.current.isWorking).toBe(false);
  });
});
