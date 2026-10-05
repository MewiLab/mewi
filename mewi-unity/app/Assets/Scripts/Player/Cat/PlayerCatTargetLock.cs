using UnityEngine;

public readonly struct PlayerCatTargetLock
{
    public readonly CreatureBlackboard TargetCat;
    public readonly string TargetId;
    public readonly float DistanceMeters;
    public readonly float FacingDot;
    public readonly float Confidence;

    public Transform TargetTransform => TargetCat != null ? TargetCat.transform : null;

    public PlayerCatTargetLock(
        CreatureBlackboard targetCat,
        string targetId,
        float distanceMeters,
        float facingDot,
        float confidence)
    {
        TargetCat = targetCat;
        TargetId = targetId ?? "";
        DistanceMeters = distanceMeters;
        FacingDot = facingDot;
        Confidence = confidence;
    }

    public bool IsValid => TargetCat != null && !string.IsNullOrWhiteSpace(TargetId);
}

public interface IPlayerTargetSource
{
    bool TryAcquireNearest(out PlayerCatTargetLock target);
    bool TryCycle(int direction, out PlayerCatTargetLock target);
    bool TryGetCurrent(out PlayerCatTargetLock target);
    void Clear();
}
