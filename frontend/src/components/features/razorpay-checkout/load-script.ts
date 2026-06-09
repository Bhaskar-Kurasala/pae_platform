/**
 * Idempotent loader for the hosted Razorpay checkout script.
 *
 * The script tag is appended once; concurrent callers share a cached promise,
 * so we never get duplicate <script> tags or duplicate network fetches even
 * when a fast user clicks several "Buy" CTAs in a row.
 *
 * SSR-safe: returns false synchronously when there's no `window` (Next.js
 * server render path).
 */

export const RAZORPAY_SCRIPT_URL =
  "https://checkout.razorpay.com/v1/checkout.js";
const RAZORPAY_SCRIPT_ID = "razorpay-checkout-js";

let inflight: Promise<boolean> | null = null;

interface RazorpayWindow {
  Razorpay?: unknown;
}

function hasRazorpayGlobal(): boolean {
  if (typeof window === "undefined") return false;
  return Boolean((window as unknown as RazorpayWindow).Razorpay);
}

export function isRazorpayReadyOnClient(): boolean {
  return hasRazorpayGlobal();
}

export function loadRazorpayScript(): Promise<boolean> {
  if (typeof window === "undefined") {
    // SSR: no DOM to attach the script to. Resolve as a no-op.
    return Promise.resolve(false);
  }

  if (hasRazorpayGlobal()) {
    return Promise.resolve(true);
  }

  if (inflight) {
    return inflight;
  }

  inflight = new Promise<boolean>((resolve) => {
    const existing = document.getElementById(
      RAZORPAY_SCRIPT_ID,
    ) as HTMLScriptElement | null;

    const onReady = () => resolve(hasRazorpayGlobal());
    const onError = () => {
      // Reset cache so a subsequent click can retry the network fetch.
      inflight = null;
      resolve(false);
    };

    if (existing) {
      // Another caller already inserted the tag but hadn't resolved yet.
      existing.addEventListener("load", onReady, { once: true });
      existing.addEventListener("error", onError, { once: true });
      return;
    }

    const script = document.createElement("script");
    script.id = RAZORPAY_SCRIPT_ID;
    script.src = RAZORPAY_SCRIPT_URL;
    script.async = true;
    script.addEventListener("load", onReady, { once: true });
    script.addEventListener("error", onError, { once: true });
    document.head.appendChild(script);
  });

  return inflight;
}
