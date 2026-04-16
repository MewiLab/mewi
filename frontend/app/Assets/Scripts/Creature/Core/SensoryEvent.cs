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
    public string    label;       // human-readable name, e.g. "BP_House_2"
    public string    category;    // semantic class, e.g. "house", "lantern", "shelter"

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

    public static SensoryEvent Create(SenseType t, Vector3 pos, float intensity, Transform src = null, string label = null, string category = null)
    {
        return new SensoryEvent
        {
            type      = t,
            position  = pos,
            intensity = intensity,
            timestamp = Time.time,
            source    = src,
            label     = label ?? src?.name,
            category  = category ?? "unknown"
        };
    }

    public override string ToString()
    {
        return $"--- EVENT: {type} ---\n" +
            $"Label:     {label}\n" +
            $"Category:  {category}\n" +
            $"Intensity: {intensity:P0} ({intensity:F2})\n" +
            $"Position:  {position}\n" +
            $"Source:    {(source != null ? source.name : "None")}\n" +
            $"Time:      {timestamp:F2}s\n";
    }
}
