"""Producer → validator input adapters for mandatory validation chains.

Per D13.5 D-A: validation chains are declared on the producing agent's
capability via `requires_mandatory_validation_by` + `validation_input_adapter`.
The adapter function maps the producer's structured output to the
validator's structured input.

Each adapter lives as a top-level function in a per-(producer, validator)
module so the Supervisor's chain-construction logic can resolve it via
import without triggering full agent-module loads (which would create
circular imports through capability.py).

Adapters import only schemas — never agent classes or services.
"""

from __future__ import annotations

__all__: list[str] = []
