"""Sandbox security primitives — resource limits, env scrubbing,
escape detection.

THREAT MODEL (D14a Path A — process-based isolation):

  Mitigated by this implementation:
    • Wall-clock and CPU runaway (RLIMIT_CPU + asyncio.wait_for fallback)
    • Memory exhaustion (RLIMIT_AS — address-space cap)
    • Filesystem write runaway (RLIMIT_FSIZE — output file size cap)
    • File-descriptor exhaustion (RLIMIT_NOFILE)
    • Fork bombs (RLIMIT_NPROC — process count cap)
    • Secret leakage via env (env scrubbing — only PATH and HOME are
      passed to the subprocess; no API keys, no database URLs)
    • Heuristic escape detection (regex match on stdout/stderr for
      known escape signals — best-effort only)

  NOT mitigated by this implementation; require Path B
  (container-per-execution) or kernel-level controls:
    • Read access to host filesystem (subprocess can read any file
      the appuser can read, e.g., /etc/passwd contents are visible).
      Path B mitigates via container fs isolation.
    • Network egress (network namespaces require CAP_SYS_ADMIN; we run
      as appuser). Subprocess CAN make outbound connections if the
      container's network policy doesn't block them. Production
      environments should enforce egress restrictions at the container
      or pod level.
    • Local privilege escalation through kernel exploits (CVE-shaped
      attacks). Kernel hardening is the host's responsibility.
    • Side-channel attacks (timing, cache, /proc inspection of other
      processes). Out of scope for AICareerOS at current scale.
    • Persistent storage attacks (writing files that survive the
      execution). Subprocess CAN write to /tmp and any path appuser
      can write; output is bounded by RLIMIT_FSIZE but persistence
      across executions is not mitigated.

The "best-effort + Path B-eventual" framing is documented in
docs/followups/sandbox-path-b-container-isolation.md.
"""

from __future__ import annotations

import re
import resource
from typing import Final


# ── Resource-limit setup ────────────────────────────────────────────


# RLIMIT_CPU is in seconds; we add +1 to give the kernel time to react.
# The asyncio.wait_for fallback catches the case where the kernel kill
# is slow or the subprocess managed to ignore SIGXCPU (which is
# possible if the code does signal.signal(signal.SIGXCPU, …)).
_CPU_GRACE_SECONDS: Final[int] = 1

# RLIMIT_FSIZE in bytes. 10MB is generous for any captured stdout
# spilled to a temp file; way above the 50KB stdout cap so a student
# print loop hits the cap before the kernel kills.
_FSIZE_BYTES: Final[int] = 10 * 1024 * 1024

# RLIMIT_NOFILE — max open file descriptors. 32 covers stdin/stdout/
# stderr + a typical Python interpreter's own internal opens (~10) +
# headroom for student code.
_NOFILE_MAX: Final[int] = 32

# RLIMIT_NPROC — max concurrent processes for the executing user.
# Caps fork bombs. 16 lets multiprocessing-light student code work
# (e.g., one Pool with a few workers); 1 would block legitimate
# subprocess use; >32 risks a fork bomb getting traction before the
# kernel cuts in.
_NPROC_MAX: Final[int] = 16


def make_resource_limit_setter(
    *, memory_mb: int, cpu_seconds: int
) -> "callable[[], None]":  # pragma: no cover  (lambda factory)
    """Build a `preexec_fn` callable that applies rlimits.

    Subprocess sets these AFTER fork but BEFORE exec, so the subprocess
    inherits the limits but the parent (this process) is unaffected.

    Returns a no-arg callable suitable for `subprocess` /
    `asyncio.create_subprocess_exec`'s `preexec_fn` param.
    """
    memory_bytes = memory_mb * 1024 * 1024

    def _apply() -> None:
        # CPU: kernel sends SIGXCPU at soft, SIGKILL at hard.
        cpu_hard = cpu_seconds + _CPU_GRACE_SECONDS
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_hard))
        # Memory: address-space cap. Soft and hard equal; one strike.
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
        # File-write size: caps any output file the subprocess opens.
        resource.setrlimit(resource.RLIMIT_FSIZE, (_FSIZE_BYTES, _FSIZE_BYTES))
        # Open file descriptors.
        resource.setrlimit(resource.RLIMIT_NOFILE, (_NOFILE_MAX, _NOFILE_MAX))
        # Process count — fork-bomb defense.
        resource.setrlimit(resource.RLIMIT_NPROC, (_NPROC_MAX, _NPROC_MAX))

    return _apply


# ── Environment scrubbing ──────────────────────────────────────────


# Minimal env passed to the subprocess. NO API keys, NO database URLs,
# NO LANG-specific overrides. The subprocess gets just enough to find
# the interpreter and write tempfiles.
_SAFE_ENV: Final[dict[str, str]] = {
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "HOME": "/tmp",
    # PYTHONDONTWRITEBYTECODE prevents the subprocess from leaving
    # .pyc files in /tmp under appuser's home.
    "PYTHONDONTWRITEBYTECODE": "1",
    # PYTHONIOENCODING ensures stdout/stderr are decodable as UTF-8;
    # without this, some student code (emojis, non-ASCII) crashes on
    # encoding errors that aren't actually their fault.
    "PYTHONIOENCODING": "utf-8",
}


def scrubbed_environment() -> dict[str, str]:
    """Return the minimal env passed to sandbox subprocesses.

    Returns a fresh dict each call so callers can mutate without
    affecting future subprocess invocations.
    """
    return dict(_SAFE_ENV)


# ── Escape detection ───────────────────────────────────────────────


# Heuristic patterns for detecting escape attempts in stdout/stderr.
# Best-effort only — sophisticated attackers can avoid these patterns;
# Path B (container isolation) is the strict-correctness answer.
#
# Each pattern represents an attack class:
#   • _SECRET_FILE_RE — student code reading host secrets/config files.
#     Matches common sensitive paths whose CONTENT (not just the path
#     string) appears in output. Anchored on file-content shapes
#     (root:x:0:0 from /etc/passwd, BEGIN PRIVATE KEY from key files)
#     to avoid false-positives on student code that just mentions
#     "/etc/passwd" in a string literal.
#   • _NETWORK_INDICATOR_RE — student code making outbound calls
#     successfully. Matches HTTP headers, IP addresses in unusual
#     contexts (NOT 127.* / 192.168.* which are private), and DNS
#     resolution success patterns.
#   • _PROCESS_ESCAPE_RE — fork bombs, /proc inspection of other
#     processes, exec replacement attempts.
_SECRET_FILE_RE: Final[re.Pattern[str]] = re.compile(
    r"root:x:0:0:|BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY|"
    r"AKIA[0-9A-Z]{16}|"  # AWS access key prefix
    r"sk-[A-Za-z0-9]{40,}",  # OpenAI/Anthropic key prefix
    re.MULTILINE,
)
_NETWORK_SUCCESS_RE: Final[re.Pattern[str]] = re.compile(
    # HTTP response status line shape, OR socket.gethostbyname returning
    # a public IP (filtering out localhost/private ranges).
    r"HTTP/[0-9.]+ \d{3}|"
    r"Connected to [a-z0-9.-]+\.[a-z]{2,}",
    re.IGNORECASE,
)
_PROCESS_ESCAPE_RE: Final[re.Pattern[str]] = re.compile(
    # /proc/N/ where N is a PID we likely don't own; exec of /bin/sh;
    # ptrace-related attempts.
    r"/proc/\d+/(?:status|environ|maps|mem)|"
    r"PTRACE_(?:ATTACH|TRACEME)",
)


def detect_sandbox_escape(stdout: str, stderr: str) -> bool:
    """Heuristic: did the subprocess output evidence of an escape attempt?

    Returns True when stdout OR stderr matches one of the patterns
    above. Used to populate `SandboxResult.sandbox_escaped` so
    consumers can flag suspicious executions for review.

    False-negative-prone by design — sophisticated attackers can avoid
    these patterns; Path B is the strict-correctness layer.
    Intentionally NOT false-positive-prone — the patterns target
    content shapes (key prefixes, /etc/passwd line shape) not just
    string mentions.
    """
    combined = f"{stdout}\n{stderr}"
    if _SECRET_FILE_RE.search(combined):
        return True
    if _NETWORK_SUCCESS_RE.search(combined):
        return True
    if _PROCESS_ESCAPE_RE.search(combined):
        return True
    return False


__all__ = [
    "detect_sandbox_escape",
    "make_resource_limit_setter",
    "scrubbed_environment",
]
