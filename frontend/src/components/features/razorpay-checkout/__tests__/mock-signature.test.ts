import { createHmac } from "node:crypto";
import { describe, expect, it } from "vitest";

import {
  MOCK_SIGNATURE_SECRET,
  signMockPayment,
} from "../mock-signature";

function expectedSignature(orderId: string, paymentId: string): string {
  return createHmac("sha256", MOCK_SIGNATURE_SECRET)
    .update(`${orderId}|${paymentId}`)
    .digest("hex");
}

describe("signMockPayment", () => {
  it("matches the canonical Node HMAC-SHA256 of order|payment", async () => {
    const orderId = "order_X";
    const paymentId = "pay_Y";
    const got = await signMockPayment(orderId, paymentId);
    expect(got).toBe(expectedSignature(orderId, paymentId));
  });

  it("produces a 64-char lowercase hex string", async () => {
    const sig = await signMockPayment("order_abc", "pay_def");
    expect(sig).toMatch(/^[0-9a-f]{64}$/);
  });

  it("changes deterministically with payment id", async () => {
    const a = await signMockPayment("order_1", "pay_a");
    const b = await signMockPayment("order_1", "pay_b");
    expect(a).not.toBe(b);
    expect(a).toBe(expectedSignature("order_1", "pay_a"));
    expect(b).toBe(expectedSignature("order_1", "pay_b"));
  });
});
