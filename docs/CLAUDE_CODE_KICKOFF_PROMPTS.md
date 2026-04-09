# Claude Code Kickoff Prompts
## Copy-paste these into Claude Code — one phase at a time

---

## PHASE 0: Foundation (Run first — once only)

```
Read CLAUDE.md, then read every file in .claude/ directory (settings.json, all skills, all agents, all commands, all rules). Understand the complete platform architecture from docs/ARCHITECTURE.md and README.md.

Then execute Phase 0 — Foundation scaffolding. Do everything below autonomously. Do not ask me questions — make reasonable decisions and document them.

BACKEND:
1. cd backend && uv init --python 3.12
2. Add all dependencies from CLAUDE.md and backend/CLAUDE.md (fastapi, uvicorn, sqlalchemy, alembic, celery, redis, langchain, langgraph, anthropic, pydantic-settings, python-jose, httpx, tenacity, structlog, python-multipart, sendgrid, stripe, pygithub, pytest, pytest-asyncio, pytest-cov, ruff, mypy)
3. Create the full app/ directory structure: app/__init__.py, app/main.py (FastAPI app factory with CORS, health endpoint, router includes), app/core/config.py (Pydantic Settings loading from .env), app/core/database.py (async SQLAlchemy engine + session dependency), app/core/redis.py (Redis connection pool), app/core/security.py (JWT creation + verification + get_current_user dependency), app/core/celery_app.py (Celery config)
4. Create all SQLAlchemy models in app/models/ — users, courses, lessons, exercises, enrollments, student_progress, exercise_submissions, quiz_results, mcq_bank, agent_actions, payments, notifications (all with UUID PKs, created_at, updated_at, soft delete)
5. Create Pydantic schemas in app/schemas/ for every model (Create, Update, Response variants)
6. Initialize Alembic, configure for async, create initial migration, apply it
7. Create base repository pattern in app/repositories/base.py (generic async CRUD)
8. Create app/agents/base_agent.py with the BaseAgent abstract class from the agent-developer skill
9. Create tests/conftest.py with async test client fixture and test database
10. Create a basic test: tests/test_api/test_health.py that hits GET /health
11. Run: uv run ruff check . && uv run mypy app/ && uv run pytest -x

FRONTEND:
1. cd frontend (if not already created by create-next-app, run: pnpx create-next-app@latest . --typescript --tailwind --eslint --app --src-dir --import-alias '@/*')
2. Install: pnpm add @tanstack/react-query zustand lucide-react recharts openapi-fetch
3. Install dev: pnpm add -D vitest @testing-library/react @testing-library/jest-dom jsdom
4. Run: npx shadcn@latest init (use defaults), then add: button card dialog input label select tabs toast avatar badge separator dropdown-menu sheet
5. Create src/lib/api-client.ts — placeholder that will be generated from OpenAPI schema
6. Create src/stores/auth-store.ts — Zustand store for auth state
7. Create src/components/layouts/portal-layout.tsx — sidebar + main content layout
8. Create src/components/layouts/admin-layout.tsx — admin sidebar layout
9. Create src/app/(public)/page.tsx — simple landing page placeholder
10. Create src/app/(public)/layout.tsx — public layout (no sidebar)
11. Create src/app/(portal)/layout.tsx — portal layout with auth check
12. Create src/app/(portal)/dashboard/page.tsx — placeholder dashboard
13. Create vitest.config.ts and a basic test
14. Run: pnpm lint && pnpm test && pnpm build

DOCKER:
1. Create backend/Dockerfile (Python 3.12 slim, uv, gunicorn+uvicorn)
2. Create frontend/Dockerfile (node 22 alpine, multi-stage build)
3. Verify docker-compose.yml is correct
4. Run: docker compose build

VALIDATION (must all pass before you stop):
- cd backend && uv run ruff check . → 0 errors
- cd backend && uv run mypy app/ → 0 errors
- cd backend && uv run pytest -x → all pass
- cd frontend && pnpm lint → 0 errors
- cd frontend && pnpm test → all pass
- cd frontend && pnpm build → success
- docker compose build → success
- git add -A && git commit -m "chore: Phase 0 — complete foundation scaffolding"

If any validation fails, fix it before moving on. Do not stop until all validations pass.
```

---

## PHASE 1: Auth + Core API (Run after Phase 0 passes)

```
Read CLAUDE.md and backend/CLAUDE.md. You completed Phase 0 — the foundation is scaffolded. Now implement Phase 1 autonomously. Do not ask questions.

1. AUTH SYSTEM:
   - Create app/api/v1/routes/auth.py: POST /register, POST /login (JWT), GET /me
   - Create app/services/auth_service.py with password hashing (passlib bcrypt), JWT creation, user lookup
   - Create app/repositories/user_repo.py with async create, find_by_email, find_by_id
   - Write tests: tests/test_api/test_auth.py — test register, login, get current user, invalid token

2. COURSE + LESSON API:
   - Create app/api/v1/routes/courses.py: GET /courses, GET /courses/:id, POST /courses (admin), PUT /courses/:id (admin)
   - Create app/api/v1/routes/lessons.py: GET /courses/:id/lessons, GET /lessons/:id
   - Create services and repositories for both
   - Write tests for all endpoints

3. STUDENT PROGRESS API:
   - Create app/api/v1/routes/students.py: GET /students/me/progress, POST /lessons/:id/complete
   - Track lesson completion, time spent
   - Write tests

4. EXERCISE SUBMISSION API:
   - Create app/api/v1/routes/exercises.py: GET /exercises, GET /exercises/:id, POST /exercises/:id/submit
   - Write tests

5. WEBHOOK ENDPOINTS:
   - Create app/api/v1/routes/webhooks.py: POST /webhooks/github, POST /webhooks/stripe (signature verification, placeholder handlers)
   - Write tests

6. Wire all routers into app/main.py with /api/v1 prefix

7. Create new Alembic migration if any model changes were needed, apply it

8. Generate OpenAPI schema: curl http://localhost:8000/openapi.json > frontend/src/types/openapi.json

VALIDATION (must all pass):
- uv run ruff check . → 0 errors
- uv run mypy app/ → 0 errors
- uv run pytest -x -v → all pass, >80% coverage on new code
- All endpoints visible at http://localhost:8000/docs
- git add -A && git commit -m "feat: Phase 1 — auth, courses, lessons, exercises, webhooks API"
```

---

## PHASE 2: Frontend Student Portal (Run after Phase 1 passes)

```
Read CLAUDE.md and frontend/CLAUDE.md. Phase 1 API is complete. Now build the frontend autonomously. Do not ask questions.

Use shadcn/ui components, Tailwind CSS, the design tokens from the UX skill (teal #1D9E75, purple #7C3AED, dark #111827). Use React Query for server state. Use the API client to hit the FastAPI backend.

1. PUBLIC PAGES:
   - src/app/(public)/page.tsx — Landing page: hero section with tagline "Production AI Engineering", pipeline diagram placeholder, email capture form, free content CTA
   - src/app/(public)/login/page.tsx — Login form (email + password)
   - src/app/(public)/register/page.tsx — Registration form
   - src/app/(public)/courses/page.tsx — Public course listing (cards grid)

2. STUDENT PORTAL:
   - src/app/(portal)/dashboard/page.tsx — Welcome message, progress overview (progress bars per course), recent activity list, "Continue Learning" button linking to next incomplete lesson
   - src/app/(portal)/courses/[id]/page.tsx — Course detail: title, description, lesson list with completion checkmarks, overall progress bar
   - src/app/(portal)/lessons/[id]/page.tsx — Lesson view: YouTube video embed (iframe), code viewer below (use a <pre><code> block with syntax highlighting via shiki or highlight.js), mark complete button, prev/next navigation
   - src/app/(portal)/exercises/page.tsx — Exercise list with status badges (not started / submitted / graded)
   - src/app/(portal)/exercises/[id]/page.tsx — Exercise detail: instructions, code editor (textarea for now, Monaco later), submit button, grade display if graded
   - src/app/(portal)/progress/page.tsx — Progress dashboard: completion chart (Recharts bar chart), skill breakdown, time spent stats

3. LAYOUTS:
   - src/components/layouts/portal-layout.tsx — Left sidebar (Dashboard, Courses, Exercises, Progress, Chat, Settings), top bar with user avatar + logout, mobile-responsive (sidebar collapses to hamburger)
   - src/components/layouts/public-layout.tsx — Simple header with logo + Login/Register buttons

4. SHARED COMPONENTS:
   - src/components/features/course-card.tsx — Card with title, description, progress bar, lesson count
   - src/components/features/lesson-item.tsx — List item with title, duration, completion check
   - src/components/features/progress-bar.tsx — Animated progress bar with percentage label
   - src/components/features/user-avatar.tsx — Avatar with fallback initials

5. API INTEGRATION:
   - src/lib/api-client.ts — fetch wrapper with JWT token from auth store, base URL from env
   - src/lib/hooks/use-courses.ts — useQuery hooks for courses, lessons
   - src/lib/hooks/use-progress.ts — useQuery/useMutation for progress tracking
   - src/stores/auth-store.ts — Update with login/logout/token management

6. AUTH FLOW:
   - Login page calls POST /api/v1/auth/login, stores JWT in Zustand + localStorage
   - Portal layout checks auth state, redirects to /login if not authenticated
   - API client attaches Authorization: Bearer header to all requests

7. Add loading.tsx skeleton files for portal pages
8. Add error.tsx boundary files for portal pages

VALIDATION:
- pnpm lint → 0 errors
- pnpm test → all pass
- pnpm build → success
- Manually verify: open http://localhost:3000, register, login, see dashboard, browse courses
- git add -A && git commit -m "feat: Phase 2 — complete student portal frontend"
```

---

## PHASE 3: Agent Framework + First 3 Agents (Run after Phase 2 passes)

```
Read CLAUDE.md, backend/CLAUDE.md, and .claude/skills/agent-developer/SKILL.md. Now build the AI agent framework and first 3 agents autonomously. Do not ask questions.

1. AGENT FRAMEWORK:
   - Verify app/agents/base_agent.py has: AgentState (Pydantic model), BaseAgent (abstract class with execute, evaluate, log_action methods)
   - Create app/agents/registry.py — AGENT_REGISTRY dict mapping agent names to classes, get_agent() function
   - Create app/agents/moa.py — Master Orchestrator Agent using LangGraph StateGraph: receives student request → classifies intent → routes to appropriate agent → evaluates response → returns to student
   - Create app/services/agent_orchestrator.py — Service that wraps MOA, manages conversation history in Redis, logs to agent_actions table

2. SOCRATIC TUTOR AGENT:
   - Create app/agents/socratic_tutor.py — extends BaseAgent
   - Create app/agents/prompts/socratic_tutor.md — system prompt: "You are a Socratic tutor. Never give direct answers. Guide students through questions. Use their knowledge level from context. Be warm and encouraging."
   - Tools: search_course_content (RAG query to Pinecone — stub for now, return mock content), get_student_progress
   - Evaluation: response must contain at least one question mark

3. CODE REVIEW AGENT:
   - Create app/agents/code_review.py — extends BaseAgent
   - Create app/agents/prompts/code_review.md — system prompt for production code review
   - Tools: analyze_code (runs ruff + basic checks on submitted code string)
   - Returns: structured feedback with inline comments, quality score 0-100

4. ADAPTIVE QUIZ AGENT:
   - Create app/agents/adaptive_quiz.py — extends BaseAgent
   - Create app/agents/prompts/adaptive_quiz.md
   - Pulls questions from mcq_bank, adjusts difficulty based on student performance
   - Returns: next question with options, or quiz summary if complete

5. CHAT API:
   - Create app/api/v1/routes/agents.py: POST /agents/chat (accepts: agent_name, message, conversation_id)
   - Connects to agent_orchestrator service
   - Returns: agent response, agent_name that handled it, evaluation_score

6. AGENT CHAT FRONTEND:
   - Create src/app/(portal)/chat/page.tsx — Chat interface: message list, input box, send button, agent name display above each response
   - Create src/components/features/chat-message.tsx — Message bubble (user vs agent styling)
   - Create src/lib/hooks/use-agent-chat.ts — useMutation for sending messages

7. TESTS:
   - tests/test_agents/test_base_agent.py — Test AgentState, BaseAgent contract
   - tests/test_agents/test_socratic_tutor.py — Mock LLM, verify Socratic behavior
   - tests/test_agents/test_code_review.py — Mock LLM, verify review format
   - tests/test_agents/test_adaptive_quiz.py — Mock LLM, verify quiz flow
   - tests/test_api/test_agents.py — Test chat endpoint

VALIDATION:
- uv run ruff check . && uv run mypy app/ → 0 errors
- uv run pytest -x -v → all pass
- pnpm lint && pnpm build → success
- Test manually: login → go to Chat → select Socratic Tutor → ask "What is RAG?" → get guided question back
- git add -A && git commit -m "feat: Phase 3 — agent framework, MOA, socratic tutor, code review, adaptive quiz"
```

---

## PHASE 4: Remaining Agents + Admin (Run after Phase 3 passes)

```
Read CLAUDE.md and .claude/skills/agent-developer/SKILL.md. Agent framework is working with 3 agents. Now add the remaining agents and admin dashboard autonomously. Do not ask questions. For agents that need external APIs not yet configured (YouTube, Stripe, job boards), create the agent with stubbed tool implementations that return mock data — mark each stub with # TODO: connect real API.

1. CREATION AGENTS (add to app/agents/):
   - content_ingestion.py — Stub: accepts YouTube URL or GitHub commit, returns structured metadata
   - curriculum_mapper.py — Stub: accepts content metadata, returns learning path updates
   - mcq_factory.py — Generates MCQs from content using Claude API (this one should work for real with the Anthropic API)
   - coding_assistant.py — Reviews code submissions, returns PR-style comments
   - student_buddy.py — Short focused explanations based on student context
   - deep_capturer.py — Stub: generates weekly insight connecting concepts

2. LEARNING AGENTS:
   - spaced_repetition.py — Implements SM-2 algorithm, queries mcq_bank for due reviews
   - knowledge_graph.py — Stub: updates student concept mastery in JSONB column
   - adaptive_path.py — Adjusts learning path based on quiz scores

3. ANALYTICS AGENTS:
   - project_evaluator.py — Evaluates capstone submissions against rubric
   - progress_report.py — Generates weekly progress summary

4. CAREER AGENTS:
   - mock_interview.py — System design interview simulation using Claude API
   - portfolio_builder.py — Generates markdown portfolio from completed projects
   - job_match.py — Stub: returns mock job listings

5. ENGAGEMENT AGENTS:
   - disrupt_prevention.py — Checks student activity, generates re-engagement messages
   - peer_matching.py — Stub: matches students by skill level
   - community_celebrator.py — Generates celebration messages for milestones

6. Register ALL agents in app/agents/registry.py
7. Update MOA routing logic to handle all agent categories

8. ADMIN DASHBOARD (frontend):
   - src/app/(admin)/layout.tsx — Admin layout with admin sidebar
   - src/app/(admin)/page.tsx — Overview: total students, MRR, active agents, recent activity
   - src/app/(admin)/agents/page.tsx — Agent monitor: list of all agents, status, total actions, avg cost, avg eval score
   - src/app/(admin)/students/page.tsx — Student list with search, engagement scores
   - Create admin API routes: GET /admin/stats, GET /admin/agents/health, GET /admin/students

9. Write at least one test per new agent (mock LLM)

VALIDATION:
- uv run ruff check . && uv run mypy app/ → 0 errors
- uv run pytest -x → all pass
- pnpm lint && pnpm build → success
- All agents registered and accessible via POST /agents/chat
- Admin dashboard renders with mock data
- git add -A && git commit -m "feat: Phase 4 — all 18 agents, admin dashboard, agent monitoring"
```

---

## PHASE 5: Polish + Docker + CI (Run last)

```
Read CLAUDE.md. All features are built. Now polish, optimize, and prepare for deployment. Do not ask questions.

1. DOCKER VERIFICATION:
   - Ensure all Dockerfiles build correctly
   - docker compose up -d --build
   - docker compose exec backend uv run alembic upgrade head
   - Verify all health checks pass
   - Run backend tests inside container: docker compose exec backend uv run pytest -x

2. CI/CD:
   - Verify .github/workflows/ci.yml is correct
   - Run the same commands locally that CI would run
   - Fix any issues

3. SECURITY:
   - Grep for any hardcoded secrets: grep -rn "sk-\|api_key\s*=\s*['\"]" backend/ frontend/
   - Verify .env.example has no real values
   - Verify .gitignore includes .env
   - Add rate limiting to auth endpoints (slowapi or custom)
   - Add CORS configuration to FastAPI (allow frontend origin only)

4. PERFORMANCE:
   - Add database indexes on frequently queried columns (user email, course slug, lesson order)
   - Add Redis caching for course listings (5 min TTL)
   - Frontend: verify next.config.js has image optimization configured

5. DOCUMENTATION:
   - Update docs/ARCHITECTURE.md with final state
   - Create docs/AGENTS.md listing all agents with their triggers and tools
   - Create docs/API.md with all endpoints (or just reference /docs)
   - Update README.md with final setup instructions
   - Verify docs/lessons.md has any lessons learned during development

6. FINAL VALIDATION (every single one must pass):
   - cd backend && uv run ruff check . → 0 errors
   - cd backend && uv run mypy app/ → 0 errors
   - cd backend && uv run pytest --cov=app --cov-report=term-missing → >80% coverage
   - cd frontend && pnpm lint → 0 errors
   - cd frontend && pnpm test → all pass
   - cd frontend && pnpm build → success
   - docker compose build → success
   - docker compose up -d && sleep 10 && curl -sf http://localhost:8000/health → ok
   - git add -A && git commit -m "chore: Phase 5 — polish, security, performance, documentation"

Print a final summary of: total files, test count, test coverage, agent count, endpoint count, and any remaining TODOs.
```

---

## HOW TO USE THESE PROMPTS

1. Extract platform-config-files.tar.gz into your project folder
2. Install plugins: `claude /plugin install superpowers` + `npx get-shit-done-cc@latest`
3. Open Claude Code: `claude`
4. Copy-paste PHASE 0 prompt → wait for completion → verify all validations pass
5. Run `/clear` to reset context
6. Copy-paste PHASE 1 prompt → wait → verify
7. `/clear`
8. Continue through each phase
9. After Phase 5, you have a production-ready platform

IMPORTANT:
- Always /clear between phases (prevents context overflow)
- If Claude gets stuck or errors out mid-phase, just re-run the same phase prompt — it will pick up where it left off because git tracks progress
- For parallel development, use worktrees: `claude --worktree phase-3-agents` in a separate terminal
- Each phase takes ~15-30 minutes of Claude Code time

---

# Phase 6: QA Testing with Playwright — Claude Code Prompt

## Copy this entire prompt into Claude Code after ensuring:
## 1. Docker stack is running: `docker compose up -d`
## 2. Playwright MCP is installed: `claude plugins add playwright@claude-plugins-official`
## 3. Database is migrated: `docker compose exec backend uv run alembic upgrade head`

---

```
Read CLAUDE.md and docs/PRD_QA_TestSpec.docx (or the PRD_QA_TestSpec.md summary below). 
This is Phase 6 — comprehensive QA testing of the running application.

You are now a Senior QA Engineer. Your job is to test every user journey against the RUNNING application at http://localhost:3000 (frontend) and http://localhost:8000 (backend). You will use Playwright to interact with the real browser UI and httpx/curl to test API contracts directly.

DO NOT modify application code during testing. Only observe, test, and report.

## STEP 1: SEED TEST DATA

Before testing, seed the database with test data by running these API calls:

```bash
# Create admin user
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"name": "Admin User", "email": "admin@test.com", "password": "AdminPass123!"}'

# Manually update role to admin (or use a seed script)
docker compose exec backend uv run python -c "
from app.core.database import get_sync_session
from app.models.user import User
session = next(get_sync_session())
user = session.query(User).filter_by(email='admin@test.com').first()
if user: user.role = 'admin'; session.commit(); print('Admin role set')
"

# Create student user
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"name": "Test Student", "email": "student@test.com", "password": "StudentPass123!"}'

# Create a second student (for data isolation tests)
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"name": "Student Two", "email": "student2@test.com", "password": "StudentPass123!"}'

# Login as admin and get token
ADMIN_TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@test.com", "password": "AdminPass123!"}' | jq -r '.access_token')

# Create a test course with 10 lessons
COURSE_ID=$(curl -s -X POST http://localhost:8000/api/v1/courses \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d '{"title": "Production RAG Engineering", "slug": "production-rag", "description": "Build production RAG systems from scratch", "is_published": true, "price_cents": 899900}' | jq -r '.id')

# Create 10 lessons
for i in $(seq 1 10); do
  curl -s -X POST http://localhost:8000/api/v1/courses/$COURSE_ID/lessons \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -d "{\"title\": \"Lesson $i: Pipeline Stage $i\", \"order\": $i, \"video_url\": \"https://youtube.com/watch?v=lesson$i\", \"content_md\": \"# Lesson $i\\n\\nThis is lesson $i content with code examples.\\n\\n\\\`\\\`\\\`python\\nprint('hello from lesson $i')\\n\\\`\\\`\\\`\", \"commit_sha\": \"abc${i}def\"}"
done

# Create 3 exercises
for i in $(seq 1 3); do
  curl -s -X POST http://localhost:8000/api/v1/exercises \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -d "{\"title\": \"Exercise $i: Build a component\", \"lesson_id\": \"LESSON_${i}_ID\", \"instructions\": \"Build a production-ready component for pipeline stage $i.\", \"starter_code\": \"def solution():\\n    # Your code here\\n    pass\", \"test_code\": \"assert solution() is not None\", \"difficulty\": $i}"
done

# Enroll student in the course
STUDENT_TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "student@test.com", "password": "StudentPass123!"}' | jq -r '.access_token')

# Create enrollment (direct DB or via API)
curl -s -X POST http://localhost:8000/api/v1/courses/$COURSE_ID/enroll \
  -H "Authorization: Bearer $STUDENT_TOKEN"

# Complete first 2 lessons for student (to have some progress)
curl -s -X POST http://localhost:8000/api/v1/lessons/LESSON_1_ID/complete \
  -H "Authorization: Bearer $STUDENT_TOKEN"
curl -s -X POST http://localhost:8000/api/v1/lessons/LESSON_2_ID/complete \
  -H "Authorization: Bearer $STUDENT_TOKEN"
```

IMPORTANT: The seed script above is a template. Adapt the actual endpoint paths and payload fields to match your real API (check http://localhost:8000/docs for the actual schema). If endpoints don't exist (e.g., POST /courses/{id}/enroll), note this as a MISSING ENDPOINT finding.

## STEP 2: RUN E2E TESTS WITH PLAYWRIGHT

Use Playwright MCP to test each flow in a real browser. For each test case below, navigate to the page, interact with it, observe the result, take a screenshot if something fails, and record PASS/FAIL with details.

### Authentication Tests (TC-001 through TC-009)

TEST AUTH-001: Register new student
- Open http://localhost:3000/register
- Fill: name="QA Tester", email="qa@test.com", password="QAPass123!", confirm="QAPass123!"
- Click submit
- VERIFY: redirect to /portal/dashboard, welcome message contains "QA Tester"
- Take screenshot

TEST AUTH-002: Login with valid credentials
- Open http://localhost:3000/login
- Fill: email="student@test.com", password="StudentPass123!"
- Click submit
- VERIFY: redirect to /portal/dashboard, user name visible in nav

TEST AUTH-003: Login with wrong password
- Open http://localhost:3000/login
- Fill: email="student@test.com", password="WrongPassword"
- Click submit
- VERIFY: error message shown, stays on /login, email field NOT cleared

TEST AUTH-005: Access portal without login
- Clear all cookies/localStorage
- Navigate to http://localhost:3000/portal/dashboard
- VERIFY: redirects to /login

TEST AUTH-006: Access admin as non-admin
- Login as student@test.com
- Navigate to http://localhost:3000/admin
- VERIFY: either redirect to portal or 403 message shown, admin data NOT accessible

### Course & Learning Tests (TC-010 through TC-020)

TEST COURSE-001: View published courses
- Navigate to http://localhost:3000/courses
- VERIFY: "Production RAG Engineering" course card visible, shows lesson count

TEST LEARN-001: Mark lesson complete updates progress
- Login as student@test.com
- Navigate to course page, then to lesson 3
- Click "Mark Complete"
- Navigate back to dashboard
- VERIFY: progress shows 3/10 (30%), not 2/10

TEST LEARN-002: Progress percentage accuracy
- On dashboard, check the progress percentage
- VERIFY: shows exactly 30% (if 3 of 10 complete), not 0%, not 100%

TEST LEARN-004: Continue Learning points to correct lesson
- On dashboard, find "Continue Learning" button
- VERIFY: it links to lesson 4 (the first incomplete lesson), not lesson 1

### Exercise Tests (TC-021 through TC-025)

TEST EX-001: Submit exercise
- Navigate to an exercise page
- Type solution code in editor
- Click Submit
- VERIFY: status changes to "Submitted", loading spinner shown during submit

TEST EX-002: Empty submission validation
- Navigate to exercise page
- Clear the editor
- Click Submit
- VERIFY: error message shown, no API call made

### Agent Chat Tests (TC-026 through TC-030)

TEST AGENT-001: Socratic Tutor responds
- Navigate to /portal/chat
- Type "What is RAG?" and send
- VERIFY: response appears, labeled "Socratic Tutor", contains a question (?)

TEST AGENT-003: Agent error handling
- (If possible to simulate API failure) send a message
- VERIFY: graceful error message, not a crash

### Visual & UX Tests (TC-031 through TC-035)

TEST VIS-002: Empty state for new student
- Login as student2@test.com (no enrollments)
- Navigate to /portal/dashboard
- VERIFY: shows empty state message like "No courses enrolled", NOT blank page, NOT "undefined"

TEST VIS-004: Error handling on API failure
- Navigate to a portal page while backend is healthy
- Note the normal state
- Then test: navigate to /portal/courses/99999 (non-existent)
- VERIFY: 404 message shown, not a crash

### Admin Tests

TEST ADMIN-001: Admin dashboard accessible
- Login as admin@test.com
- Navigate to /admin
- VERIFY: metric cards shown (total students, etc.)

TEST ADMIN-002: Agent monitor shows data
- Navigate to /admin/agents
- VERIFY: table of agents with action counts (at least 1 if agent chat was tested)

## STEP 3: API CONTRACT TESTS

Run these directly with curl/httpx (not through browser):

```bash
# Test API returns correct schema
curl -s http://localhost:8000/api/v1/courses | jq 'type' 
# VERIFY: returns "array"

# Test auth required
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/v1/students/me/progress
# VERIFY: returns 401

# Test admin endpoint requires admin role
curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $STUDENT_TOKEN" http://localhost:8000/api/v1/admin/stats
# VERIFY: returns 403

# Test invalid webhook signature
curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8000/api/v1/webhooks/stripe \
  -H "Content-Type: application/json" \
  -H "Stripe-Signature: invalid" \
  -d '{"type": "checkout.session.completed"}'
# VERIFY: returns 403
```

## STEP 4: GENERATE REPORT

After completing all tests, generate a detailed report in this EXACT format:

```markdown
# QA Test Report — Phase 6
## Date: [today]
## Tested against: localhost:3000 (frontend) + localhost:8000 (backend)

## Summary
| Status | Count |
|--------|-------|
| PASS | X |
| FAIL | X |
| BLOCKED | X |
| SKIP | X |

## P0 Test Results (Must Pass for Launch)
| Test ID | Test Name | Status | Details |
|---------|-----------|--------|---------|
| AUTH-001 | Register new student | PASS/FAIL | [what happened] |
| ... | ... | ... | ... |

## P1 Test Results (Should Pass)
[same format]

## Failure Analysis
For EACH failed test:
### FAIL: [Test ID] — [Test Name]
**What happened:** [exact behavior observed]
**Expected:** [what should have happened per PRD]
**Root cause:** [why it failed — missing code, wrong logic, missing endpoint, etc.]
**File to fix:** [exact file path]
**Fix description:** [what code change is needed]
**Severity:** Critical / Major / Minor

## Missing Endpoints / Features
List any API endpoints or features referenced in the PRD that don't exist yet.

## Recommendations
Prioritized list of fixes, ordered by severity.
```

Write this report to docs/QA_REPORT_PHASE6.md and also print it to the terminal.

IMPORTANT RULES:
- Do NOT modify any application code during testing
- Do NOT skip any P0 test — every P0 test must be attempted
- If a test is BLOCKED (e.g., prerequisite endpoint missing), mark it BLOCKED with explanation
- Take Playwright screenshots for every FAIL
- Be brutally honest — if something doesn't work, report it clearly
- After the report, provide a prioritized fix list that can be used as a Phase 7 prompt
```

---

## PHASE 7: Fix All QA Failures (Run after Phase 6 report)

```
Read CLAUDE.md and docs/QA_REPORT_PHASE6.md. You are fixing all failures found during QA testing. Fix each issue below in order. Run tests after each fix. Do not ask questions.

FIX 1 — CRITICAL: Add is_published to CourseCreate schema
- File: backend/app/schemas/course.py
- Add is_published: bool = False to CourseCreate
- Verify: POST /api/v1/courses with is_published=true now works
- Test: uv run pytest tests/test_api/test_courses.py -x

FIX 2 — CRITICAL: Stripe webhook must reject when secret is empty
- File: backend/app/api/v1/routes/webhooks.py
- When STRIPE_WEBHOOK_SECRET is empty/None, return 503 "Stripe webhook not configured" instead of bypassing verification
- Never allow unverified payloads through
- Test: uv run pytest tests/test_api/test_webhooks.py -x

FIX 3 — CRITICAL: Agent chat must catch all exceptions gracefully
- File: backend/app/api/v1/routes/agents.py
- Wrap the agent execution in try/except that catches ALL exceptions
- On failure: return {"response": "I encountered an issue. Please try again.", "agent_name": "system", "error": true}
- NEVER return traceback, file paths, or library versions to the client
- Test: uv run pytest tests/test_api/test_agents.py -x

FIX 4 — CRITICAL: Create enrollment endpoint
- Create: POST /api/v1/courses/{course_id}/enroll (auth required)
- Logic: check user is authenticated, check course exists and is published, check not already enrolled, create Enrollment record
- If already enrolled, return 409 "Already enrolled"
- If course not found, return 404
- Add to router in app/main.py
- Write test: tests/test_api/test_enrollment.py (test enroll, duplicate enroll, enroll in non-existent course)
- Test: uv run pytest tests/test_api/test_enrollment.py -x

FIX 5 — MAJOR: Rate limiting must use Redis backend
- File: backend/app/api/v1/routes/auth.py (or wherever slowapi is configured)
- Change from in-memory storage to Redis-backed storage
- Use: limiter = Limiter(key_func=get_remote_address, storage_uri=settings.REDIS_URL)
- Test: verify rate limiting works (existing tests should still pass)

FIX 6 — MAJOR: Remove duplicate exercise_id requirement
- File: backend/app/api/v1/routes/exercises.py and app/schemas/exercise.py
- exercise_id should come from URL path only, NOT required in request body
- Test: uv run pytest tests/test_api/test_exercises.py -x

FIX 7 — MAJOR: Progress endpoint must return computed summary
- File: backend/app/api/v1/routes/students.py and app/services/learning_engine.py (or equivalent)
- GET /api/v1/students/me/progress must return:
  {
    "courses": [
      {
        "course_id": "...",
        "course_title": "...",
        "total_lessons": 10,
        "completed_lessons": 3,
        "progress_percentage": 30.0,
        "next_lesson_id": "lesson_4_id",
        "lessons": [{"id": "...", "title": "...", "status": "completed/in_progress/not_started"}]
      }
    ],
    "overall_progress": 30.0,
    "recent_activity": [...]
  }
- NOT just raw database rows
- Frontend dashboard should be able to render directly from this response
- Test: write test that creates 10 lessons, completes 3, verifies progress_percentage=30.0

FIX 8 — MINOR: Add auth requirement to /agents/list
- File: backend/app/api/v1/routes/agents.py
- Add Depends(get_current_user) to the list endpoint
- Test: verify 401 without token

FIX 9 — MINOR: Fix Docker healthcheck
- File: docker-compose.yml
- Replace: test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
- With: test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
- Or install curl in Dockerfile: RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

AFTER ALL FIXES:
- Run full test suite: make test (must pass with 0 failures)
- Run linter: make lint (must pass with 0 errors)
- Rebuild Docker: docker compose build
- Run the same QA seed + test sequence from Phase 6 to verify fixes
- Commit: git add -A && git commit -m "fix: Phase 7 — resolve all QA failures (4 critical, 5 major/minor)"

Print a summary showing which issues are fixed and verified.
```
