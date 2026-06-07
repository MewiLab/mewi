using System;
using System.Collections.Generic;
using UnityEngine;

[Serializable]
public sealed class CatSocialMotionRecipe
{
    [Tooltip("Stable social motion key. Backend social_act.kind may request it.")]
    public string motion = "";

    [Tooltip("Comma-separated aliases this recipe also accepts from social_act.kind/style/tone.")]
    public string aliases = "";

    public List<CatSocialMotionStep> steps = new List<CatSocialMotionStep>();

    public bool Matches(string requested, bool allowTextContains)
    {
        string normalizedRequest = CatSocialMotionUtil.Normalize(requested);
        if (string.IsNullOrEmpty(normalizedRequest))
            return false;

        if (MatchesToken(normalizedRequest, motion, allowTextContains))
            return true;

        if (string.IsNullOrWhiteSpace(aliases))
            return false;

        string[] parts = aliases.Split(',');
        for (int i = 0; i < parts.Length; i++)
        {
            if (MatchesToken(normalizedRequest, parts[i], allowTextContains))
                return true;
        }

        return false;
    }

    public void Append(
        InteractionContext context,
        List<IntentMessage> actions,
        string commandPrefix)
    {
        if (actions == null || steps == null)
            return;

        for (int i = 0; i < steps.Count; i++)
            steps[i]?.Append(context, actions, commandPrefix);
    }

    static bool MatchesToken(string normalizedRequest, string token, bool allowTextContains)
    {
        string normalizedToken = CatSocialMotionUtil.Normalize(token);
        if (string.IsNullOrEmpty(normalizedToken))
            return false;

        if (string.Equals(normalizedRequest, normalizedToken, StringComparison.Ordinal))
            return true;

        return allowTextContains &&
               normalizedRequest.IndexOf(normalizedToken, StringComparison.Ordinal) >= 0;
    }
}

[Serializable]
public sealed class CatSocialMotionStep
{
    public string action = "look_at";
    public bool useDirectiveTarget = true;
    public string targetOverride = "";
    public Vector3 directionHint;

    public void Append(
        InteractionContext context,
        List<IntentMessage> actions,
        string commandPrefix)
    {
        if (actions == null || string.IsNullOrWhiteSpace(action))
            return;

        string target = useDirectiveTarget ? context.TargetId : "";
        if (!string.IsNullOrWhiteSpace(targetOverride))
            target = targetOverride.Trim();

        actions.Add(IntentMessage.Create(
            action.Trim(),
            LayerSource.Mind,
            -1f,
            directionHint,
            InteractionSequenceBuilder.NextCommandId(commandPrefix),
            context.RequestId,
            target));
    }
}

public static class CatSocialMotionUtil
{
    public static bool IsSocialIntent(InteractionContext context)
    {
        return IntentIs(context, "SOCIALIZE") || IntentIs(context, "SEEK_PLAYER");
    }

    public static bool IntentIs(InteractionContext context, string intent)
        => string.Equals(context.Intent, intent, StringComparison.OrdinalIgnoreCase);

    public static bool Contains(string value, string needle)
        => !string.IsNullOrWhiteSpace(value) &&
           !string.IsNullOrWhiteSpace(needle) &&
           value.IndexOf(needle, StringComparison.OrdinalIgnoreCase) >= 0;

    public static CatSocialMotionRecipe FindRecipe(
        string request,
        List<CatSocialMotionRecipe> recipeList,
        bool allowTextContains)
    {
        if (string.IsNullOrWhiteSpace(request) || recipeList == null)
            return null;

        for (int i = 0; i < recipeList.Count; i++)
        {
            CatSocialMotionRecipe recipe = recipeList[i];
            if (recipe != null && recipe.Matches(request, allowTextContains))
                return recipe;
        }

        return null;
    }

    public static T FindOnTarget<T>(Transform target) where T : Component
    {
        if (target == null)
            return null;

        return target.GetComponent<T>()
            ?? target.GetComponentInParent<T>()
            ?? target.GetComponentInChildren<T>();
    }

    public static string Normalize(string value)
    {
        if (string.IsNullOrWhiteSpace(value))
            return "";

        string trimmed = value.Trim().ToLowerInvariant();
        var chars = new char[trimmed.Length];
        int count = 0;
        bool lastWasSeparator = false;

        for (int i = 0; i < trimmed.Length; i++)
        {
            char c = trimmed[i];
            if (char.IsLetterOrDigit(c))
            {
                chars[count++] = c;
                lastWasSeparator = false;
            }
            else if (!lastWasSeparator && count > 0)
            {
                chars[count++] = '_';
                lastWasSeparator = true;
            }
        }

        if (count > 0 && chars[count - 1] == '_')
            count--;

        return count > 0 ? new string(chars, 0, count) : "";
    }
}
