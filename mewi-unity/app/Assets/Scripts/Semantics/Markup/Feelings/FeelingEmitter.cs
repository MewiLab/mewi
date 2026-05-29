using System;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// Authored sensory profile for a prop, creature, player, or zone.
/// Passive data source: CreaturePerception scans this and writes FeelingEvents.
/// </summary>
[DisallowMultipleComponent]
public class FeelingEmitter : MonoBehaviour
{
    [Tooltip("Human-readable source name sent to the agent. Empty uses SmartObject label, parent, or GameObject name.")]
    public string label = "";

    [Tooltip("Optional override for perceived position. Empty uses SmartObject perception center or this transform.")]
    public Transform perceptionCenter;

    [Tooltip("Authored sensory qualities this object or zone can emit.")]
    public List<FeelingAspect> aspects = new List<FeelingAspect>();

    [Tooltip("Initial authored states, e.g. wet, burning, fresh, rotten, moving, familiar.")]
    public List<string> initialStates = new List<string>();

    readonly Dictionary<string, float> _triggerExpiry =
        new Dictionary<string, float>(StringComparer.OrdinalIgnoreCase);
    readonly HashSet<string> _states =
        new HashSet<string>(StringComparer.OrdinalIgnoreCase);
    readonly HashSet<Transform> _contactSources = new HashSet<Transform>();

    SmartObject _smartObject;

    public Vector3 Position
    {
        get
        {
            if (perceptionCenter != null) return perceptionCenter.position;
            if (_smartObject == null) _smartObject = GetComponent<SmartObject>() ?? GetComponentInParent<SmartObject>();
            return _smartObject != null ? _smartObject.Position : transform.position;
        }
    }

    public string Label
    {
        get
        {
            if (!string.IsNullOrWhiteSpace(label)) return label.Trim();
            if (_smartObject == null) _smartObject = GetComponent<SmartObject>() ?? GetComponentInParent<SmartObject>();
            if (_smartObject != null) return _smartObject.Label;
            return transform.parent != null ? transform.parent.name : gameObject.name;
        }
    }

    void Awake()
    {
        _smartObject = GetComponent<SmartObject>() ?? GetComponentInParent<SmartObject>();
        SeedInitialStates();
    }

    void OnValidate()
    {
        if (aspects == null) aspects = new List<FeelingAspect>();
        for (int i = 0; i < aspects.Count; i++)
        {
            FeelingAspect aspect = aspects[i];
            if (aspect == null) continue;
            aspect.strength = Mathf.Clamp01(aspect.strength);
            aspect.radius   = Mathf.Max(0f, aspect.radius);
            aspect.duration = Mathf.Max(0.05f, aspect.duration);
        }
    }

    public void SetState(string state, bool active)
    {
        string key = NormalizeKey(state);
        if (string.IsNullOrEmpty(key)) return;

        if (active) _states.Add(key);
        else        _states.Remove(key);
    }

    public bool HasState(string state)
    {
        string key = NormalizeKey(state);
        return !string.IsNullOrEmpty(key) && _states.Contains(key);
    }

    public void EmitTrigger(string triggerName)
    {
        EmitTrigger(triggerName, -1f);
    }

    public void EmitTrigger(string triggerName, float durationOverride)
    {
        string key = NormalizeKey(triggerName);
        if (string.IsNullOrEmpty(key)) return;

        float duration = durationOverride > 0f ? durationOverride : ResolveTriggerDuration(key);
        _triggerExpiry[key] = Time.time + Mathf.Max(0.05f, duration);
    }

    public void MarkContact(Transform other, bool active)
    {
        Transform key = ResolveContactRoot(other);
        if (key == null) return;

        if (active) _contactSources.Add(key);
        else        _contactSources.Remove(key);
    }

    public bool IsTouching(Transform self)
    {
        Transform key = ResolveContactRoot(self);
        return key != null && _contactSources.Contains(key);
    }

    public bool TryBuildEvent(
        FeelingAspect aspect,
        Transform self,
        CreatureConfig config,
        out FeelingEvent evt)
    {
        evt = default;
        if (aspect == null || !aspect.HasDescription) return false;
        if (!IsAspectActive(aspect, self)) return false;

        Vector3 pos = Position;
        bool contact = aspect.trigger == FeelingTriggerMode.ContactOnly;
        float strength = aspect.ClampedStrength;
        float intensity = strength;

        if (!contact)
        {
            float maxRadius = config != null && config.feelingScanRadius > 0f
                ? config.feelingScanRadius
                : 12f;
            float radius = aspect.radius > 0f ? aspect.radius : maxRadius;
            float dist = self != null ? Vector3.Distance(self.position, pos) : 0f;
            if (dist > radius) return false;
            intensity *= 1f - Mathf.Clamp01(dist / Mathf.Max(0.01f, radius));
        }

        if (intensity <= 0.01f) return false;

        evt = FeelingEvent.Create(
            aspect.sense,
            pos,
            intensity,
            transform,
            Label,
            aspect.description,
            aspect.meaning,
            aspect.EffectiveTriggerName,
            contact,
            aspect.includeInSummary);
        return true;
    }

    void SeedInitialStates()
    {
        _states.Clear();
        if (initialStates == null) return;
        for (int i = 0; i < initialStates.Count; i++)
        {
            string key = NormalizeKey(initialStates[i]);
            if (!string.IsNullOrEmpty(key)) _states.Add(key);
        }
    }

    bool IsAspectActive(FeelingAspect aspect, Transform self)
    {
        switch (aspect.trigger)
        {
            case FeelingTriggerMode.AlwaysOn:
                return StateRequirementMet(aspect);

            case FeelingTriggerMode.StateBased:
            case FeelingTriggerMode.EnvironmentModified:
                return StateRequirementMet(aspect) &&
                       !string.IsNullOrWhiteSpace(aspect.requiredState);

            case FeelingTriggerMode.ContactOnly:
                return IsTouching(self) && StateRequirementMet(aspect);

            case FeelingTriggerMode.TimedEvent:
            case FeelingTriggerMode.Collision:
            case FeelingTriggerMode.Kick:
            case FeelingTriggerMode.Fall:
            case FeelingTriggerMode.EatenOrUsed:
                return IsTriggerActive(aspect.EffectiveTriggerName) && StateRequirementMet(aspect);

            default:
                return false;
        }
    }

    bool StateRequirementMet(FeelingAspect aspect)
    {
        if (string.IsNullOrWhiteSpace(aspect.requiredState)) return true;
        return HasState(aspect.requiredState);
    }

    bool IsTriggerActive(string triggerName)
    {
        string key = NormalizeKey(triggerName);
        if (string.IsNullOrEmpty(key)) return false;

        if (!_triggerExpiry.TryGetValue(key, out float expiresAt))
            return false;

        if (Time.time <= expiresAt)
            return true;

        _triggerExpiry.Remove(key);
        return false;
    }

    float ResolveTriggerDuration(string triggerName)
    {
        if (aspects == null) return 2f;
        for (int i = 0; i < aspects.Count; i++)
        {
            FeelingAspect aspect = aspects[i];
            if (aspect == null) continue;
            if (string.Equals(aspect.EffectiveTriggerName, triggerName, StringComparison.OrdinalIgnoreCase))
                return aspect.EffectiveDuration;
        }
        return 2f;
    }

    static Transform ResolveContactRoot(Transform t)
    {
        if (t == null) return null;
        CreatureBlackboard board = t.GetComponentInParent<CreatureBlackboard>();
        if (board != null) return board.transform;
        return t.root != null ? t.root : t;
    }

    static string NormalizeKey(string value)
        => string.IsNullOrWhiteSpace(value) ? "" : value.Trim();
}
