"""D11.5 — sandbox request + result schemas (Pass 3d §E.3.2 contract).

Aligned with pass-3d-tool-implementations.md §E.3.2 RunInSandboxInput /
RunInSandboxOutput. The schemas were originally drafted at D11.5 Stage 1
under different field names; Stage 3.1 renamed to match the spec
contract (`duration_ms` not `runtime_ms`, `timed_out` not
`timeout_killed`, `truncated` flag consolidating output truncation,
plus `memory_used_mb`).

Path A (process-based isolation) is implemented; Path B (container-based,
likely E2B per spec recommendation) is a follow-up. Some spec fields
(language="node", network_access=True) are accepted at the schema layer
but raise NotImplementedError at the executor — the spec contract is
the source of truth, but Path A's implementation surface is narrower.

Design rationale per locked decisions D-A through D-E:

  D-D: SandboxResult discriminates failure modes at the data level.
       Boolean flags (timed_out, oom_killed, sandbox_escaped, truncated)
       + structured fields (exception_traceback, exit_code, memory_used_mb)
       beat a string-prefix convention so consumers can act differently
       on different failure shapes.

  D-E: Sandbox executions audit through agent_tool_calls. SandboxRequest
       fields land in args (jsonb); SandboxResult fields land in result
       (jsonb). No separate sandbox_executions table.

  oom_killed, sandbox_escaped, exception_traceback are EXTENSIONS beyond
  the Pass 3d spec contract; useful for debugging and Critic-loop
  consumption. Spec consumers (senior_engineer's run_in_sandbox tool)
  read the spec fields and ignore the extensions.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SandboxRequest(BaseModel):
    """Pass 3d §E.3.2 RunInSandboxInput — aligned to spec contract.

    The agent (or its caller) supplies code + execution parameters.
    All fields have explicit caps so a malformed agent prompt can't
    request unbounded resources.
    """

    model_config = ConfigDict(extra="forbid")

    code: str = Field(
        max_length=100_000,
        description=(
            "The source code to execute. UTF-8 text. 100KB cap is "
            "generous for capstone-sized snippets and keeps the "
            "audit row bounded."
        ),
    )
    language: Literal["python", "node"] = Field(
        default="python",
        description=(
            "Source language per Pass 3d §E.3.2. Python is implemented "
            "in D11.5; Node.js raises NotImplementedError at the "
            "executor — see "
            "docs/followups/sandbox-language-extension-node.md."
        ),
    )
    test_inputs: list[str] = Field(
        default_factory=list,
        max_length=20,
        description=(
            "Per-test stdin strings, one per element. Empty list means "
            "the subprocess runs once with /dev/null stdin (current "
            "single-shot behavior). Multi-shot stdin support is a "
            "future extension; D11.5 implements the empty-list path "
            "and validates the shape."
        ),
    )
    network_access: bool = Field(
        default=False,
        description=(
            "Per Pass 3d spec, defaults False. D11.5 always behaves as "
            "False under Path A (network namespaces require "
            "CAP_SYS_ADMIN; we run as appuser). Passing True raises "
            "NotImplementedError at the executor — Path B (container "
            "isolation, likely E2B) is the proper enforcement layer."
        ),
    )
    timeout_seconds: int = Field(
        default=10,
        ge=1,
        le=60,
        description=(
            "Wall-clock + CPU timeout. The kernel kills the subprocess "
            "via RLIMIT_CPU at this value + 1; the asyncio wrapper "
            "kills it at this value + 2 as a fallback. Spec ceiling is "
            "60s per E.3.2."
        ),
    )
    memory_limit_mb: int = Field(
        default=256,
        ge=64,
        le=1024,
        description=(
            "Address-space limit (RLIMIT_AS). Subprocess that exceeds "
            "this is killed by the kernel; sandbox sets oom_killed=True "
            "in the result. 64MB lower bound is enough for a Python "
            "interpreter + small stdlib + typical student code. Spec "
            "ceiling is 1024MB per E.3.2."
        ),
    )


class SandboxResult(BaseModel):
    """Pass 3d §E.3.2 RunInSandboxOutput — aligned to spec contract.

    Spec fields:
      • stdout, stderr, exit_code
      • duration_ms (was runtime_ms in pre-spec drafts)
      • memory_used_mb (NEW — populated from getrusage at subprocess
        termination; best-effort)
      • timed_out (was timeout_killed in pre-spec drafts)
      • truncated (single flag set when stdout OR stderr was truncated)

    Extensions beyond the spec contract (D11.5 additions for debugging
    and Critic-loop consumption):
      • oom_killed — kernel SIGKILL discrimination
      • sandbox_escaped — heuristic escape detection (security.py)
      • exception_traceback — extracted from stderr for clean consumer
        access without re-parsing
      • language — echoed for audit aid

    Per D-D: failure modes are discriminated at the data level via
    boolean flags. The boolean flags are NOT mutually exclusive in
    principle — a single execution could trip both timed_out and
    sandbox_escaped (e.g., infinite loop trying to open /etc/shadow).
    Consumers should check each flag independently.
    """

    model_config = ConfigDict(extra="forbid")

    stdout: str = Field(
        default="",
        max_length=50_000,
        description=(
            "Captured stdout, truncated to 50KB. The truncated flag "
            "is set when truncation occurred."
        ),
    )
    stderr: str = Field(
        default="",
        max_length=50_000,
        description=(
            "Captured stderr, truncated to 50KB. Same truncation "
            "discipline as stdout."
        ),
    )
    exit_code: int | None = Field(
        default=None,
        description=(
            "The subprocess exit code. None when killed by signal "
            "(timeout, OOM, or other kill). Successful Python exits "
            "produce 0; uncaught exceptions produce 1; explicit "
            "sys.exit(N) produces N."
        ),
    )
    duration_ms: int = Field(
        ge=0,
        description=(
            "Wall-clock subprocess elapsed time in ms. Always populated "
            "(even on timeout, this captures how long before the kill). "
            "Spec name per Pass 3d §E.3.2 (was runtime_ms in earlier "
            "drafts)."
        ),
    )
    memory_used_mb: int = Field(
        default=0,
        ge=0,
        description=(
            "Peak memory usage in MB measured via getrusage at "
            "subprocess termination. Best-effort — when the OS doesn't "
            "expose RSS via getrusage cleanly (cgroups environments), "
            "this stays 0. Set per Pass 3d §E.3.2."
        ),
    )
    timed_out: bool = Field(
        default=False,
        description=(
            "True when the subprocess was killed for exceeding "
            "timeout_seconds. Reached via RLIMIT_CPU OR the asyncio "
            "wait_for fallback. Spec name per Pass 3d §E.3.2 (was "
            "timeout_killed in earlier drafts)."
        ),
    )
    truncated: bool = Field(
        default=False,
        description=(
            "True when stdout OR stderr exceeded its 50KB cap and was "
            "truncated. Spec consolidation per Pass 3d §E.3.2 (earlier "
            "drafts had the truncation marker inline only)."
        ),
    )
    oom_killed: bool = Field(
        default=False,
        description=(
            "EXTENSION beyond Pass 3d spec. True when the subprocess "
            "was killed for exceeding memory_limit_mb. Reached via "
            "RLIMIT_AS — Python typically raises MemoryError before "
            "the kernel kills, so most OOM cases manifest as "
            "exception_traceback containing MemoryError; this flag is "
            "set when exit code/signal indicates an OOM kill specifically."
        ),
    )
    sandbox_escaped: bool = Field(
        default=False,
        description=(
            "EXTENSION beyond Pass 3d spec. True when the security "
            "guard's heuristic patterns detected an escape attempt in "
            "the subprocess output (e.g., /etc/passwd reads, outbound "
            "network calls). Best-effort signal; container-level "
            "isolation (Path B) is the strict-correctness answer."
        ),
    )
    exception_traceback: str | None = Field(
        default=None,
        max_length=20_000,
        description=(
            "EXTENSION beyond Pass 3d spec. Populated when student "
            "code raised an uncaught exception. Captured from stderr "
            "via traceback marker matching. Distinct from stderr to "
            "give consumers a clean traceback string without other "
            "stderr noise."
        ),
    )
    language: Literal["python", "node"] = Field(
        default="python",
        description="Language echoed from the request (audit aid).",
    )


__all__ = ["SandboxRequest", "SandboxResult"]
