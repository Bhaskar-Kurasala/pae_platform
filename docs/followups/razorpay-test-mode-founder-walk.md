---
id: razorpay-test-mode-founder-walk
status: deferred
blocking: B3 (Batch 3 CP1 Track 1)
requires: RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET set in environment
---

# B3 — Razorpay Test-Mode Founder Walk

## Why deferred

B3 requires a live Razorpay test-mode key pair to exercise the full
create-order → capture → webhook flow end-to-end. The test environment
does not have credentials — the provider falls back to `MockProvider`.

**When to run**: before go-live, with Razorpay test credentials in `.env`.

## Pre-requisites

```bash
# Confirm credentials are present
echo $RAZORPAY_KEY_ID      # should start with rzp_test_
echo $RAZORPAY_KEY_SECRET  # should be non-empty
```

## Smoke script

```bash
#!/usr/bin/env bash
# B3 Razorpay test-mode founder walk
# Run from repo root with a valid test keypair in env.
set -euo pipefail

BASE_URL=${BASE_URL:-http://localhost:8000}
EMAIL="b3smoke+$(date +%s)@example.com"
PASSWORD="SmokeTest1234!"

echo "=== B3 Razorpay test-mode walk ==="

# 1. Register + login
TOKEN=$(curl -s -X POST "$BASE_URL/api/v1/auth/register" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$EMAIL\",\"full_name\":\"B3 Smoke\",\"password\":\"$PASSWORD\"}" | \
  python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))")

if [ -z "$TOKEN" ]; then
  TOKEN=$(curl -s -X POST "$BASE_URL/api/v1/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}" | \
    python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
fi
echo "✅ Logged in"

# 2. Pick a published paid course (get first from catalogue)
COURSE_ID=$(curl -s "$BASE_URL/api/v1/courses/" | \
  python3 -c "
import sys, json
courses = json.load(sys.stdin)
paid = [c for c in courses if c.get('price_cents', 0) > 0 and c.get('status') == 'published']
print(paid[0]['id'] if paid else '')
")
if [ -z "$COURSE_ID" ]; then
  echo "⚠️  No published paid course found — seed one first, then re-run."
  exit 1
fi
echo "✅ Found paid course: $COURSE_ID"

# 3. Create order — server computes price (B9 already ✅)
ORDER=$(curl -s -X POST "$BASE_URL/api/v1/payments/orders" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"target_type\":\"course\",\"target_id\":\"$COURSE_ID\",\"provider\":\"razorpay\"}")
echo "Order response: $ORDER"

PROVIDER_ORDER_ID=$(echo "$ORDER" | python3 -c "import sys,json; print(json.load(sys.stdin).get('provider_order_id',''))")
AMOUNT=$(echo "$ORDER" | python3 -c "import sys,json; print(json.load(sys.stdin).get('amount_cents',''))")

if [ -z "$PROVIDER_ORDER_ID" ]; then
  echo "❌ Order creation failed — check logs."
  exit 1
fi
echo "✅ Order created: $PROVIDER_ORDER_ID, amount_cents=$AMOUNT (server-computed)"

# 4. Simulate Razorpay capture webhook (test mode)
# In real test-mode: use Razorpay dashboard to capture the payment.
# Or use Razorpay's test-mode API:
#   rzp_test: POST https://api.razorpay.com/v1/payments/<pay_id>/capture
# Then Razorpay sends the webhook to your ngrok/public URL.
#
# To test webhook locally with ngrok:
#   ngrok http 8000
#   Set webhook URL in Razorpay dashboard to https://<ngrok>.ngrok.io/api/v1/payments/webhook/razorpay

echo ""
echo "=== Manual steps ==="
echo "1. In Razorpay test dashboard, capture payment for order: $PROVIDER_ORDER_ID"
echo "2. Confirm webhook fires to POST /api/v1/payments/webhook/razorpay"
echo "3. Check DB: SELECT * FROM payment_webhook_events WHERE provider_order_id = '$PROVIDER_ORDER_ID';"
echo "4. Confirm enrollment row created: SELECT * FROM enrollments WHERE user_id = <user_uuid>;"
echo ""
echo "B3 smoke walk complete — manual capture required for full end-to-end."
```

## Acceptance criteria

- [ ] `POST /payments/orders` returns 201 with `provider_order_id` from Razorpay (not mock)
- [ ] `amount_cents` in response matches the course's `price_cents` in DB (B9 verified)
- [ ] Razorpay dashboard shows order in test mode
- [ ] After capture: webhook received, `payment_webhook_events` row inserted, `signature_valid=true`
- [ ] Enrollment row created for user+course
- [ ] No raw Python errors in response bodies (H1.1 verified)

## Owner

Founder / ops team before cohort-1 go-live.
