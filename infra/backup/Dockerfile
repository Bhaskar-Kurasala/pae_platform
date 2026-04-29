# PR3/D1.1 — Nightly Postgres backup machine.
#
# Runs as a Fly.io scheduled machine (see fly-backup.toml). On boot:
#   1. pg_dump the Neon database (custom-format, parallel-safe)
#   2. gzip on the fly
#   3. stream to Cloudflare R2 via the AWS CLI (R2 is S3-compatible)
#   4. exit 0 → Fly stops the machine until the next scheduled run.
#
# Image is intentionally tiny — Alpine + pg client + aws-cli + bash.
# We pin the postgres-client major version to 16 to match Neon's prod tier
# (Neon's wire protocol is compatible across minor versions; pg_dump must
# be >= the server version).
FROM alpine:3.19

# Install Postgres 16 client + AWS CLI v2 + tooling.
# `aws-cli` on Alpine is the v1 build; we install via pip to get v2 which
# supports `--endpoint-url` consistently for R2.
RUN apk add --no-cache \
        postgresql16-client=~16 \
        bash \
        ca-certificates \
        curl \
        coreutils \
        py3-pip \
        gzip \
    && pip3 install --no-cache-dir --break-system-packages awscli==1.* \
    && rm -rf /var/cache/apk/*

# Run as a non-root user. The backup script doesn't need any persistent
# disk — everything streams through stdout to the AWS CLI.
RUN addgroup -S backup && adduser -S backup -G backup
USER backup
WORKDIR /home/backup

COPY --chown=backup:backup backup.sh /home/backup/backup.sh
RUN chmod +x /home/backup/backup.sh

# Fly's scheduled machines invoke the entrypoint and stop the machine on
# exit. ENTRYPOINT (not CMD) so users can't accidentally override the
# script with `fly machine run … <cmd>`.
ENTRYPOINT ["/home/backup/backup.sh"]
