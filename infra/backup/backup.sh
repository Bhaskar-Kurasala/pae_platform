#!/usr/bin/env bash
# PR3/D1.1 — Nightly pg_dump → gzip → Cloudflare R2.
#
# Invoked by the Fly scheduled machine (fly-backup.toml schedule = "daily").
# Exits 0 on success so Fly stops the machine cleanly.
#
# Required environment (set as Fly secrets on the backup app):
#   NEON_DATABASE_URL          - postgres://user:pass@host/db (the prod Neon URL)
#   R2_ACCOUNT_ID              - Cloudflare account id (from R2 dashboard)
#   R2_ACCESS_KEY_ID           - R2 API token's access key
#   R2_SECRET_ACCESS_KEY       - R2 API token's secret key
#   R2_BUCKET                  - bucket name (e.g. "pae-backups")
#
# Optional:
#   R2_PREFIX                  - object prefix (default: "backups")
#   PGDUMP_EXTRA_ARGS          - extra args to pg_dump (e.g. "--exclude-schema=audit")

set -euo pipefail

# ── Required env validation ────────────────────────────────────────────────
: "${NEON_DATABASE_URL:?NEON_DATABASE_URL is required}"
: "${R2_ACCOUNT_ID:?R2_ACCOUNT_ID is required}"
: "${R2_ACCESS_KEY_ID:?R2_ACCESS_KEY_ID is required}"
: "${R2_SECRET_ACCESS_KEY:?R2_SECRET_ACCESS_KEY is required}"
: "${R2_BUCKET:?R2_BUCKET is required}"

R2_PREFIX="${R2_PREFIX:-backups}"
PGDUMP_EXTRA_ARGS="${PGDUMP_EXTRA_ARGS:-}"

# ── Output object key ──────────────────────────────────────────────────────
# Format: backups/2026/04/29/pae-20260429-040000.sql.gz
# The year/month/day prefixes make R2 lifecycle rules + console browsing
# painless, and let us answer "show me April's backups" with one ListObjects.
TS="$(date -u +%Y%m%d-%H%M%S)"
YEAR="$(date -u +%Y)"
MONTH="$(date -u +%m)"
DAY="$(date -u +%d)"
OBJECT_KEY="${R2_PREFIX}/${YEAR}/${MONTH}/${DAY}/pae-${TS}.sql.gz"

# ── AWS CLI config for R2 ──────────────────────────────────────────────────
# R2 is S3-compatible but uses a per-account endpoint URL. We don't write
# ~/.aws/credentials — feed everything via env so secrets never touch disk.
export AWS_ACCESS_KEY_ID="${R2_ACCESS_KEY_ID}"
export AWS_SECRET_ACCESS_KEY="${R2_SECRET_ACCESS_KEY}"
export AWS_DEFAULT_REGION="auto"

R2_ENDPOINT="https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com"

echo "[backup] start ts=${TS} target=s3://${R2_BUCKET}/${OBJECT_KEY}"

# ── pg_dump → gzip → R2 ────────────────────────────────────────────────────
# Plain SQL format (not custom) so a teammate can `gunzip | psql` to restore
# without needing pg_restore. The trade-off vs custom-format is no parallel
# restore, but Neon's free-tier dataset restores in well under the 15-min
# drill SLA in docs/runbooks/restore.md.
#
# `--no-owner --no-privileges` strips role/grant statements that would fail
# against a fresh Neon branch where the role names differ.
#
# `set -o pipefail` (above) ensures pg_dump's exit code propagates through
# the gzip and aws cp pipeline.
# shellcheck disable=SC2086  # PGDUMP_EXTRA_ARGS is intentionally word-split
pg_dump \
    --no-owner \
    --no-privileges \
    --format=plain \
    --quote-all-identifiers \
    ${PGDUMP_EXTRA_ARGS} \
    "${NEON_DATABASE_URL}" \
  | gzip --best \
  | aws s3 cp \
        --endpoint-url "${R2_ENDPOINT}" \
        --expected-size 1073741824 \
        - "s3://${R2_BUCKET}/${OBJECT_KEY}"

# ── Verify the object landed ───────────────────────────────────────────────
# `aws s3api head-object` returns the size + etag; we log the size so the
# next morning's grep across Fly logs gives us a quick "did it grow or
# shrink?" signal without listing the bucket.
SIZE_BYTES="$(aws s3api head-object \
    --endpoint-url "${R2_ENDPOINT}" \
    --bucket "${R2_BUCKET}" \
    --key "${OBJECT_KEY}" \
    --query "ContentLength" \
    --output text)"

echo "[backup] success ts=${TS} object=${OBJECT_KEY} size_bytes=${SIZE_BYTES}"
