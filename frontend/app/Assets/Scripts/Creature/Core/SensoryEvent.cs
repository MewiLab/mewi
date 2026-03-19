using UnityEngine;

/// <summary>
/// A single thing the cat perceived this frame.
/// Perception writes these; Reflex and Tactical read them.
/// </summary>
[System.Serializable]
public struct SensoryEvent
{
    public SenseType type;
    public Vector3   position;
    public float     intensity;   // 0–1, how strong/close/loud
    public float     timestamp;
    public Transform source;      // nullable — not every event has a transform

    public enum SenseType
    {
        PlayerNearby,
        PlayerApproachFast,
        SoundHeard,
        FoodSpotted,
        ObstacleClose,
        TouchedByPlayer
    }

    public static SensoryEvent Create(SenseType t, Vector3 pos, float intensity, Transform src = null)
    {
        return new SensoryEvent
        {
            type      = t,
            position  = pos,
            intensity = intensity,
            timestamp = Time.time,
            source    = src
        };
    }
}
