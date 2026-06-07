using System;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// Designer-authored finite micro-action recipes for a target.
/// Use this for custom props before adding a dedicated provider class.
/// </summary>
[DisallowMultipleComponent]
public sealed class AuthoredInteractionProvider : MonoBehaviour, IInteractionProvider
{
    [SerializeField] List<AuthoredInteractionRecipe> recipes = new List<AuthoredInteractionRecipe>();

    public bool TryBuildInteraction(InteractionContext context, List<IntentMessage> actions)
    {
        if (actions == null || recipes == null)
            return false;

        AuthoredInteractionRecipe fallback = null;
        for (int i = 0; i < recipes.Count; i++)
        {
            AuthoredInteractionRecipe recipe = recipes[i];
            if (recipe == null)
                continue;

            if (recipe.IsFallback)
            {
                fallback ??= recipe;
                continue;
            }

            if (recipe.Matches(context.Intent))
                return AppendRecipe(recipe, context, actions);
        }

        return fallback != null && AppendRecipe(fallback, context, actions);
    }

    static bool AppendRecipe(
        AuthoredInteractionRecipe recipe,
        InteractionContext context,
        List<IntentMessage> actions)
    {
        int before = actions.Count;
        recipe.Append(context, actions);
        return actions.Count > before;
    }
}

[Serializable]
public sealed class AuthoredInteractionRecipe
{
    [Tooltip("Backend high-level intent this recipe handles. Empty means fallback for any intent.")]
    public string intent = "";

    public List<AuthoredInteractionStep> steps = new List<AuthoredInteractionStep>();

    public bool IsFallback => string.IsNullOrWhiteSpace(intent);

    public bool Matches(string requestedIntent)
    {
        if (IsFallback)
            return true;
        return string.Equals(
            intent.Trim(),
            requestedIntent ?? "",
            StringComparison.OrdinalIgnoreCase);
    }

    public void Append(InteractionContext context, List<IntentMessage> actions)
    {
        if (actions == null || steps == null)
            return;

        for (int i = 0; i < steps.Count; i++)
            steps[i]?.Append(context, actions);
    }
}

[Serializable]
public sealed class AuthoredInteractionStep
{
    public string action = "go_to";
    public bool useDirectiveTarget = true;
    public string targetOverride = "";
    public Vector3 directionHint;

    public void Append(InteractionContext context, List<IntentMessage> actions)
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
            InteractionSequenceBuilder.NextCommandId("authored"),
            context.RequestId,
            target));
    }
}
