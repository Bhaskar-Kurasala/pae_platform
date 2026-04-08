---
name: agent-developer
description: |
  Use when building or modifying any of the 18 AI agents in the platform.
  Covers LangGraph node creation, tool registration, memory setup,
  evaluation criteria, and integration with the Master Orchestrator Agent.
  Trigger phrases: "build agent", "create agent", "modify agent", "agent code"
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, TodoWrite
---

# Agent Development Skill

## Architecture
Every agent is a LangGraph node that:
1. Receives a `AgentState` dict: student context, conversation history, task description
2. Has access to registered tools (GitHub API, DB queries, Pinecone, etc.)
3. Returns updated `AgentState` with response and side effects
4. Is evaluated by MOA before delivery to student

## Base Agent Contract
```python
# backend/app/agents/base_agent.py
from abc import ABC, abstractmethod
from pydantic import BaseModel

class AgentState(BaseModel):
    student_id: str
    conversation_history: list[dict]
    task: str
    context: dict = {}
    response: str | None = None
    tools_used: list[str] = []
    evaluation_score: float | None = None

class BaseAgent(ABC):
    name: str
    description: str
    trigger_conditions: list[str]
    model: str = "claude-sonnet-4-6"
    
    @abstractmethod
    async def execute(self, state: AgentState) -> AgentState: ...
    
    async def evaluate(self, state: AgentState) -> float:
        """Return 0.0-1.0 quality score. Override for custom eval."""
        return 0.8  # Default pass-through
    
    async def log_action(self, state: AgentState) -> None:
        """Log to agent_actions table. Called automatically by MOA."""
        ...
```

## New Agent Checklist
- [ ] Create `backend/app/agents/{name}.py` extending `BaseAgent`
- [ ] Create system prompt at `backend/app/agents/prompts/{name}.md`
- [ ] Register in `backend/app/agents/__init__.py` AGENT_REGISTRY dict
- [ ] Add trigger conditions so MOA can route to this agent
- [ ] Write unit test: `backend/tests/test_agents/test_{name}.py`
- [ ] Write integration test with mocked LLM responses
- [ ] Define evaluation criteria (what makes a good response)
- [ ] Verify agent_actions logging works
- [ ] Add to docs/AGENTS.md documentation

## Tool Registration Pattern
```python
from langchain_core.tools import tool

@tool
async def search_course_content(query: str, lesson_id: str | None = None) -> str:
    """Search course content via Pinecone RAG pipeline."""
    # Implementation here
    ...
```

## Memory Scopes
- **Short-term (Redis)**: Current conversation, expires after 1 hour
- **Long-term (PostgreSQL)**: Student profile, learning history, permanent
- **Episodic (agent_actions table)**: Every action logged for analytics
