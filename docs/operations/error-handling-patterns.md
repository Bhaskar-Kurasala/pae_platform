# Error Handling Patterns — Canonical Reference

Authored at Batch 2A CP1 closure. This is the authoritative reference for
error-handling conventions across the backend and frontend. Any new code
touching error paths must follow these patterns.

---

## D-A: Backend exception-message leak fix (H1)

**Rule:** Never forward raw exception text to HTTP clients. Log the raw
exception server-side, raise an HTTPException with a generic user message.

```python
# BAD — leaks exception internals to user
raise HTTPException(status_code=502, detail=f"Payment provider unavailable: {exc}")
raise HTTPException(status_code=400, detail=str(exc))

# GOOD — log full exception, raise generic user message
log.warning("payments.order.provider_unavailable", error=str(exc))
raise HTTPException(
    status_code=502,
    detail="Payment provider is temporarily unavailable. Please try again.",
) from exc
```

**Logging discipline:**
- Use `log.warning` for expected failures (validation errors, not-found, rate limits)
- Use `log.error` for unexpected failures (provider errors, parse failures)
- Use `log.exception` for fully unexpected errors with a traceback
- Always include `error=str(exc)` in structured fields
- `request_id` and `trace_id` are bound automatically by `RequestIDMiddleware`
  and appear on every log line without any per-call plumbing

**Generic message vocabulary:**
| Failure class | Generic user message |
|---|---|
| Payment provider down | "Payment provider is temporarily unavailable. Please try again." |
| Service/LLM unavailable | "Service temporarily unavailable. Please try again." |
| Validation / bad request | "Unable to [action]. Please check your request." |
| Session not found | "Session not found." |
| Session already closed | "Session is already closed." |
| Agent not found | "Agent not found." |
| Webhook signature | "Webhook signature verification failed." |

---

## D-B: Frontend error rendering (H2)

**Rule:** Never render raw `err.message` or `err.detail` directly. Route
through the central translator in `lib/error-toast.ts`.

**For toast paths (non-inline):**

```typescript
// BAD
toast.error(err instanceof Error ? err.message : "Save failed.");

// GOOD
import { showErrorToast } from "@/lib/error-toast";
// ...
} catch (err) {
  console.error("[component] action failed", err);
  showErrorToast(err, undefined);
}
```

**For setError / state paths (inline rendering):**

```typescript
// BAD
setError(err instanceof Error ? err.message : "Something went wrong.");

// GOOD
import { translateError } from "@/lib/error-toast";
// ...
} catch (err) {
  console.error("[component] action failed", err);
  setError(translateError(err));
}
```

**`translateError` shape** (`lib/error-toast.ts`):
- `ApiTimeoutError` → `err.message`
- `ApiError(401)` → "Session expired. Please log in again."
- `ApiError(4xx/5xx)` → backend `error.message` envelope > `detail` > `err.message`
- other → "Something went wrong. Please try again."

**`console.error` discipline:** Always emit `console.error` before setting
the user-facing error state. This logs the full error object to DevTools for
developers without leaking it to users.

---

## D-D: Inline error component (H4)

**Rule:** All inline error states (not toasts) use `GracefulFailureMessage`
from `@/components/errors/graceful-failure-message`.

```tsx
// BAD — raw div with {error} or {err.message}
{error && (
  <div className="text-destructive">{error}</div>
)}

// GOOD — GracefulFailureMessage with retry handler
import { GracefulFailureMessage } from "@/components/errors/graceful-failure-message";
// ...
{error && (
  <GracefulFailureMessage
    userMessage={error}
    onRetry={handleRetry}
    className="text-sm"
  />
)}
```

**GracefulFailureMessage props:**
- `userMessage?: string` — override for the default "Something went wrong" copy
- `onRetry: () => void` — **required** — the action to retry on "Try again" click
- `traceId?: string | null` — W3C trace_id or request_id from error envelope
- `className?: string` — outer container spacing override
- `retryLabel?: string` — override "Try again" button label

**Retry handler conventions by context:**
| Context | Retry handler |
|---|---|
| Form submit failed | `() => setError(null)` (let user re-submit from the form) |
| API fetch failed (side-effect) | Re-invoke the fetch action directly |
| React Query mutation error | `() => { reset(); mutate(args); }` |
| Interview session error | `handleReset` (restart session) |
| Context picker load failed | `() => setRetryCount(n => n + 1)` (re-triggers effect) |

---

## Pattern scope

These patterns apply to all routes in `backend/app/api/v1/routes/` and all
frontend components in `frontend/src/app/` and `frontend/src/components/`.

**PSC-1 exceptions** (Batch 1 scope — do not apply these patterns until
Batch 1 CP3 is sealed):
- `frontend/src/app/(public)/login/`
- `frontend/src/app/(public)/register/`
- `frontend/src/app/(public)/password-reset/`
- `frontend/src/app/(public)/verify-email*`

---

## H5/H6 deferred patterns (post-Batch-1)

- **H5** — structlog PII redaction processor (`app/core/` shared substrate)
- **H6** — Sentry `trace_id`/`request_id` tags (`app/core/` shared substrate)

These touch the `app/core/` substrate which Batch 1 CP3 may be modifying.
Wire after Batch 1 is sealed.
