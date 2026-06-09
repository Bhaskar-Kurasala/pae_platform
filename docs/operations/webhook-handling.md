# Webhook handling — canonical reference

> Scope: Razorpay + Stripe webhooks. Pattern established in Batch 3 CP1 (2026-05-14).
> Implementation files: `payments_webhook.py`, `payment_webhook_event_service.py`,
> `payment_providers/razorpay_provider.py`, `models/payment_webhook_event.py`.

---

## Architecture overview

Incoming webhooks pass through **two independent layers** before any business logic runs:

```
Provider POST
     │
     ▼
Layer 1 — Signature check
     │   verify_webhook_signature() → bool
     │   Result recorded in payment_webhook_events.signature_valid
     │
     ▼
Layer 2 — Idempotency gate
     │   INSERT INTO payment_webhook_events (provider, provider_event_id)
     │   UNIQUE constraint → IntegrityError on duplicate → short-circuit
     │
     ▼
Dispatch pipeline (only if sig_valid AND not duplicate)
     │   dispatch_event() — fully DI, routes to payment_success / payment_failed / refund
     │
     ▼
mark_event_processed() — stamps processed_at (or error=str(exc)[:512])
```

Both layers run inside `record_webhook_event()`, which is called before any
business logic. The route never dispatches if either layer rejects the event.

---

## HMAC-SHA256 implementation

Signature verification is delegated to the provider adapter via `PaymentProviderBase.verify_webhook_signature()`.

### Razorpay

`RazorpayProvider.verify_webhook_signature()` (in `razorpay_provider.py`):

```python
self._client.utility.verify_webhook_signature(
    raw_body.decode("utf-8"),
    signature,
    settings.razorpay_webhook_secret,
)
```

- Uses the official Razorpay Python SDK's `utility.verify_webhook_signature`.
- Under the hood: HMAC-SHA256 of the raw request body keyed with `RAZORPAY_WEBHOOK_SECRET`.
- Returns `False` (does NOT re-raise) on `SignatureVerificationError` — this is the
  contract on `PaymentProviderBase` so all callers get a clean bool, not an exception.
- If `settings.razorpay_webhook_secret` is unset, logs a warning and returns `False`
  (fail-closed for security: no secret means all signatures are treated as invalid).

### Raw body handling

The route reads `raw_body = await request.body()` **once** before FastAPI parses the
JSON body. Re-reading after framework parsing is unsafe because async streams are
consumed. The same `raw_body` bytes are stored verbatim in `payment_webhook_events.raw_body`
(Postgres `BYTEA`) so signatures can be re-verified offline if the secret is rotated.

---

## Security posture: why invalid signatures return 200

**Spec D-A** says invalid signatures should return 401. The implementation deliberately
deviates from this.

### The problem with non-2xx on invalid signatures

Razorpay (and Stripe) treat any non-2xx response as a delivery failure and will retry
the webhook up to 5 times with exponential back-off. An adversary sending forged
requests with bad signatures would therefore cause infinite retry storms — every
forged event triggers 5 re-deliveries regardless of whether we reject them.

### The implemented behaviour

```
invalid signature → recorded in DB (signature_valid=False, error="invalid_signature")
                  → log.warning("webhook.invalid_signature", ...)
                  → return 200 WebhookAck(received=True)
```

The audit trail is complete (full raw body stored), but Razorpay is told "received"
so it stops retrying. Dispatch is **never** called for invalid-signature events — the
route checks `event.signature_valid` before proceeding.

### The one genuine 4xx case

A completely **missing** signature header (i.e. `X-Razorpay-Signature` absent) returns
HTTP 400. This is misconfiguration on the provider dashboard side — there is no valid
retry scenario — and the 400 forces the operator to fix the integration rather than
enter an endless retry loop.

---

## Idempotency table: `payment_webhook_events`

```sql
CREATE TABLE payment_webhook_events (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider         VARCHAR(20)  NOT NULL,
    provider_event_id VARCHAR(255) NOT NULL,
    event_type       VARCHAR(80)  NOT NULL,
    raw_body         BYTEA        NOT NULL,
    signature        VARCHAR(512),
    signature_valid  BOOLEAN      NOT NULL DEFAULT FALSE,
    related_order_id UUID REFERENCES orders(id) ON DELETE SET NULL,
    processed_at     TIMESTAMPTZ,
    error            TEXT,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_payment_webhook_provider_event UNIQUE (provider, provider_event_id)
);
```

Key design decisions:

- **UNIQUE (provider, provider_event_id)** is the dedup boundary. Every webhook
  event gets an `id` from the provider (e.g. Razorpay's `evt_…`); the pair
  `(provider, id)` is globally unique.
- The INSERT happens **before** any business logic. If two concurrent deliveries of
  the same event race, exactly one INSERT wins; the other gets an `IntegrityError`,
  rolls back, fetches the existing row, and returns `is_duplicate=True`.
- `raw_body` is stored as bytes, not text, to preserve exact byte content for
  signature re-verification.
- `signature_valid=False` rows are kept — they form an audit trail of attempted
  replays or forgeries.
- `error` is truncated to 512 chars when set from dispatch failures
  (`str(exc)[:512]`) to keep the column bounded.

---

## Dispatch pipeline

`record_webhook_event()` returns `(event_row, is_duplicate)`. The route in
`payments_webhook.py` then executes:

```
record_webhook_event(db, provider, raw_body, signature)
    → (event, is_duplicate)

if is_duplicate:
    return WebhookAck(received=True, duplicate=True)

if not event.signature_valid:
    log.warning(...)
    return WebhookAck(received=True, duplicate=False)

envelope = provider_client.parse_webhook_event(raw_body=raw_body)

dispatch_event(db, event, envelope,
    order_resolver=...,
    attempt_recorder=...,
    entitlement_grant_fn=...,
    refund_handler=...,
)

await db.commit()
mark_event_processed(db, event_id=event.id, related_order_id=...)
```

`dispatch_event()` is fully dependency-injected. Every external call (order lookup,
attempt recording, entitlement grant, refund processing) is passed in as a callable.
This makes the routing logic unit-testable in isolation without rebuilding the full
stack. It returns one of four routing decision strings: `"payment_success"`,
`"payment_failed"`, `"refund"`, or `"unhandled"`.

Event-type routing table:

| Event type | Set | Routed to |
|---|---|---|
| `payment.captured` | PAYMENT_SUCCESS_EVENTS | `attempt_recorder(failed=False)` + entitlement grant |
| `checkout.session.completed` | PAYMENT_SUCCESS_EVENTS | same |
| `payment_intent.succeeded` | PAYMENT_SUCCESS_EVENTS | same |
| `payment.failed` | PAYMENT_FAILURE_EVENTS | `attempt_recorder(failed=True)` |
| `refund.processed` | REFUND_EVENTS | `refund_handler(db, envelope)` |
| `refund.created` | REFUND_EVENTS | `refund_handler(db, envelope)` |
| anything else | — | logged + `"unhandled"` |

---

## Error handling: dispatch failures never become 5xx

**Spec D-B** says processing failures should return 500 so Razorpay retries. The
implementation deliberately deviates from this as well.

If `dispatch_event()` raises, the route catches the exception at the outermost level:

```python
except Exception as exc:
    log.exception("webhook.dispatch.error", provider=..., event_id=..., error=str(exc))
    with contextlib.suppress(Exception):
        await db.rollback()
    with contextlib.suppress(Exception):
        await payment_webhook_event_service.mark_event_processed(
            db, event_id=event.id, error=str(exc)[:512]
        )
# Falls through to:
return WebhookAck(received=True, duplicate=False, event_type=event.event_type)
```

The error is:
1. Logged at `exception` level (includes full traceback via structlog).
2. Stored in `payment_webhook_events.error` (truncated to 512 chars).
3. Never propagated as a 5xx.

Rationale: A 5xx causes Razorpay to retry the same event repeatedly. For transient
infrastructure failures (DB timeout, network blip) this could cause thousands of
retries. For permanent failures (bug in dispatch logic), retrying doesn't help and
creates noise. The error is surfaced via structured logs and Sentry instead.

Human intervention or a backfill script (re-running unprocessed events by querying
`processed_at IS NULL AND error IS NOT NULL`) is the recovery path for dispatch bugs.

---

## Adding a new payment provider

1. Create `app/services/payment_providers/<name>_provider.py` and subclass
   `PaymentProviderBase` (in `base.py`).

2. Implement the two required webhook methods:

   ```python
   def verify_webhook_signature(self, *, raw_body: bytes, signature: str) -> bool:
       # Return False (never raise) on mismatch.
       ...

   def parse_webhook_event(self, *, raw_body: bytes) -> WebhookEventEnvelope:
       # Return a WebhookEventEnvelope with at minimum:
       #   provider_event_id: str  — unique ID from the provider
       #   event_type: str         — e.g. "payment.captured"
       #   related_provider_order_id: str | None
       #   related_provider_payment_id: str | None
       #   raw_payload: dict
       ...
   ```

3. Register the provider in `app/services/payment_providers/__init__.py`'s
   `get_provider()` factory.

4. Add a `POST /payments/webhook/<name>` route in `payments_webhook.py` that reads
   the provider's signature header and calls `_handle_webhook(provider_name="<name>", ...)`.

5. Add the new event type strings to the appropriate sets in
   `payment_webhook_event_service.py`:
   - `PAYMENT_SUCCESS_EVENTS`
   - `PAYMENT_FAILURE_EVENTS`
   - `REFUND_EVENTS`

No changes are needed in the idempotency layer or dispatch logic — they are
provider-agnostic.

---

## Pattern 35 instance

`record_webhook_event()` is the **single dedup layer** for all webhook routes. Every
webhook handler (Razorpay, Stripe, and any future provider) inherits deduplication
by calling it before dispatching. There is no per-route dedup logic.

This follows Pattern 35 (shared infrastructure, single responsibility): the idempotency
boundary is owned exclusively by `payment_webhook_event_service.py`, not by individual
routes. Routes are responsible only for parsing the signature header and calling
`_handle_webhook()`.

---

## Observability

All webhook events emit structured log lines via `structlog`:

| Log key | When emitted |
|---|---|
| `webhook.recorded` | New event inserted successfully |
| `webhook.duplicate` | IntegrityError — duplicate short-circuit |
| `webhook.invalid_signature` | Signature valid=False, not dispatching |
| `webhook.dispatch.payment_success` | Payment captured, order fulfilled |
| `webhook.dispatch.payment_failed` | Payment failure recorded |
| `webhook.dispatch.refund` | Refund row created, entitlements revoked |
| `webhook.unhandled_event` | event_type not in any known set |
| `webhook.dispatch.error` | Exception in dispatch (full traceback) |

All log lines include `provider` and `event_id` (the internal UUID, not the provider's
event ID) so events can be correlated across the audit table and log sink.
