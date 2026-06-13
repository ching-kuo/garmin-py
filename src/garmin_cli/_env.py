"""Environment-variable parsing helpers shared across low-level modules."""
from __future__ import annotations

import os


def _env_float(name: str, default: float, *, allow_zero: bool = True) -> float:
    """Read *name* from the environment as a float, falling back to *default*.

    A parse error, a negative value, or a zero value when ``allow_zero`` is
    False, is ignored and *default* is returned. This is the shared core of the
    per-knob resolvers (HTTP timeout, auth probe TTL, daily-call delay).
    """
    raw = os.environ.get(name, "")
    if raw:
        try:
            value = float(raw)
            if value > 0 or (allow_zero and value == 0):
                return value
        except ValueError:
            pass
    return default
