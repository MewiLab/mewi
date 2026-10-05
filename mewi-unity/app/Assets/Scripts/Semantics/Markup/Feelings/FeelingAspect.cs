using UnityEngine;

/// <summary>
/// One authored sensory quality on a FeelingEmitter.
/// </summary>
[System.Serializable]
public class FeelingAspect
{
    [Tooltip("Which sensory channel this aspect contributes to.")]
    public FeelingSense sense = FeelingSense.Smell;

    [Tooltip("Compact LLM-facing phrase, e.g. 'fresh fish oil' or 'rough wet rope'.")]
    public string description = "";

    [Tooltip("Detection radius for distance senses. Contact-only senses can keep this at 0.")]
    public float radius = 4f;

    [Range(0f, 1f)]
    [Tooltip("Base strength before distance falloff and trigger modifiers.")]
    public float strength = 0.5f;

    [Tooltip("When this aspect is active.")]
    public FeelingTriggerMode trigger = FeelingTriggerMode.AlwaysOn;

    [Tooltip("Trigger name used by TimedEvent and event-style triggers. Empty uses a mode default.")]
    public string triggerName = "";

    [Tooltip("Optional emitter state required for StateBased or EnvironmentModified aspects.")]
    public string requiredState = "";

    [Tooltip("How long event-triggered aspects stay active after EmitTrigger().")]
    public float duration = 2f;

    [Tooltip("Short behavioral meaning appended to the snapshot string.")]
    public string meaning = "";

    [Tooltip("Whether this aspect can contribute to the one-line feelings summary.")]
    public bool includeInSummary = true;

    public bool HasDescription => !string.IsNullOrWhiteSpace(description);

    public float ClampedStrength => Mathf.Clamp01(strength);

    public float EffectiveDuration => Mathf.Max(0.05f, duration);

    public string EffectiveTriggerName
    {
        get
        {
            if (!string.IsNullOrWhiteSpace(triggerName))
                return triggerName.Trim();

            switch (trigger)
            {
                case FeelingTriggerMode.Collision:     return "impact";
                case FeelingTriggerMode.Kick:          return "kicked";
                case FeelingTriggerMode.Fall:          return "fell";
                case FeelingTriggerMode.EatenOrUsed:   return "used";
                case FeelingTriggerMode.TimedEvent:    return "event";
                default:                               return "";
            }
        }
    }
}
