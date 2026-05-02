using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// Authoritative runtime marker for any perceptible object — props, agents, zones.
/// Perception reads SmartObject only; names are never queried at runtime.
///
/// Tag convention: dot-delimited, lowercase hierarchy.
///   prop.food.fish        prop.shelter.house       prop.climbable.crate
///   entity.cat.kitten     entity.player
///   zone.harbor           zone.home
///
/// Multiple tags are allowed — a crate with fish on top can be both
/// prop.food.fish and prop.climbable.crate.
///
/// Authoring:
///   - Prefer the SmartObjectBaker to stamp these in bulk.
///   - For hand-authored one-offs (named places, agents), add the component
///     directly and fill in tags + label in the Inspector.
/// </summary>
[DisallowMultipleComponent]
public class SmartObject : MonoBehaviour
{
    [Tooltip("Semantic tags — dot-delimited, lowercase. e.g. prop.food.fish")]
    public List<string> tags = new List<string>();

    [Tooltip("Human-readable name sent to the agent. Empty → falls back to the parent (or self) GameObject name.")]
    public string label;

    [Tooltip("Optional override for perceived position. Empty → uses this transform.")]
    public Transform perceptionCenter;

    public Vector3 Position => perceptionCenter != null ? perceptionCenter.position : transform.position;

    public string Label
    {
        get
        {
            if (!string.IsNullOrEmpty(label)) return label;
            return transform.parent != null ? transform.parent.name : gameObject.name;
        }
    }

    /// <summary>First segment of the first tag. "prop.food.fish" → "prop".</summary>
    public string PrimaryCategory
    {
        get
        {
            if (tags == null || tags.Count == 0) return "unknown";
            var t   = tags[0];
            int dot = t.IndexOf('.');
            return dot < 0 ? t : t.Substring(0, dot);
        }
    }

    /// <summary>Most-specific segment of the first tag. "prop.food.fish" → "fish".</summary>
    public string SpecificCategory
    {
        get
        {
            if (tags == null || tags.Count == 0) return "unknown";
            var t   = tags[0];
            int dot = t.LastIndexOf('.');
            return dot < 0 ? t : t.Substring(dot + 1);
        }
    }

    /// <summary>Prefix match: HasTag("prop.food") matches "prop.food.fish".</summary>
    public bool HasTag(string prefix)
    {
        if (tags == null || string.IsNullOrEmpty(prefix)) return false;
        for (int i = 0; i < tags.Count; i++)
        {
            var t = tags[i];
            if (t == prefix) return true;
            if (t.Length > prefix.Length && t.StartsWith(prefix) && t[prefix.Length] == '.')
                return true;
        }
        return false;
    }
}
