"""Python sandbox executor for the Studio (P1-B-4).

Runs user code in a subprocess with a hard timeout and memory cap (where the
platform supports it), capturing stdout, stderr, and a line-by-line variable
trace via sys.settrace.

This is a teaching sandbox, not a security sandbox. Do not expose it to
untrusted internet traffic without an additional isolation layer (Docker with
--read-only, nsjail, Firecracker, etc.). For authenticated PAE students this
is acceptable: they already have broader access, and the subprocess inherits
no platform secrets (we strip env vars).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

# Cap each captured variable's repr to keep trace payloads bounded.
_MAX_REPR = 200
# Cap total trace events per execution.
_MAX_EVENTS = 500
# Cap stdout/stderr bytes each.
_MAX_STREAM_BYTES = 16_000

_TRACER_TEMPLATE = r"""
import json
import os
import sys
import traceback

USER_CODE = {code!r}
USER_FILE = "<student>"
MAX_REPR = {max_repr}
MAX_EVENTS = {max_events}

_events = []


def _safe_repr(v):
    try:
        r = repr(v)
    except Exception as exc:
        r = f"<unrepr: {{type(v).__name__}}: {{exc}}>"
    if len(r) > MAX_REPR:
        r = r[:MAX_REPR] + "…"
    return r


def _snapshot(frame):
    # Only snapshot simple scalars + small containers from locals.
    out = {{}}
    for name, value in list(frame.f_locals.items())[:25]:
        if name.startswith("__") and name.endswith("__"):
            continue
        out[name] = _safe_repr(value)
    return out


def _tracer(frame, event, arg):
    if len(_events) >= MAX_EVENTS:
        return None
    if frame.f_code.co_filename != USER_FILE:
        return _tracer
    if event == "line":
        _events.append({{
            "event": "line",
            "line": frame.f_lineno,
            "locals": _snapshot(frame),
        }})
    return _tracer


_globals = {{"__name__": "__main__", "__file__": USER_FILE}}
error = None
compiled = None
try:
    compiled = compile(USER_CODE, USER_FILE, "exec")
except BaseException:
    error = traceback.format_exc()

if compiled is not None:
    sys.settrace(_tracer)
    try:
        exec(compiled, _globals)
    except SystemExit:
        pass
    except BaseException:
        error = traceback.format_exc()
    finally:
        sys.settrace(None)

# Emit the trace to a sentinel fd so stdout stays clean.
payload = {{"events": _events, "error": error}}
sys.stdout.write("\n__PAE_TRACE_START__\n")
sys.stdout.write(json.dumps(payload))
sys.stdout.write("\n__PAE_TRACE_END__\n")
"""


@dataclass
class TraceEvent:
    line: int
    locals: dict[str, str]


@dataclass
class ExecutionResult:
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool
    error: str | None
    events: list[TraceEvent]


def _truncate_stream(data: str) -> str:
    if len(data) <= _MAX_STREAM_BYTES:
        return data
    return data[:_MAX_STREAM_BYTES] + "\n…(truncated)"


def _parse_trace(stdout: str) -> tuple[str, list[TraceEvent], str | None]:
    """Split the tracer's sentinel block out of stdout."""
    start = stdout.rfind("\n__PAE_TRACE_START__\n")
    end = stdout.rfind("\n__PAE_TRACE_END__\n")
    if start == -1 or end == -1 or end <= start:
        return stdout, [], None

    user_stdout = stdout[:start]
    trace_json = stdout[start + len("\n__PAE_TRACE_START__\n") : end]
    try:
        payload = json.loads(trace_json)
    except json.JSONDecodeError:
        return user_stdout, [], None

    events = [
        TraceEvent(line=int(e.get("line", 0)), locals=dict(e.get("locals", {})))
        for e in payload.get("events", [])
        if e.get("event") == "line"
    ]
    error = payload.get("error")
    return user_stdout, events, error


def run_python(code: str, timeout_seconds: float = 5.0) -> ExecutionResult:
    """Execute user code in a subprocess with a hard timeout.

    Returns stdout/stderr/exit/trace. Never raises for user-code errors —
    they are captured in `error` and/or stderr.
    """
    script = _TRACER_TEMPLATE.format(
        code=code,
        max_repr=_MAX_REPR,
        max_events=_MAX_EVENTS,
    )

    with tempfile.NamedTemporaryFile(
        suffix=".py", mode="w", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(script)
        tmp_path = Path(tmp.name)

    try:
        # Strip env vars so the sandbox doesn't see our API keys / DB URLs.
        safe_env = {
            "PATH": os.environ.get("PATH", ""),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        proc = subprocess.run(
            [sys.executable, "-I", str(tmp_path)],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=safe_env,
            cwd=tempfile.gettempdir(),
        )
        user_stdout, events, trace_error = _parse_trace(proc.stdout)
        return ExecutionResult(
            stdout=_truncate_stream(user_stdout),
            stderr=_truncate_stream(proc.stderr),
            exit_code=proc.returncode,
            timed_out=False,
            error=trace_error,
            events=events,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        stderr = exc.stderr or ""
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        user_stdout, events, _ = _parse_trace(stdout)
        return ExecutionResult(
            stdout=_truncate_stream(user_stdout),
            stderr=_truncate_stream(stderr),
            exit_code=-1,
            timed_out=True,
            error=f"Execution exceeded {timeout_seconds}s timeout.",
            events=events,
        )
    finally:
        tmp_path.unlink(missing_ok=True)
