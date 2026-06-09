/**
 * DEV-ONLY shortcut so the catalog flow demos end-to-end without a real
 * Razorpay account.
 *
 * The backend's MockProvider activates when no `RAZORPAY_KEY_ID` is configured
 * and verifies HMAC-SHA256(`{order_id}|{payment_id}`, `dev-mock-secret-…`).
 * To exercise the real /confirm endpoint from a dev frontend we reproduce
 * that signature client-side. In production, the Razorpay modal handler
 * always returns a real signature and this helper is never invoked.
 *
 * The shared secret below is the published dev secret — it has zero security
 * value; the backend rejects this signature whenever the real Razorpay
 * provider is active.
 */

export const MOCK_SIGNATURE_SECRET = "dev-mock-secret-not-for-production";

function toHex(bytes: ArrayBuffer): string {
  const view = new Uint8Array(bytes);
  let out = "";
  for (let i = 0; i < view.length; i += 1) {
    out += view[i].toString(16).padStart(2, "0");
  }
  return out;
}

export async function signMockPayment(
  orderId: string,
  paymentId: string,
): Promise<string> {
  const subtle = globalThis.crypto?.subtle;
  if (!subtle) {
    throw new Error(
      "WebCrypto SubtleCrypto is unavailable; cannot sign mock payment.",
    );
  }
  const enc = new TextEncoder();
  const key = await subtle.importKey(
    "raw",
    enc.encode(MOCK_SIGNATURE_SECRET),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signature = await subtle.sign(
    "HMAC",
    key,
    enc.encode(`${orderId}|${paymentId}`),
  );
  return toHex(signature);
}
