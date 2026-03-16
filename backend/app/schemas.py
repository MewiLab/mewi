from pydantic import BaseModel
from typing import Optional, Dict

#  define structure of ground_truth
class GroundTruth(BaseModel):
    valence: float
    arousal: float

# define structure of a diary
class ScentData(BaseModel):
    id: int
    text: str
    lbs_context: Optional[str]
    ground_truth: GroundTruth
    routing_label: str