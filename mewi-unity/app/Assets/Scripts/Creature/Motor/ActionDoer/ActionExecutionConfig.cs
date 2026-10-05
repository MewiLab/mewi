using System;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// Tunables for Malbers action-mode execution. Kept separate from the adapter
/// so animation timing can be adjusted without growing the motor bridge.
/// </summary>
[Serializable]
public class ActionExecutionConfig
{
    [Tooltip("If Malbers accepts an action but never enters the mode within this many seconds, clean it up. 0 disables this timeout.")]
    public float activationTimeoutSeconds = 1.5f;

    [Tooltip("Maximum time an action mode may run before cleanup. 0 disables this timeout.")]
    public float maxActionSeconds = 8f;

    [Tooltip("After an action ends or is cleaned up, keep the worker busy for this many seconds before the next queued step.")]
    public float postActionCooldownSeconds = 0.35f;

    [Tooltip("Force-stop Malbers action mode when an action timeout fires.")]
    public bool forceStopOnTimeout = true;

    [Tooltip("Before a new command starts, interrupt any stale Malbers mode left behind by the previous action.")]
    public bool interruptLingeringModeBeforeNewCommand = true;

    [Tooltip("If an old rest/sleep/sit state blocks navigation, ask Malbers to return to locomotion/idle before pathing.")]
    public bool forceLocomotionWhenStateBlocksNavigation = true;

    [Tooltip("Optional per-intent timing overrides. Use -1 to inherit the default for a field.")]
    public List<ActionTimingOverride> overrides = new List<ActionTimingOverride>();

    public float ActivationTimeoutFor(string intent)
        => Resolve(intent, o => o.activationTimeoutSeconds, activationTimeoutSeconds);

    public float MaxActionSecondsFor(string intent)
        => Resolve(intent, o => o.maxActionSeconds, maxActionSeconds);

    public float CooldownSecondsFor(string intent)
        => Resolve(intent, o => o.postActionCooldownSeconds, postActionCooldownSeconds);

    float Resolve(string intent, Func<ActionTimingOverride, float> selector, float fallback)
    {
        if (overrides != null && !string.IsNullOrWhiteSpace(intent))
        {
            for (int i = 0; i < overrides.Count; i++)
            {
                ActionTimingOverride item = overrides[i];
                if (item == null || string.IsNullOrWhiteSpace(item.intent)) continue;
                if (!string.Equals(item.intent.Trim(), intent.Trim(), StringComparison.OrdinalIgnoreCase)) continue;

                float value = selector(item);
                return value >= 0f ? value : Mathf.Max(0f, fallback);
            }
        }

        return Mathf.Max(0f, fallback);
    }
}

[Serializable]
public class ActionTimingOverride
{
    public string intent = "";
    public float activationTimeoutSeconds = -1f;
    public float maxActionSeconds = -1f;
    public float postActionCooldownSeconds = -1f;
}
