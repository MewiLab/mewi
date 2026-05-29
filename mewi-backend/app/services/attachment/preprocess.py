from __future__ import annotations

from statistics import mean

from app.models.attachment import (
    AttachmentEventType,
    AttachmentSessionFeatures,
    CatAssignedType,
    RawAttachmentEvent,
)

NEAR_DISTANCE_METERS = 2.0
REUNION_DISTANCE_METERS = 5.0
WITHDRAWAL_RESPONSE_WINDOW_SECONDS = 30.0
REUNION_RESPONSE_WINDOW_SECONDS = 20.0


def preprocess_attachment_session(
    events: list[RawAttachmentEvent],
    *,
    cat_assigned_type: CatAssignedType,
) -> AttachmentSessionFeatures:
    """Convert raw Unity events into one theory-grounded feature row."""

    if not events:
        raise ValueError("at least one attachment event is required")

    ordered = sorted(events, key=lambda event: event.t)
    first = ordered[0]

    return AttachmentSessionFeatures(
        session_id=first.session_id,
        cat_id=first.cat_id,
        cat_assigned_type=cat_assigned_type,
        reapproach_latency_mean=_reapproach_latency_mean(ordered),
        pursuit_ratio=_pursuit_ratio(ordered),
        time_near_ratio=_time_near_ratio(ordered),
        reunion_response=_reunion_response(ordered),
        withdrawal_tolerance=_withdrawal_tolerance(ordered),
        n_events=len(ordered),
    )


def _reapproach_latency_mean(events: list[RawAttachmentEvent]) -> float:
    latencies: list[float] = []
    for event in events:
        if event.event != AttachmentEventType.CAT_WITHDREW:
            continue
        next_approach = _next_event(
            events,
            after=event.t,
            event_type=AttachmentEventType.PLAYER_APPROACHED,
            within=WITHDRAWAL_RESPONSE_WINDOW_SECONDS,
        )
        if next_approach is not None:
            latencies.append(next_approach.t - event.t)
    return round(mean(latencies), 3) if latencies else 0.0


def _pursuit_ratio(events: list[RawAttachmentEvent]) -> float:
    approaches = 0
    retreats = 0
    for withdrawal in events:
        if withdrawal.event != AttachmentEventType.CAT_WITHDREW:
            continue
        for event in _events_after(events, withdrawal.t, WITHDRAWAL_RESPONSE_WINDOW_SECONDS):
            if event.event == AttachmentEventType.PLAYER_APPROACHED:
                approaches += 1
            elif event.event == AttachmentEventType.PLAYER_RETREATED:
                retreats += 1

    total = approaches + retreats
    return round(approaches / total, 3) if total else 0.0


def _time_near_ratio(events: list[RawAttachmentEvent]) -> float:
    distance_events = [event for event in events if event.distance is not None]
    if not distance_events:
        return 0.0

    near_count = sum(1 for event in distance_events if event.distance is not None and event.distance <= NEAR_DISTANCE_METERS)
    return round(near_count / len(distance_events), 3)


def _reunion_response(events: list[RawAttachmentEvent]) -> float:
    scores: list[float] = []
    for reunion in events:
        if reunion.event != AttachmentEventType.PLAYER_RETURNED_AFTER_ABSENCE:
            continue

        window = _events_after(events, reunion.t, REUNION_RESPONSE_WINDOW_SECONDS)
        score = 0.0
        if any(event.event == AttachmentEventType.PLAYER_APPROACHED for event in window):
            score = max(score, 0.8)
        if any(event.event == AttachmentEventType.PLAYER_INTERACTED for event in window):
            score = max(score, 1.0)

        distances = [event.distance for event in window if event.distance is not None]
        if distances:
            nearest = min(distances)
            closeness = 1.0 - min(nearest / REUNION_DISTANCE_METERS, 1.0)
            score = max(score, closeness)

        scores.append(score)

    return round(mean(scores), 3) if scores else 0.0


def _withdrawal_tolerance(events: list[RawAttachmentEvent]) -> float:
    tolerances: list[float] = []
    for withdrawal in events:
        if withdrawal.event != AttachmentEventType.CAT_WITHDREW:
            continue

        response_window = _events_after(events, withdrawal.t, WITHDRAWAL_RESPONSE_WINDOW_SECONDS)
        retreat = next(
            (
                event for event in response_window
                if event.event in {
                    AttachmentEventType.PLAYER_RETREATED,
                    AttachmentEventType.PLAYER_FAR,
                }
            ),
            None,
        )
        if retreat is not None:
            tolerances.append(retreat.t - withdrawal.t)
            continue

        near_events = [
            event for event in response_window
            if (
                event.event == AttachmentEventType.PLAYER_NEAR
                or (event.distance is not None and event.distance <= NEAR_DISTANCE_METERS)
            )
        ]
        if near_events:
            tolerances.append(max(event.t for event in near_events) - withdrawal.t)
        elif response_window:
            tolerances.append(0.0)

    return round(mean(tolerances), 3) if tolerances else 0.0


def _next_event(
    events: list[RawAttachmentEvent],
    *,
    after: float,
    event_type: AttachmentEventType,
    within: float,
) -> RawAttachmentEvent | None:
    return next(
        (
            event for event in events
            if event.t > after
            and event.t - after <= within
            and event.event == event_type
        ),
        None,
    )


def _events_after(
    events: list[RawAttachmentEvent],
    after: float,
    within: float,
) -> list[RawAttachmentEvent]:
    return [
        event for event in events
        if event.t > after and event.t - after <= within
    ]
