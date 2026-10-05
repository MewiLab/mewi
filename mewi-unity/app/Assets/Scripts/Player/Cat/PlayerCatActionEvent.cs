using UnityEngine;

public readonly struct PlayerCatActionEvent
{
    public readonly string EventId;
    public readonly string CorrelationId;
    public readonly string ActorId;
    public readonly string TargetCatId;
    public readonly string Kind;
    public readonly string Phase;
    public readonly Vector3 ActorPosition;
    public readonly Vector3 TargetPosition;
    public readonly float DistanceMeters;
    public readonly float FacingDot;
    public readonly float Confidence;
    public readonly double TimestampSeconds;
    public readonly string BehaviorKey;
    public readonly string MotorAction;

    public PlayerCatActionEvent(
        string eventId,
        string correlationId,
        string actorId,
        string targetCatId,
        string kind,
        string phase,
        Vector3 actorPosition,
        Vector3 targetPosition,
        float distanceMeters,
        float facingDot,
        float confidence,
        double timestampSeconds,
        string behaviorKey,
        string motorAction)
    {
        EventId = eventId ?? "";
        CorrelationId = correlationId ?? "";
        ActorId = actorId ?? "";
        TargetCatId = targetCatId ?? "";
        Kind = kind ?? "";
        Phase = phase ?? "";
        ActorPosition = actorPosition;
        TargetPosition = targetPosition;
        DistanceMeters = distanceMeters;
        FacingDot = facingDot;
        Confidence = confidence;
        TimestampSeconds = timestampSeconds;
        BehaviorKey = behaviorKey ?? "";
        MotorAction = motorAction ?? "";
    }

    public bool IsReactionEligible =>
        Phase == "committed" ||
        Phase == "completed";
}
