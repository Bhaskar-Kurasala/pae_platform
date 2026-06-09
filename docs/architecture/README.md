# Architecture Decision Documents

This directory contains the architectural decision history for AICareerOS. Documents are numbered as "Pass" deliverables — each one a discrete decision point that builds on the previous.

## Reading order

1. **`docs/audits/pass-1-ground-truth.md`** — Structural snapshot of the codebase as of the audit. Observations only.
2. **`docs/audits/pass-2-hypothesis-verification.md`** — Five hypotheses about whether the codebase implements an "OS of learning." Code-level evidence.
3. **`pass-3a-agent-inventory.md`** — Original 24-agent roster. ⚠️ Superseded by the addendum but preserved for decision history.
4. **`pass-3a-addendum-after-d8.md`** — Corrected 16-agent roster after D1–D8 reconciliation. **This is the canonical agent contract.**
5. **`pass-3b-...`** — Supervisor agent design (forthcoming).
6. **`pass-3c-...` through `pass-3l-...`** — Subsequent architecture passes (forthcoming).

## Status reference

| Pass | Status | Document |
|---|---|---|
| Pass 1 | Final | `../audits/pass-1-ground-truth.md` |
| Pass 2 | Final | `../audits/pass-2-hypothesis-verification.md` |
| Pass 3a | Superseded | `pass-3a-agent-inventory.md` |
| Pass 3a Addendum | **Final — canonical** | `pass-3a-addendum-after-d8.md` |
| Pass 3b | In progress | (drafting) |
| Pass 3c–3l | Not started | — |

## Companion documents

- `../AGENTIC_OS.md` — Architecture document for the agentic OS layer (D1–D8 foundation). Backwards-looking; describes what's built.
- `../audits/track-6-baseline.md` — Verification baseline at end of parallel cleanup workstream.
- `../followups/` — Open and resolved follow-ups, including known bugs (e.g., `agentic-loader-fastapi-startup.md` — P0).
