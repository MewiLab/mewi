from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID
from pydantic import BaseModel, Field, model_validator


class Temperament(str, Enum):
    shy = "shy"
    neutral = "neutral"
    bold = "bold"
    aggressive = "aggressive"


class CreatureRead(BaseModel):
    id: UUID
    name: str | None = None
    aura: str | None = None            # visual vibe / color theme
    temperament: Temperament = Temperament.neutral
    territory_id: UUID | None = None   # which zone they claim
    trust_toward_human: float = Field(0.0, ge=-1.0, le=1.0)
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Creature-to-creature relationship ────────────────────────

class BondType(str, Enum):
    stranger = "stranger"       # never met
    cautious = "cautious"       # sniffed, unsure
    friendly = "friendly"       # groom, share space
    bonded = "bonded"           # sleep together, co-hunt
    rival = "rival"             # hiss, fight over territory


class CreaturesRelationRead(BaseModel):
    id: UUID
    creature_a_id: UUID         # always smaller UUID
    creature_b_id: UUID
    bond_type: BondType = BondType.stranger
    bond_score: float = Field(0.0, ge=-1.0, le=1.0)  # -1 hostile ↔ +1 bonded
    encounter_count: int = 0
    last_interaction: str | None = None   # "groomed", "hissed", "shared food"
    last_seen_at: datetime | None = None

    model_config = {"from_attributes": True}

    @model_validator(mode="after")
    def normalize_order(self):
        if str(self.creature_a_id) > str(self.creature_b_id):
            self.creature_a_id, self.creature_b_id = (
                self.creature_b_id, self.creature_a_id,
            )
        return self
    
    
""" Key Question or Insight
bond_score is a spectrum, and bond_type is the label
- bond_score drifts continuously with each interaction 
- bond_type is good for sending to Unity (detriministic)

encounter_count
- met once vs  have 50 peaceful encounters

last_interaction
- string, list? should save description or cache how many interaction

territory_id
-  Cats in the same zone meet more often?
"""


class CreatureThinkRequest(BaseModel):
    creature_id: str
    snapshot: dict[str, Any]