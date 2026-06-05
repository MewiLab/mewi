using UnityEngine;

/// <summary>
/// Runtime scent/history left in a place by an actor.
/// </summary>
[System.Serializable]
public class PresenceTrace
{
    public string zoneId = "";
    public string ownerId = "";
    public string ownerKind = "cat";
    public string description = "";
    public float strength;
    public float lastUpdatedAt;
    public float lifetimeSeconds = 600f;

    public float IntensityAt(float now)
    {
        float lifetime = Mathf.Max(1f, lifetimeSeconds);
        float age = Mathf.Max(0f, now - lastUpdatedAt);
        float freshness = 1f - Mathf.Clamp01(age / lifetime);
        return Mathf.Clamp01(strength * freshness);
    }

    public bool IsExpired(float now)
    {
        return now - lastUpdatedAt > Mathf.Max(1f, lifetimeSeconds);
    }
}
