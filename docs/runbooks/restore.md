# Runbook — Database restore from R2 backup

**Owner:** Bhaskar
**Severity:** P0 (data-loss recovery)
**SLA target:** Restored copy verified within 15 minutes of starting the drill.

This runbook walks a teammate with shell access through restoring the
production Neon database from the most recent Cloudflare R2 backup.
It is followable cold — no prior context required beyond the credentials
listed in **Prerequisites**.

The backup pipeline that produces these files is documented inline at
`infra/backup/backup.sh` (PR3/D1.1).

---

## When to use this runbook

- **Disaster recovery.** Prod DB lost / corrupted / catastrophically wrong-deleted.
- **Drill (every 30 days).** Verify the backup is restorable. Skipping the drill is the same as not having backups.
- **Forensics.** Restore a point-in-time copy to a Neon branch to investigate a specific bug without touching prod.

If you're here because of an active prod incident, jump to
[Section 3 — Emergency restore](#3--emergency-restore-prod-down).
Otherwise read the whole document.

---

## 1 — Prerequisites

Before you start, you must have:

| Credential | Where it lives | Used for |
|---|---|---|
| Cloudflare R2 API token (read-only is fine for restore) | 1Password "PAE — R2" | Listing + downloading backups |
| Neon API key | Neon dashboard → Account → API Keys | Creating a restore branch |
| `psql` 16.x locally | `brew install postgresql@16` | Loading the dump |
| `awscli` v1 or v2 | `brew install awscli` | Pulling from R2 |
| Backend repo checked out | `git clone …` | Running contract tests |

Sanity check your tooling:

```bash
psql --version              # → psql (PostgreSQL) 16.x
aws --version               # → aws-cli/1.x or 2.x
which uv                    # → backend tests run via uv
```

---

## 2 — Drill restore (no incident)

Use this path on the 1st of every month. Schedule it on your calendar.

### 2.1 — Configure AWS CLI for R2

R2 is S3-compatible but uses a per-account endpoint. Set these env vars in
your shell — **do not** write them to `~/.aws/credentials` (we don't keep
backup creds on disk):

```bash
export AWS_ACCESS_KEY_ID="<r2-access-key>"
export AWS_SECRET_ACCESS_KEY="<r2-secret-key>"
export AWS_DEFAULT_REGION="auto"
export R2_ACCOUNT_ID="<cloudflare-account-id>"
export R2_BUCKET="pae-backups"
export R2_ENDPOINT="https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
```

### 2.2 — Pull the latest backup

```bash
# List today's backups (date-prefixed in R2 — see backup.sh comment).
aws s3 ls --endpoint-url "$R2_ENDPOINT" \
    "s3://${R2_BUCKET}/backups/$(date -u +%Y/%m/%d)/"

# Download the latest one. Adjust the filename from the listing above.
LATEST_KEY="backups/$(date -u +%Y/%m/%d)/pae-$(date -u +%Y%m%d)-040000.sql.gz"
aws s3 cp --endpoint-url "$R2_ENDPOINT" \
    "s3://${R2_BUCKET}/${LATEST_KEY}" \
    /tmp/pae-restore.sql.gz

# Verify size — a healthy prod backup is 20–500 MB at our scale. A 1KB
# file means pg_dump failed silently and we have a backup-of-an-error.
ls -lh /tmp/pae-restore.sql.gz
```

### 2.3 — Create a Neon restore branch

```bash
# In the Neon dashboard:
#   Project → Branches → Create branch
#   Name: "restore-drill-YYYY-MM-DD"
#   Parent: main
#
# Copy the connection string — should look like:
#   postgres://restore_user:…@ep-…-pooler.us-east-1.aws.neon.tech/neondb
export NEON_RESTORE_URL="postgres://…"
```

The branch is a copy-on-write fork of prod. It's free, isolated, and
discardable when the drill finishes.

### 2.4 — Load the dump

```bash
# `gunzip -c` streams; `psql` reads from stdin. The dump uses
# --no-owner / --no-privileges so it doesn't reference prod role names.
gunzip -c /tmp/pae-restore.sql.gz \
  | psql "$NEON_RESTORE_URL" \
      --set ON_ERROR_STOP=1 \
      --quiet
```

`ON_ERROR_STOP=1` is critical — without it, psql will keep running past
a CREATE TABLE failure and you end up with a half-restored DB that
*looks* fine until the missing rows bite. With it, a single error aborts
and you know to investigate.

### 2.5 — Verify

```bash
# Sanity row counts (numbers depend on prod state — eyeball for
# "is this in the right ballpark?").
psql "$NEON_RESTORE_URL" -c "
    SELECT
        (SELECT count(*) FROM users) AS users,
        (SELECT count(*) FROM courses) AS courses,
        (SELECT count(*) FROM exercises) AS exercises;
"

# Run the read-only contract tests against the restored DB.
cd backend
DATABASE_URL="$NEON_RESTORE_URL" \
JWT_SECRET_KEY="drill-only-secret" \
ANTHROPIC_API_KEY="sk-test-mock" \
    uv run pytest tests/test_contracts/ -x --tb=short
```

All contract tests should pass. If any fail, the backup is corrupt or
the schema migration after the backup time isn't being captured —
**stop and file an incident** before declaring the drill green.

### 2.6 — Tear down

```bash
# In the Neon dashboard: delete the restore-drill-YYYY-MM-DD branch.
# Locally:
rm /tmp/pae-restore.sql.gz
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY NEON_RESTORE_URL
```

Note in `docs/runbooks/oncall.md` the drill date + result. A failed
drill is a P1 ticket — file it before going to bed.

---

## 3 — Emergency restore (prod down)

You're here because the prod DB is unrecoverable and we're cutting over
to a restored copy. The plan:

1. **Freeze writes.** In the Fly dashboard, scale `pae-platform` API to 0:
   ```bash
   fly scale count 0 -a pae-platform
   ```
   This stops the write path while you restore.

2. **Restore to a NEW Neon branch** (Section 2.1–2.4). Do NOT restore over
   the existing prod branch — keep the corrupt copy for forensics.

3. **Cut over.** Promote the restore branch to primary in the Neon
   dashboard. Update Fly secrets to point at the new connection string:
   ```bash
   fly secrets set DATABASE_URL="<new-prod-url>" -a pae-platform
   ```

4. **Bring API back up.**
   ```bash
   fly scale count 1 -a pae-platform
   fly logs -a pae-platform | grep app.startup
   ```

5. **Smoke test.** Hit `https://app.example.com/health/ready` (PR3/C6.1).
   Should return 200 with `{db:"ok",redis:"ok"}`. Log in as the smoke
   user and load `/today`.

6. **Post-mortem.** Within 24h, write up:
   - When the loss happened (timestamp from logs).
   - Window of data lost (last good backup → incident time).
   - Root cause.
   - What we'd change to prevent re-occurrence.

---

## 4 — R2 retention policy (PR3/D1.3)

We keep:

- **7 daily** backups (last week).
- **4 weekly** backups (Sunday of the last 4 weeks).
- **3 monthly** backups (1st of the last 3 months).

Total: 14 objects in steady state, ~3–5 GB at projected 1k-user scale.
Cloudflare R2's first 10 GB is free, so retention costs nothing for the
foreseeable future.

### 4.1 — Apply the policy

R2 lifecycle rules are configured per-bucket. Apply this JSON via the
Cloudflare API or the R2 dashboard. **Do not call R2 from CI** — this
is a one-time human operation when the bucket is provisioned.

Save as `r2-lifecycle.json`:

```json
{
  "Rules": [
    {
      "ID": "expire-daily-after-7d",
      "Status": "Enabled",
      "Filter": { "Prefix": "backups/" },
      "Expiration": { "Days": 7 },
      "AbortIncompleteMultipartUpload": { "DaysAfterInitiation": 1 }
    },
    {
      "ID": "keep-weekly-as-archive",
      "Status": "Enabled",
      "Filter": { "Prefix": "archive/weekly/" },
      "Expiration": { "Days": 35 },
      "AbortIncompleteMultipartUpload": { "DaysAfterInitiation": 1 }
    },
    {
      "ID": "keep-monthly-as-archive",
      "Status": "Enabled",
      "Filter": { "Prefix": "archive/monthly/" },
      "Expiration": { "Days": 100 },
      "AbortIncompleteMultipartUpload": { "DaysAfterInitiation": 1 }
    }
  ]
}
```

Apply via AWS CLI (R2 supports the `s3api put-bucket-lifecycle-configuration` call):

```bash
aws s3api put-bucket-lifecycle-configuration \
    --endpoint-url "$R2_ENDPOINT" \
    --bucket "$R2_BUCKET" \
    --lifecycle-configuration file://r2-lifecycle.json
```

Verify:

```bash
aws s3api get-bucket-lifecycle-configuration \
    --endpoint-url "$R2_ENDPOINT" \
    --bucket "$R2_BUCKET"
```

### 4.2 — Weekly + monthly archive

The lifecycle rule above only handles dailies. To populate `archive/weekly/`
and `archive/monthly/`, extend `infra/backup/backup.sh` to additionally
copy:

- Every Sunday's dump → `archive/weekly/YYYY-WW.sql.gz`
- Every 1st-of-month dump → `archive/monthly/YYYY-MM.sql.gz`

This is a future-PR follow-up, not blocking. The dailies-only retention
above is correct and safe; the weekly/monthly archive is "nice to have"
once we want >7-day rollback windows.

### 4.3 — Retention math (sanity)

| Window | Source | Lifecycle | Result |
|---|---|---|---|
| 0–7 days | `backups/YYYY/MM/DD/` | Expire after 7 days | 7 dailies live |
| 7–35 days | `archive/weekly/` (future) | Expire after 35 days | 4 weeklies |
| 35–100 days | `archive/monthly/` (future) | Expire after 100 days | 3 monthlies |
| Steady state | sum | — | 7 + 4 + 3 = **14 objects** |

---

## 5 — Common failures

| Symptom | Cause | Fix |
|---|---|---|
| `aws s3 cp` returns "AccessDenied" | R2 token doesn't have read on the bucket | Generate a new R2 API token scoped to the bucket. |
| `psql: error: connection to server … failed: SSL connection has been closed unexpectedly` | Neon free-tier branch hit idle timeout mid-restore | Re-run with `--set ON_ERROR_STOP=1` and Neon will restart the compute on demand. |
| `ERROR:  permission denied for schema public` | The dump was taken with `--no-owner --no-privileges` but the restore role lacks CREATE | Run `GRANT CREATE ON SCHEMA public TO <role>;` on the restore branch. |
| Restored DB has no rows | `pg_dump` ran while the Neon branch was paused | Re-take the backup — Neon's free-tier compute auto-suspends after 5 min idle, and a backup against a suspended compute can return an empty schema. |
| Contract tests fail with "column does not exist" | Schema migration shipped after the backup; restored DB is one rev behind | Run `alembic upgrade head` against the restore branch. |

---

## 6 — Drill log

Append a one-liner here every drill. (Last 12 months only — older entries
prune to keep this file readable.)

```
YYYY-MM-DD   <name>   restored from <backup key>   contract tests: PASS/FAIL   notes
```

| Date | Operator | Backup key | Result | Notes |
|---|---|---|---|---|
| (first drill pending) | | | | Initial drill scheduled for first 1st-of-month after D1.1 deploys. |
