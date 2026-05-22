"""Slow/Fast Mind implementation package.

The root ``app.agent`` package owns runtime wiring and broad agent services.
This package owns the LLM mind layer: intent selection, action planning,
prompt context assembly, and shared parsing helpers.
"""

from app.agent.mind.fast import make_fast_mind
from app.agent.mind.slow import make_slow_mind

__all__ = ["make_fast_mind", "make_slow_mind"]
