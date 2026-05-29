using UnityEngine;

/// <summary>
/// One sensory signal detected by the creature during the current perception tick.
/// </summary>
[System.Serializable]
public struct FeelingEvent
{
    public FeelingSense sense;
    public Vector3      position;
    public float        intensity;
    public float        timestamp;
    public Transform    source;
    public string       sourceLabel;
    public string       description;
    public string       meaning;
    public string       triggerName;
    public bool         contact;
    public bool         includeInSummary;

    public static FeelingEvent Create(
        FeelingSense sense,
        Vector3 position,
        float intensity,
        Transform source,
        string sourceLabel,
        string description,
        string meaning = "",
        string triggerName = "",
        bool contact = false,
        bool includeInSummary = true)
    {
        return new FeelingEvent
        {
            sense            = sense,
            position         = position,
            intensity        = Mathf.Clamp01(intensity),
            timestamp        = Time.time,
            source           = source,
            sourceLabel      = string.IsNullOrWhiteSpace(sourceLabel) ? "unknown" : sourceLabel,
            description      = description ?? "",
            meaning          = meaning ?? "",
            triggerName      = triggerName ?? "",
            contact          = contact,
            includeInSummary = includeInSummary,
        };
    }

    public float PriorityScore
    {
        get
        {
            float score = intensity;
            if (contact) score += 0.35f;
            if (!string.IsNullOrWhiteSpace(triggerName)) score += 0.2f;

            switch (sense)
            {
                case FeelingSense.Danger:      score += 0.45f; break;
                case FeelingSense.Taste:       score += 0.25f; break;
                case FeelingSense.Temperature: score += 0.15f; break;
                case FeelingSense.Sound:       score += 0.1f;  break;
                case FeelingSense.Smell:       score += 0.05f; break;
            }

            return score;
        }
    }

    public string ToSnapshotString(Transform self)
    {
        string strength = StrengthBucket(intensity);
        string direction = DirectionBucket(self);
        string distance = DistanceBucket(self);
        string sourceText = string.IsNullOrWhiteSpace(sourceLabel) || sourceLabel == "unknown"
            ? ""
            : $" from {sourceLabel}";
        string meaningText = string.IsNullOrWhiteSpace(meaning) ? "" : $"; {meaning}";

        return $"{strength} {direction} {distance}: {description}{sourceText}{meaningText}";
    }

    public string ToSummaryFragment()
    {
        if (string.IsNullOrWhiteSpace(description)) return "";
        string sourceText = string.IsNullOrWhiteSpace(sourceLabel) || sourceLabel == "unknown"
            ? ""
            : $" from {sourceLabel}";
        return $"{SenseLabel(sense)}: {description}{sourceText}";
    }

    public static int ComparePriority(FeelingEvent a, FeelingEvent b)
        => b.PriorityScore.CompareTo(a.PriorityScore);

    static string StrengthBucket(float value)
    {
        if (value >= 0.75f) return "strong";
        if (value >= 0.45f) return "clear";
        if (value >= 0.2f)  return "soft";
        return "faint";
    }

    string DirectionBucket(Transform self)
    {
        if (self == null) return "all_around";

        Vector3 local = self.InverseTransformPoint(position);
        if (contact)
        {
            if (local.y > 0.75f) return "above";
            if (local.y < -0.35f) return "below";
            return "contact";
        }

        float horizontal = new Vector2(local.x, local.z).magnitude;
        if (horizontal < 0.25f)
        {
            if (local.y > 0.75f) return "above";
            if (local.y < -0.35f) return "below";
            return "all_around";
        }

        float angle = Mathf.Atan2(local.x, local.z) * Mathf.Rad2Deg;
        float abs   = Mathf.Abs(angle);
        if (abs <= 22.5f)  return "front";
        if (abs >= 157.5f) return "back";
        if (angle > 0f)
        {
            if (abs <= 67.5f)  return "front_right";
            if (abs <= 112.5f) return "right";
            return "back_right";
        }
        if (abs <= 67.5f)  return "front_left";
        if (abs <= 112.5f) return "left";
        return "back_left";
    }

    string DistanceBucket(Transform self)
    {
        if (contact) return "contact";
        if (self == null) return "ambient";

        float dist = Vector3.Distance(self.position, position);
        if (dist <= 1.5f) return "near";
        if (dist <= 5f)   return "mid";
        return "far";
    }

    static string SenseLabel(FeelingSense sense)
    {
        switch (sense)
        {
            case FeelingSense.Smell:       return "smell";
            case FeelingSense.Sound:       return "sound";
            case FeelingSense.Texture:     return "texture";
            case FeelingSense.Temperature: return "temperature";
            case FeelingSense.Moisture:    return "moisture";
            case FeelingSense.Vibration:   return "vibration";
            case FeelingSense.Taste:       return "taste";
            case FeelingSense.Comfort:     return "comfort";
            case FeelingSense.Danger:      return "danger";
            default:                       return "signal";
        }
    }
}
