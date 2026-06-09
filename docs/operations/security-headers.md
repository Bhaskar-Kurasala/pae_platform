# Security Headers — E9

## Headers Deployed

All six headers are injected at two layers for defense-in-depth:

| Layer | Mechanism | Applies to |
|---|---|---|
| Next.js Edge | `frontend/src/middleware.ts` — `addSecurityHeaders()` | All responses through the Next.js runtime |
| Nginx | `nginx/nginx.conf` — `add_header … always` | All responses including static assets and direct backend proxy |

### Header Inventory

| Header | Value | Purpose |
|---|---|---|
| `Strict-Transport-Security` | `max-age=63072000; includeSubDomains; preload` | Force HTTPS for 2 years; eligible for HSTS preload list |
| `X-Frame-Options` | `DENY` | Block all framing (clickjacking) |
| `X-Content-Type-Options` | `nosniff` | Prevent MIME-type sniffing |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Send origin only on cross-origin requests |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=(), payment=()` | Deny browser feature access |
| `Content-Security-Policy-Report-Only` | See below | Characterise violations before enforcing |

### CSP Shape (Report-Only)

```
default-src 'self';
script-src 'self' 'unsafe-inline' 'unsafe-eval';
style-src 'self' 'unsafe-inline';
img-src 'self' data: https:;
connect-src 'self' https://api.razorpay.com https://*.sentry.io;
font-src 'self' data:;
frame-src https://api.razorpay.com;
frame-ancestors 'none';
base-uri 'self';
form-action 'self';
report-uri /api/v1/csp-report
```

**Why Report-Only?** The `'unsafe-inline'` and `'unsafe-eval'` directives are placeholders needed while the full inventory of inline scripts and eval usage is characterised. Shipping an enforcing CSP with these gaps would break the application silently for users. Report-Only lets violations flow to the log without blocking anything.

## CSP Violation Endpoint

`POST /api/v1/csp-report` — no auth required (browsers send without credentials).

- File: `backend/app/api/v1/routes/csp_report.py`
- Logs at `WARNING` level with key `csp.violation`
- Returns `204 No Content` on all paths
- Handles both `application/csp-report` (legacy) and `application/json`

### Monitoring Violations

```bash
# Stream violations from Docker logs
docker compose logs -f backend | grep '"csp.violation"'

# Count by blocked-uri
docker compose logs backend | grep '"csp.violation"' | python3 -c "
import sys, json
from collections import Counter
c = Counter()
for line in sys.stdin:
    try:
        e = json.loads(line.split(' ', 3)[-1])
        rep = e.get('report', {})
        c[rep.get('blocked-uri','?')] += 1
    except Exception:
        pass
for k,v in c.most_common(20): print(v, k)
"
```

## Cutover Plan (CSP Enforcing Mode)

See `docs/followups/csp-enforcing-mode-cutover.md` for the step-by-step plan.

High-level:
1. Monitor Report-Only for 2–4 weeks in production
2. Remove `'unsafe-inline'` and `'unsafe-eval'` by migrating to nonce-based or hash-based allowlisting
3. Switch `Content-Security-Policy-Report-Only` → `Content-Security-Policy`
4. Keep `report-uri` active; a well-configured CSP still generates violation reports

## Sentry CSP Integration

Currently violations log to structlog only. Sentry has a CSP reporting endpoint that can correlate violations with user sessions. See `docs/followups/sentry-csp-reporting-integration.md` for the wiring plan.
