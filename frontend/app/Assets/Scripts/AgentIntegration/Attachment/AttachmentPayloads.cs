using System;

public static class AttachmentAssignedCatTypes
{
    public const string Secure       = "secure";
    public const string Anxious      = "anxious";
    public const string Avoidant     = "avoidant";
    public const string Disorganized = "disorganized";

    public static string Normalize(string value, string fallback = Avoidant)
    {
        if (string.IsNullOrWhiteSpace(value))
            return fallback;

        switch (value.Trim().ToLowerInvariant())
        {
            case Secure:       return Secure;
            case Anxious:      return Anxious;
            case Avoidant:     return Avoidant;
            case Disorganized: return Disorganized;
            default:           return fallback;
        }
    }
}

public static class AttachmentEventTypes
{
    public const string CatWithdrew                = "cat_withdrew";
    public const string CatSoughtPlayer            = "cat_sought_player";
    public const string PlayerApproached           = "player_approached";
    public const string PlayerRetreated            = "player_retreated";
    public const string PlayerReturnedAfterAbsence = "player_returned_after_absence";
    public const string PlayerLeft                 = "player_left";
    public const string PlayerNear                 = "player_near";
    public const string PlayerFar                  = "player_far";
    public const string PlayerInteracted           = "player_interacted";

    public static string Normalize(string value)
    {
        if (string.IsNullOrWhiteSpace(value))
            return "";

        string normalized = value.Trim().ToLowerInvariant();
        return IsKnown(normalized) ? normalized : "";
    }

    public static bool IsKnown(string value)
    {
        if (string.IsNullOrWhiteSpace(value))
            return false;

        switch (value.Trim().ToLowerInvariant())
        {
            case CatWithdrew:
            case CatSoughtPlayer:
            case PlayerApproached:
            case PlayerRetreated:
            case PlayerReturnedAfterAbsence:
            case PlayerLeft:
            case PlayerNear:
            case PlayerFar:
            case PlayerInteracted:
                return true;
            default:
                return false;
        }
    }
}

[Serializable]
public class AttachmentSessionPayload
{
    public string session_id = "";
    public string cat_id = "";
    public string cat_assigned_type = AttachmentAssignedCatTypes.Avoidant;
    public AttachmentEventPayload[] events = new AttachmentEventPayload[0];
}

[Serializable]
public class AttachmentEventPayload
{
    public string event_name = ""; // Editor-readable mirror for Inspector/debugging.
    public string event_type = ""; // Compatibility mirror for tools that dislike reserved names.
    public string @event = "";
    public float t;
    public float distance;
    public AttachmentEventMeta meta = new AttachmentEventMeta();
}

[Serializable]
public class AttachmentEventMeta
{
    public string source = "";
    public string action = "";
    public string target = "";
    public string zone = "";
    public string note = "";
    public string cat_intent = "";
    public string target_key = "";
    public bool player_visible;
}

[Serializable]
public class AttachmentAnalysisResponse
{
    public string session_id = "";
    public string cat_id = "";
    public string cat_assigned_type = "";
    public string player_attachment_estimate = "";
    public AttachmentScores scores = new AttachmentScores();
    public string confidence = "";
    public int n_events;
    public AttachmentSessionFeaturesResponse features = new AttachmentSessionFeaturesResponse();
    public string[] rule_trace = new string[0];
}

[Serializable]
public class AttachmentScores
{
    public float secure;
    public float anxious;
    public float avoidant;
    public float disorganized;
}

[Serializable]
public class AttachmentSessionFeaturesResponse
{
    public string session_id = "";
    public string cat_id = "";
    public string cat_assigned_type = "";
    public float reapproach_latency_mean;
    public float pursuit_ratio;
    public float time_near_ratio;
    public float reunion_response;
    public float withdrawal_tolerance;
    public int n_events;
}
