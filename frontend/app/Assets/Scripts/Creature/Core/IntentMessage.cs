using UnityEngine;

public enum LayerSource
{
    Mind     = 0,
    Tactical = 1,
    Reflex   = 2,
}

public struct IntentMessage
{
   
    public string intent;  // eg. "flinch", "wander", "flee"
    public LayerSource source;  // eg. mind, perception, relax
    public float setTime; // Used for expiry checks


    /// <summary>
    /// How long this slot stays active. Negative = indefinite (tactical, mind).
    /// Positive = auto-expires after this many seconds (reflex).
    /// </summary>
    public float duration;
    public Vector3 directionHint; // direction or target associated with this intent
    public bool IsActive => duration < 0f || (Time.time - setTime) < duration; // Is this slot still active? Checks expiry if duration is positive
    public float TimeRemaining =>
        duration < 0f ? -1f : Mathf.Max(0f, duration - (Time.time - setTime)); // How many seconds remain before this slot expires. -1 if indefinite.



    public static IntentMessage Create(string intent, LayerSource source, float duration = -1f, Vector3 directionHint = default)
    {
        return new IntentMessage
        {
            intent        = intent,
            source        = source,
            setTime       = Time.time,
            duration      = duration,
            directionHint = directionHint,
        };
    }

    public override string ToString()
    {
        string dur = duration < 0f ? "∞" : $"{TimeRemaining:F1}s";
        return $"[{source}] {intent} ({dur})";
    }
}
