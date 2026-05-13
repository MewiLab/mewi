"""
SemanticService — X-to-1 compression for Unity perception snapshots.

Condenses a buffer of raw Unity JSON payloads into a single human-readable
narrative paragraph suitable for long-term storage and LLM retrieval.
Optionally generates vector embeddings via EmbeddingService.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from app.core.logger import get_logger

if TYPE_CHECKING:
    from app.services.embedding_service import EmbeddingService

logger = get_logger(__name__)


class SemanticService:
    """Convert a list of raw Unity snapshots into one narrative paragraph."""

    def __init__(self, embedding_service: EmbeddingService | None = None) -> None:
        self._embedding = embedding_service

    # ── Threshold helpers ────────────────────────────────────────────────────

    @staticmethod
    def _label(value: float) -> str:
        """Map a [0, 1] float to a categorical intensity word."""
        if value < 0.3:
            return "low"
        if value <= 0.7:
            return "moderate"
        return "high"

    def _trend(self, label: str, start: float, end: float) -> str | None:
        """
        Return a trend phrase when the intensity category changed between
        the first and last snapshot.  Returns None when stable.
        """
        s, e = self._label(start), self._label(end)
        if s == e:
            return None
        return f"{label} went from {s} to {e}"

    # ── Public API ───────────────────────────────────────────────────────────

    def generate_summary(
        self,
        snapshots: list[dict[str, Any]],
        location: dict[str, float] | None = None,
        timestamp: str | None = None,
    ) -> str:
        """
        Aggregate N Unity snapshots into one narrative paragraph.

        Optionally prepends a spatio-temporal header when `location` is given:
          "[<ISO-timestamp> @ (x, y, z)] The cat was ..."

        Args:
            snapshots: Ordered list of raw Unity payloads (oldest → newest).
            location:  Optional dict with 'x', 'y', 'z' keys for position context.
            timestamp: Optional ISO-8601 string; defaults to UTC now when location
                       is supplied but timestamp is omitted.
        """
        if not snapshots:
            return "No perception data available."

        first = snapshots[0]
        last  = snapshots[-1]

        # ── Current action ───────────────────────────────────────────────────
        action = last.get("self", {}).get("current_action") or "resting"

        # ── Final mood state ─────────────────────────────────────────────────
        mood_data = last.get("mood", {})
        fear      = mood_data.get("fear",      0.0)
        trust     = mood_data.get("trust",     0.0)
        curiosity = mood_data.get("curiosity", 0.5)
        social    = mood_data.get("social",    0.0)
        energy    = mood_data.get("energy",    1.0)

        mood_words: list[str] = []
        if self._label(fear)      == "high":    mood_words.append("fearful")
        if self._label(trust)     == "high":    mood_words.append("trusting")
        if self._label(curiosity) == "high":    mood_words.append("curious")
        if self._label(social)    == "high":    mood_words.append("social")
        if self._label(energy)    == "low":     mood_words.append("tired")
        mood_str = ", ".join(mood_words) if mood_words else "calm"

        # ── Final hunger state ───────────────────────────────────────────────
        hunger      = last.get("health", {}).get("hunger", 0.0)
        hunger_desc = f"hunger was {self._label(hunger)}"

        # ── Trend analysis: first snapshot → last snapshot ───────────────────
        def _m(snap: dict, key: str, default: float) -> float:
            return snap.get("mood", {}).get(key, default)

        def _h(snap: dict, key: str, default: float) -> float:
            return snap.get("health", {}).get(key, default)

        trends: list[str] = []
        for key, default in [
            ("fear",      0.0),
            ("trust",     0.0),
            ("curiosity", 0.5),
            ("energy",    1.0),
        ]:
            t = self._trend(key.capitalize(), _m(first, key, default), _m(last, key, default))
            if t:
                trends.append(t)

        hunger_trend = self._trend(
            "Hunger", _h(first, "hunger", 0.0), _h(last, "hunger", 0.0)
        )
        if hunger_trend:
            trends.append(hunger_trend)

        # ── Entity aggregation: unique tags across all snapshots ─────────────
        seen_tags: set[str] = set()
        for snap in snapshots:
            for entity in snap.get("entities", []):
                for tag in entity.get("tags", []):
                    if tag:
                        seen_tags.add(tag)

        # ── Compose paragraph ────────────────────────────────────────────────
        parts = [
            f"The cat was {action}.",
            f"It felt {mood_str}, {hunger_desc}.",
        ]
        if trends:
            parts.append(f"Over this window: {'; '.join(trends)}.")
        if seen_tags:
            tag_list = ", ".join(f"a {t}" for t in sorted(seen_tags))
            parts.append(f"It noticed {tag_list}.")

        body = " ".join(parts)

        # ── Prepend spatio-temporal context when location is provided ────────
        if location is not None:
            x   = location.get("x", 0.0)
            y   = location.get("y", 0.0)
            z   = location.get("z", 0.0)
            ts  = timestamp or datetime.now(timezone.utc).isoformat()
            return f"[{ts} @ ({x:.1f},{y:.1f},{z:.1f})] {body}"

        return body

    def generate_embedding(self, text: str) -> list[float]:
        """
        Return a 1536-dim embedding vector for `text` via text-embedding-3-small.
        Returns an empty list when no EmbeddingService was injected.
        """
        if self._embedding is None:
            logger.debug("generate_embedding called but no EmbeddingService injected")
            return []
        try:
            return self._embedding.embed_text(text)
        except Exception:
            logger.exception("EmbeddingService.embed_text failed")
            return []
