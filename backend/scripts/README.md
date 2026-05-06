# backend/scripts/

One-off tooling scripts for migrations, seeding, and verification. Run
from inside the backend container:

    docker compose exec backend uv run python /app/scripts/<script>.py [args]

## Seed scripts

| Script | Purpose |
|---|---|
| `seed_admin_console.py` | Seeds an admin user + course catalog for local dev. |
| `seed_catalog_tracks.sql` | Catalog tracks fixture (raw SQL). |
| `seed_e2e_courses.sql` | Course fixtures for E2E tests (raw SQL). |
| `seed_e2e_exercises.sql` | Exercise fixtures for E2E tests (raw SQL). |
| `seed_e2e_receipts.sql` | Receipt fixtures for E2E tests (raw SQL). |
| `seed_high_impact_exercises.sql` | Curated capstone-tier exercises (raw SQL). |

## D12 CP3 verification harness scripts

These were the verification scripts produced during D12 CP3 (career
bundle migration). They remain in the repo as reusable templates for
D13+ migrations per the protocol documented at
[docs/followups/migration-verification-discipline.md](../../docs/followups/migration-verification-discipline.md).

| Script | Purpose |
|---|---|
| `d12_cp3_real_llm_smoke.py` | Full Stage 4.1 smoke: 4 individual agent calls + 1 chain dispatch via `/api/v1/agentic/default/chat`. Seeds a test user with `admin_grant` entitlement, mints JWT, fires real-MiniMax calls, captures `agent_actions` rows + `agent_invocation_log` rows + cost. |
| `d12_cp3_phase4_individual_call.py` | Single-agent verification harness (parameterized via `--agent <name>`). Used in D12 CP3 Stage 4.3 for per-agent verification. **Reuse for D13+**: extend the `MESSAGES` dict with the new agent's diagnostic input; run `--agent <newagent>`. |
| `d12_cp3_phase2_diagnose_llm.py` | Pure-LLM diagnostic harness (bypasses orchestrator, safety, dispatch). Used in D12 CP3 Phase 2 to surface Bug 10 (parser dict-block handling) and pin the prompt rewrite (Bug 10b). Run when an agent's full path can't complete and you need to isolate LLM-side behavior. |
| `d12_cp3_phase4_career_coach_pure_llm.py` | Career-coach-specific pure-LLM probe with SDK-timeout override (180s wall clock). Used in D12 CP3 Phase 4 to measure career_coach P50 latency under MiniMax (45.4s observed). |

D13+ migrations should:

1. Reuse `d12_cp3_real_llm_smoke.py` and `d12_cp3_phase4_individual_call.py` patterns.
2. Adapt the diagnostic harnesses if the new agent's structural shape differs (multi-turn, persistent state, etc.).
3. Keep new verification scripts in this directory with the same `dN_cpX_<phase>_<purpose>.py` naming convention.
