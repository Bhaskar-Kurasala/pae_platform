import pytest

from app.agents.base_agent import AgentState, BaseAgent


class EchoAgent(BaseAgent):
    """Minimal concrete agent for testing the contract."""

    name = "echo"
    description = "Echo agent for tests"
    trigger_conditions = ["echo"]

    async def execute(self, state: AgentState) -> AgentState:
        return state.model_copy(update={"response": f"ECHO: {state.task}"})


class ErrorAgent(BaseAgent):
    name = "error"
    description = "Always raises"
    trigger_conditions = []

    async def execute(self, state: AgentState) -> AgentState:
        raise RuntimeError("Intentional error")


@pytest.mark.asyncio
async def test_agent_state_defaults() -> None:
    state = AgentState(student_id="s1", task="hello")
    assert state.conversation_history == []
    assert state.tools_used == []
    assert state.response is None
    assert state.evaluation_score is None


@pytest.mark.asyncio
async def test_agent_state_immutability() -> None:
    state = AgentState(student_id="s1", task="hello")
    updated = state.model_copy(update={"response": "world"})
    assert state.response is None
    assert updated.response == "world"


@pytest.mark.asyncio
async def test_echo_agent_execute() -> None:
    agent = EchoAgent()
    state = AgentState(student_id="s1", task="ping")
    result = await agent.execute(state)
    assert result.response == "ECHO: ping"


@pytest.mark.asyncio
async def test_echo_agent_evaluate_default() -> None:
    agent = EchoAgent()
    state = AgentState(student_id="s1", task="ping", response="some response")
    evaluated = await agent.evaluate(state)
    assert evaluated.evaluation_score == 0.8


@pytest.mark.asyncio
async def test_echo_agent_run_pipeline() -> None:
    """run() should execute + evaluate + log_action (log_action no-ops in tests)."""
    agent = EchoAgent()
    state = AgentState(student_id="s1", task="test run")
    result = await agent.run(state)
    assert result.response == "ECHO: test run"
    assert result.evaluation_score == 0.8
    assert result.agent_name == "echo"


@pytest.mark.asyncio
async def test_error_agent_propagates() -> None:
    agent = ErrorAgent()
    state = AgentState(student_id="s1", task="fail")
    with pytest.raises(RuntimeError, match="Intentional error"):
        await agent.run(state)


@pytest.mark.asyncio
async def test_registry_register_and_get() -> None:
    from app.agents.registry import AGENT_REGISTRY, get_agent

    AGENT_REGISTRY["echo"] = EchoAgent
    agent = get_agent("echo")
    assert agent.name == "echo"


@pytest.mark.asyncio
async def test_registry_unknown_agent() -> None:
    from app.agents.registry import get_agent

    with pytest.raises(KeyError):
        get_agent("nonexistent_agent_xyz")
