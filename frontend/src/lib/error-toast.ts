/**
 * PR2/B1.1 + PR3/C1.1 — central error-toast classifier.
 *
 * Extracted from `providers.tsx` so the test in
 * `frontend/src/test/contracts/error-toasts.test.tsx` exercises the
 * REAL function instead of a re-derived copy that can silently drift.
 *
 * Buckets (PR2/B1.1):
 *   - ApiTimeoutError → "Request took too long…"
 *   - ApiError(401)   → silent (refresh+redirect handled in api-client)
 *   - ApiError(4xx/5xx) → backend `{error.message}` envelope >
 *                          slowapi `{detail}` > bland fallback
 *   - non-ApiError    → "Something went wrong"
 *
 * Reference suffix (PR3/C1.1):
 *   Every toast that fires gets a "Reference: abc123de" line appended
 *   when we have a request_id. We try, in order:
 *     1. err.requestId (set on ApiError by the api-client at throw time —
 *        most accurate when toasts coalesce or fire async).
 *     2. body.error.request_id (the structured envelope from
 *        backend/app/core/exception_handler.py).
 *     3. getLastRequestId() (module-scoped fallback for non-ApiError
 *        paths — timeouts, network errors, etc.).
 */
import { ApiError, ApiTimeoutError, getLastRequestId } from "@/lib/api-client";
import { toast } from "@/lib/toast";

export function withReference(text: string, requestId: string | null): string {
  if (!requestId) return text;
  // Short-form the UUID — backend uses uuid4().hex; first 8 chars is
  // enough to grep logs and is friendlier than the full 36-char form.
  const short = requestId.replace(/-/g, "").slice(0, 8);
  return `${text}\nReference: ${short}`;
}

export function showErrorToast(
  err: unknown,
  meta: { skipErrorToast?: boolean } | undefined,
): void {
  if (meta?.skipErrorToast) return;
  if (err instanceof ApiTimeoutError) {
    toast.error(withReference(err.message, getLastRequestId()));
    return;
  }
  if (err instanceof ApiError) {
    if (err.status === 401) return; // refresh+redirect handled in api-client
    const body = err.body as
      | { error?: { message?: string; request_id?: string } }
      | { detail?: string }
      | undefined;
    const fromEnvelope = body && "error" in body ? body.error?.message : null;
    const fromDetail = body && "detail" in body ? body.detail : null;
    const text = fromEnvelope || fromDetail || err.message || "Something went wrong";
    const requestId =
      err.requestId ??
      (body && "error" in body ? body.error?.request_id : null) ??
      getLastRequestId();
    toast.error(withReference(text, requestId));
    return;
  }
  toast.error(
    withReference("Something went wrong. Please try again.", getLastRequestId()),
  );
}
