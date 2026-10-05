using System;
using UnityEngine;

public enum SocialStimulusPreemption
{
    None = 0,
    Soft = 1,
    Hard = 2,
}

public readonly struct SocialStimulus
{
    public readonly string EventId;
    public readonly string CorrelationId;
    public readonly string ActorId;
    public readonly string TargetCatId;
    public readonly string Kind;
    public readonly string SourceEventId;
    public readonly Vector3 ActorPosition;
    public readonly Vector3 TargetPosition;
    public readonly float DistanceMeters;
    public readonly float FacingDot;
    public readonly float Confidence;
    public readonly double TimestampSeconds;

    public SocialStimulus(PlayerCatActionEvent actionEvent)
    {
        EventId = $"stim-{actionEvent.EventId}";
        CorrelationId = actionEvent.CorrelationId ?? "";
        ActorId = actionEvent.ActorId ?? "";
        TargetCatId = actionEvent.TargetCatId ?? "";
        Kind = actionEvent.Kind ?? "";
        SourceEventId = actionEvent.EventId ?? "";
        ActorPosition = actionEvent.ActorPosition;
        TargetPosition = actionEvent.TargetPosition;
        DistanceMeters = actionEvent.DistanceMeters;
        FacingDot = actionEvent.FacingDot;
        Confidence = actionEvent.Confidence;
        TimestampSeconds = actionEvent.TimestampSeconds;
    }

    public bool IsValid =>
        !string.IsNullOrWhiteSpace(CorrelationId) &&
        !string.IsNullOrWhiteSpace(ActorId) &&
        !string.IsNullOrWhiteSpace(TargetCatId) &&
        !string.IsNullOrWhiteSpace(Kind);

    public bool IsExpired(double nowSeconds, float ttlSeconds)
        => ttlSeconds > 0f && nowSeconds - TimestampSeconds > ttlSeconds;

    public bool SameCoalescingKey(SocialStimulus other)
    {
        return string.Equals(ActorId, other.ActorId, StringComparison.OrdinalIgnoreCase) &&
               string.Equals(TargetCatId, other.TargetCatId, StringComparison.OrdinalIgnoreCase) &&
               string.Equals(Kind, other.Kind, StringComparison.OrdinalIgnoreCase);
    }
}
