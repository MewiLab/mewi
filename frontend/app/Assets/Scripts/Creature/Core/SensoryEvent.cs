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
    public string    label;        // GameObject.name — meaningful when type == NearbyObject

    public enum SenseType
    {
        PlayerNearby,
        PlayerApproachFast,
        SoundHeard,
        FoodSpotted,
        ObstacleClose,
        TouchedByPlayer,
        NearbyObject       // generic — differentiated by label (GameObject name)
    }

    public static SensoryEvent Create(SenseType t, Vector3 pos, float intensity, Transform src = null, string label = null)
    {
        return new SensoryEvent
        {
            type      = t,
            position  = pos,
            intensity = intensity,
            timestamp = Time.time,
            source    = src,
            label     = label ?? src?.name
        };
    }

    public override string ToString()
    {
        // Using @ string literal to allow for easy multi-line formatting
        return $"--- EVENT: {type} ---\n" +
            $"Label:     {label}\n" +
            $"Intensity: {intensity:P0} ({intensity:F2})\n" +
            $"Position:  {position}\n" +
            $"Source:    {(source != null ? source.name : "None")}\n" +
            $"Time:      {timestamp:F2}s\n";
    }
}
