using UnityEngine;

/// <summary>
/// Converts shared creature-prefab motor language into report action language.
///
/// Report "approach" is relational: the human-controlled actor is moving
/// toward a report cat. It is not a distinct animation or prefab action.
/// </summary>
public static class ReportActionClassifier
{
    public const string Approach = "approach";
    public const string Retreat = "retreat";
    public const string OfferItem = "offer_item";
    public const string Wait = "wait";
    public const string StopMoving = "stop_moving";
    public const string CallOut = "call_out";
    public const string PetAttempt = "pet_attempt";

    public static string FromHumanMotorIntent(string intent, bool targetIsReportCat)
    {
        string normalized = ToSnakeCase(intent);
        if (string.IsNullOrEmpty(normalized))
            return "";

        switch (normalized)
        {
            case "go_to":
            case "move":
            case "follow":
            case "investigate":
                return targetIsReportCat ? Approach : normalized;
            case "flee":
                return Retreat;
            case "idle":
            case "sit":
            case "wait":
                return Wait;
            case "stop":
            case "stop_moving":
                return StopMoving;
            case "vocalize":
                return CallOut;
            default:
                return normalized;
        }
    }

    public static string ToSnakeCase(string value)
    {
        if (string.IsNullOrWhiteSpace(value))
            return "";

        string trimmed = value.Trim();
        char[] chars = new char[trimmed.Length];
        for (int i = 0; i < trimmed.Length; i++)
        {
            char c = trimmed[i];
            chars[i] = char.IsWhiteSpace(c) || c == '-' ? '_' : char.ToLowerInvariant(c);
        }
        return new string(chars);
    }

    public static bool IsApproachByDistance(
        float previousDistance,
        float currentDistance,
        float minDeltaMeters,
        float maxDistanceMeters,
        out float speedMps,
        float elapsedSeconds)
    {
        speedMps = 0f;
        if (elapsedSeconds <= Mathf.Epsilon)
            return false;

        float delta = previousDistance - currentDistance;
        speedMps = Mathf.Max(0f, delta / elapsedSeconds);
        return currentDistance <= maxDistanceMeters && delta >= minDeltaMeters;
    }

    public static bool IsRetreatByDistance(
        float previousDistance,
        float currentDistance,
        float minDeltaMeters,
        float maxDistanceMeters,
        out float speedMps,
        float elapsedSeconds)
    {
        speedMps = 0f;
        if (elapsedSeconds <= Mathf.Epsilon)
            return false;

        float delta = currentDistance - previousDistance;
        speedMps = Mathf.Max(0f, delta / elapsedSeconds);
        return previousDistance <= maxDistanceMeters && delta >= minDeltaMeters;
    }
}

