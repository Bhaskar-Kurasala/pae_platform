/**
 * PR3/C3.1 — frontend telemetry (PostHog).
 *
 * Single chokepoint for all client-side product analytics.
 *
 * Design rules:
 *
 *   1. **No-op safe.** When `NEXT_PUBLIC_POSTHOG_KEY` is unset, every
 *      function silently does nothing. Dev, CI, and self-hosted
 *      deployments without telemetry must work identically to a
 *      production deploy with PostHog wired up — they just stop
 *      emitting events. We never throw from here.
 *
 *   2. **Lazy import.** `posthog-js` only gets pulled in when we
 *      actually have a key. This keeps the dev-server bundle smaller
 *      for engineers who never run with telemetry on.
 *
 *   3. **Single init.** Module-scoped guard prevents double-init when
 *      Next's HMR re-evaluates the module in dev. Calling identify()
 *      after init is allowed and re-runs every time the user changes.
 *
 *   4. **Thin wrapper.** No typed event catalog at this layer — the
 *      catalog lives at the call sites in PR3/C3.2 so a screen-level
 *      refactor can rename or drop events without touching this file.
 */

type PostHogClient = {
  init: (key: string, opts: Record<string, unknown>) => void;
  capture: (event: string, properties?: Record<string, unknown>) => void;
  identify: (
    distinctId: string,
    properties?: Record<string, unknown>,
  ) => void;
  reset: () => void;
};

let _client: PostHogClient | null = null;
let _initStarted = false;

function getKey(): string | null {
  // process.env.NEXT_PUBLIC_* is statically inlined at build time by
  // Next, so this works in both client and server bundles.
  const key = process.env.NEXT_PUBLIC_POSTHOG_KEY;
  return key && key.length > 0 ? key : null;
}

async function ensureClient(): Promise<PostHogClient | null> {
  if (_client) return _client;
  if (_initStarted) return _client; // race-safe: another caller is mid-init
  _initStarted = true;

  if (typeof window === "undefined") {
    // Server-side rendering path; PostHog browser SDK is no-op here.
    return null;
  }

  const key = getKey();
  if (!key) return null;

  try {
    const mod = (await import("posthog-js")) as unknown as {
      default: PostHogClient;
    };
    const ph = mod.default;
    ph.init(key, {
      api_host:
        process.env.NEXT_PUBLIC_POSTHOG_HOST ?? "https://app.posthog.com",
      // Don't auto-capture — we want a curated event catalog (C3.2),
      // not a noisy click-stream that bloats the workspace.
      autocapture: false,
      capture_pageview: false,
      // Respect user privacy by default.
      persistence: "localStorage",
    });
    _client = ph;
    return _client;
  } catch {
    // Soft fail — telemetry is never load-bearing.
    return null;
  }
}

/**
 * Fire a PostHog event. Fire-and-forget — we don't await the SDK init
 * because callers (button onClick, mutation onSuccess) shouldn't block
 * on telemetry network round-trips.
 */
export function capture(
  event: string,
  properties?: Record<string, unknown>,
): void {
  if (!getKey() || typeof window === "undefined") return;
  void (async () => {
    const client = await ensureClient();
    if (!client) return;
    try {
      client.capture(event, properties);
    } catch {
      // Soft fail.
    }
  })();
}

/**
 * Tag the current session with the signed-in user's id so server-side
 * and client-side events share a distinct_id.
 */
export function identify(
  distinctId: string,
  properties?: Record<string, unknown>,
): void {
  if (!getKey() || typeof window === "undefined") return;
  void (async () => {
    const client = await ensureClient();
    if (!client) return;
    try {
      client.identify(distinctId, properties);
    } catch {
      // Soft fail.
    }
  })();
}

/** Drop all session state on sign-out. */
export function reset(): void {
  if (!_client) return;
  try {
    _client.reset();
  } catch {
    // Soft fail.
  }
}
