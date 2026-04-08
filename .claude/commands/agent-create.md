---
name: agent-create
description: Scaffold a new AI agent with all required files
argument-hint: [agent-name] [agent-description]
---

# /agent-create — Scaffold New AI Agent

Creates all files needed for a new AI agent in the platform.

## Files Created
1. `backend/app/agents/{name}.py` — Agent implementation
2. `backend/app/agents/prompts/{name}.md` — System prompt
3. `backend/tests/test_agents/test_{name}.py` — Unit + integration tests
4. Update `backend/app/agents/__init__.py` — Register in AGENT_REGISTRY
5. Update `docs/AGENTS.md` — Add documentation

## Agent Template
```python
"""
{Agent Name} Agent
{Description}

Trigger: {when this agent activates}
Tools: {what tools it can use}
Model: claude-sonnet-4-6
"""
import structlog
from app.agents.base_agent import BaseAgent, AgentState

logger = structlog.get_logger()

class {ClassName}Agent(BaseAgent):
    name = "{snake_name}"
    description = "{description}"
    trigger_conditions = ["{trigger1}", "{trigger2}"]
    model = "claude-sonnet-4-6"
    
    async def execute(self, state: AgentState) -> AgentState:
        logger.info("agent.execute", agent=self.name, student_id=state.student_id)
        
        # 1. Build context from student profile and conversation
        context = await self._build_context(state)
        
        # 2. Call LLM with system prompt and tools
        response = await self._call_llm(
            system_prompt=self._load_prompt(),
            messages=state.conversation_history,
            context=context,
        )
        
        # 3. Update state
        state.response = response
        state.tools_used = self._get_tools_used()
        
        # 4. Log action
        await self.log_action(state)
        
        return state
    
    async def evaluate(self, state: AgentState) -> float:
        # Custom evaluation logic
        return 0.85
```

## After Creation
1. Verify tests pass: `uv run pytest tests/test_agents/test_{name}.py -v`
2. Register trigger conditions in MOA routing table
3. Update docs/AGENTS.md
4. Commit: `git commit -m 'feat(agents): add {name} agent'`
