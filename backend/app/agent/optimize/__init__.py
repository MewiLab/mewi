"""
agent/optimize — prompt and reasoning enhancements that make the cat "live more".

Unity guarantees that any chosen action will physically execute, so the
backend's job is to *widen the space of plausible behaviours*. Each module
here is one technique that pushes the LLM away from default-picking
SEEK_FOOD every tick and toward more varied, life-like behaviour:

  - chain_of_thought  — scratchpad reasoning before the JSON intent
  - query_expansion   — multiple framings of the same situation
  - multi_intent      — primary + fallback intent for resilience
  - plan_diversity    — score plan novelty against recent STM
  - life_balance      — boost neglected drives (explore, social, rest)

Each module is pure-Python and side-effect-free. They are opt-in helpers:
the existing slow/fast mind pipeline keeps working unchanged. Callers
compose them where they want richer behaviour.
"""

from app.agent.optimize.chain_of_thought import (
    SLOW_MIND_COT_OUTPUT_BLOCK,
    augment_slow_mind_with_cot,
    extract_thought,
)
from app.agent.optimize.life_balance import (
    LifeBalanceReport,
    NEED_KEYS,
    compute_life_balance,
    life_balance_focus_lines,
)
from app.agent.optimize.multi_intent import (
    MultiIntentDecision,
    SLOW_MIND_MULTI_INTENT_OUTPUT_BLOCK,
    coerce_to_multi_intent,
    extract_primary_intent,
)
from app.agent.optimize.plan_diversity import (
    plan_signature,
    score_plan_novelty,
)
from app.agent.optimize.query_expansion import (
    expand_situation_framings,
    inject_paraphrased_perceptions,
)

__all__ = [
    "SLOW_MIND_COT_OUTPUT_BLOCK",
    "augment_slow_mind_with_cot",
    "extract_thought",
    "LifeBalanceReport",
    "NEED_KEYS",
    "compute_life_balance",
    "life_balance_focus_lines",
    "MultiIntentDecision",
    "SLOW_MIND_MULTI_INTENT_OUTPUT_BLOCK",
    "coerce_to_multi_intent",
    "extract_primary_intent",
    "plan_signature",
    "score_plan_novelty",
    "expand_situation_framings",
    "inject_paraphrased_perceptions",
]
