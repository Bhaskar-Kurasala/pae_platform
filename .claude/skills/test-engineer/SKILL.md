---
name: test-engineer
description: |
  Use when writing tests, improving coverage, or designing test strategy.
  Covers pytest (backend), Vitest (frontend), Playwright (E2E),
  mocked LLM testing for agents, and CI integration.
  Trigger phrases: "test", "coverage", "pytest", "vitest", "e2e"
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, TodoWrite
---

# Testing Skill

## Backend: pytest + pytest-asyncio
```python
# tests/conftest.py
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

# tests/test_api/test_courses.py
@pytest.mark.asyncio
async def test_list_courses(client):
    response = await client.get("/api/v1/courses")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
```

## Agent Testing (mocked LLM)
```python
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_socratic_tutor():
    with patch("app.agents.socratic_tutor.call_llm") as mock_llm:
        mock_llm.return_value = "What do you think happens when...?"
        agent = SocraticTutorAgent()
        state = AgentState(student_id="test", task="explain RAG")
        result = await agent.execute(state)
        assert result.response is not None
        assert "?" in result.response  # Socratic = questions
```

## Frontend: Vitest + Testing Library
```tsx
import { render, screen } from "@testing-library/react";
import { CourseCard } from "./CourseCard";

test("renders course title", () => {
  render(<CourseCard course={{ title: "RAG Engineering" }} />);
  expect(screen.getByText("RAG Engineering")).toBeInTheDocument();
});
```

## Coverage Targets
- Backend: >80% line coverage
- Frontend: >80% component coverage
- Agents: 100% of agents have at least one integration test
- API: >90% of endpoints have at least one test
