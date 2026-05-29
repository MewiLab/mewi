from __future__ import annotations

from app.models.attachment import (
    AttachmentAnalysisResult,
    AttachmentConfidence,
    AttachmentSessionFeatures,
    PlayerAttachmentEstimate,
)

MIN_EVENTS_TO_CLASSIFY = 8


def atf(features: AttachmentSessionFeatures) -> AttachmentAnalysisResult:
    """Attachment Type Function: transparent rules over processed features."""

    if features.n_events < MIN_EVENTS_TO_CLASSIFY:
        return AttachmentAnalysisResult(
            session_id=features.session_id,
            cat_id=features.cat_id,
            cat_assigned_type=features.cat_assigned_type,
            player_attachment_estimate=PlayerAttachmentEstimate.UNDETERMINED,
            scores=_empty_scores(),
            confidence=AttachmentConfidence.LOW,
            n_events=features.n_events,
            features=features,
            rule_trace=[
                "insufficient_evidence: fewer than 8 events, so the prototype declines to hard-classify",
            ],
        )

    pursuit = _clamp(features.pursuit_ratio)
    reunion = _clamp(features.reunion_response)
    near = _clamp(features.time_near_ratio)
    tolerance = _duration_score(features.withdrawal_tolerance, high_at=12.0)
    latency_quick = 1.0 - _duration_score(features.reapproach_latency_mean, high_at=12.0)

    raw_scores = {
        "anxious": (
            0.35 * _high(pursuit)
            + 0.25 * _high(reunion)
            + 0.20 * _high(tolerance)
            + 0.20 * latency_quick
        ),
        "avoidant": (
            0.35 * _low(pursuit)
            + 0.30 * _low(reunion)
            + 0.20 * _low(near)
            + 0.15 * _low(tolerance)
        ),
        "secure": (
            0.30 * _mid(pursuit)
            + 0.30 * _high(reunion)
            + 0.25 * _high(tolerance)
            + 0.15 * _mid(near)
        ),
        "disorganized": (
            0.50 * _conflict(pursuit, reunion)
            + 0.30 * _conflict(tolerance, latency_quick)
            + 0.20 * _low(_mid(pursuit))
        ),
    }
    scores = _normalize_scores(raw_scores)
    estimate = PlayerAttachmentEstimate(max(scores, key=scores.get))

    return AttachmentAnalysisResult(
        session_id=features.session_id,
        cat_id=features.cat_id,
        cat_assigned_type=features.cat_assigned_type,
        player_attachment_estimate=estimate,
        scores=scores,
        confidence=AttachmentConfidence.LOW,
        n_events=features.n_events,
        features=features,
        rule_trace=[
            "anxious: high pursuit, high reunion intensity, high tolerance after withdrawal, quick reapproach",
            "avoidant: low pursuit, muted reunion, lower near-time, low tolerance after withdrawal",
            "secure: moderate pursuit, strong reunion, sustained tolerance, balanced near-time",
            "disorganized: conflicting pursuit/reunion or tolerance/reapproach pattern",
            "confidence: low until validated against an external self-report instrument",
        ],
    )


def _empty_scores() -> dict[str, float]:
    return {
        "secure": 0.0,
        "anxious": 0.0,
        "avoidant": 0.0,
        "disorganized": 0.0,
    }


def _normalize_scores(raw_scores: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, score) for score in raw_scores.values())
    if total <= 0.0:
        return _empty_scores()
    return {
        key: round(max(0.0, score) / total, 3)
        for key, score in raw_scores.items()
    }


def _duration_score(value: float, *, high_at: float) -> float:
    return _clamp(value / high_at if high_at > 0 else 0.0)


def _high(value: float) -> float:
    return _clamp((value - 0.5) / 0.5)


def _low(value: float) -> float:
    return _clamp((0.5 - value) / 0.5)


def _mid(value: float) -> float:
    return _clamp(1.0 - abs(value - 0.5) / 0.5)


def _conflict(a: float, b: float) -> float:
    return abs(_clamp(a) - _clamp(b))


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
