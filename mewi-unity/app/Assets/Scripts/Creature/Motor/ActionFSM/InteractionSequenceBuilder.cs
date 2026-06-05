using System;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// Builds finite goal-owned micro-action sequences from target markup.
/// Existing scene markup stays authoritative; explicit providers override
/// inferred recipes.
/// </summary>
public static class InteractionSequenceBuilder
{
    static int _commandSeq;

    public static string NextCommandId(string prefix)
    {
        string clean = string.IsNullOrWhiteSpace(prefix) ? "interaction" : prefix.Trim();
        return $"{clean}:{_commandSeq++:X6}";
    }

    public static bool TryBuild(
        CreatureBlackboard board,
        CreatureBlackboard.MindDirective directive,
        List<IntentMessage> actions,
        out string source)
    {
        source = "";
        if (actions == null)
            return false;

        actions.Clear();
        if (!directive.IsValid || string.IsNullOrWhiteSpace(directive.FocusTarget))
            return false;

        if (!InteractionTargetResolver.TryResolve(board, directive.FocusTarget, out Transform target) ||
            target == null)
        {
            source = "target_unresolved";
            return false;
        }

        var context = new InteractionContext(board, directive, target);

        if (TryExplicitProvider(target, context, actions))
        {
            source = "explicit_provider";
            return true;
        }

        if (TryBuildFromMarkup(context, actions, out source))
            return true;

        source = "no_provider";
        return false;
    }

    static bool TryExplicitProvider(
        Transform target,
        InteractionContext context,
        List<IntentMessage> actions)
    {
        if (target == null)
            return false;

        if (TryProviderList(target.GetComponents<MonoBehaviour>(), context, actions))
            return true;
        if (TryProviderList(target.GetComponentsInParent<MonoBehaviour>(), context, actions))
            return true;
        return TryProviderList(target.GetComponentsInChildren<MonoBehaviour>(), context, actions);
    }

    static bool TryProviderList(
        MonoBehaviour[] behaviours,
        InteractionContext context,
        List<IntentMessage> actions)
    {
        if (behaviours == null)
            return false;

        for (int i = 0; i < behaviours.Length; i++)
        {
            var provider = behaviours[i] as IInteractionProvider;
            if (provider == null)
                continue;

            int before = actions.Count;
            if (provider.TryBuildInteraction(context, actions) && actions.Count > before)
                return true;

            if (actions.Count > before)
                actions.RemoveRange(before, actions.Count - before);
        }

        return false;
    }

    static bool TryBuildFromMarkup(
        InteractionContext context,
        List<IntentMessage> actions,
        out string source)
    {
        source = "";
        Transform target = context.Target;
        SmartObject smart = FindOnTarget<SmartObject>(target);
        ZoneVolume zone = FindOnTarget<ZoneVolume>(target);

        if (FindOnTarget<EdibleObject>(target) != null || HasTag(smart, "prop.food") || HasTag(smart, "food"))
        {
            BuildFood(context, actions);
            source = "markup_food";
            return true;
        }

        if (FindOnTarget<CatDoorController>(target) != null ||
            FindOnTarget<CatAutoClimbPoint>(target) != null)
        {
            BuildPassage(context, actions);
            source = "markup_passage";
            return true;
        }

        if (IsPlayerTarget(context, smart))
        {
            BuildCatPlayerSocial(context, actions);
            source = "markup_cat_player_social";
            return true;
        }

        if (IsCatTarget(context, smart))
        {
            BuildCatCatSocial(context, actions);
            source = "markup_cat_cat_social";
            return true;
        }

        if (HasRestMarkup(target, smart))
        {
            BuildRest(context, actions);
            source = "markup_rest";
            return true;
        }

        if (HasTag(smart, "prop.toy") || HasTag(smart, "toy") || HasTag(smart, "play"))
        {
            BuildToy(context, actions);
            source = "markup_toy";
            return true;
        }

        if (HasTag(smart, "scent") || HasTag(smart, "hint") || HasTag(smart, "trace"))
        {
            BuildHint(context, actions);
            source = "markup_hint";
            return true;
        }

        if (zone != null || HasTag(smart, "place") || HasTag(smart, "zone"))
        {
            BuildPlace(context, actions);
            source = "markup_place";
            return true;
        }

        return false;
    }

    static void BuildFood(InteractionContext context, List<IntentMessage> actions)
    {
        Add(actions, context, "go_to");
        Add(actions, context, "smell");
        if (IntentIs(context, "SEEK_FOOD"))
            Add(actions, context, "eat");
        else
            Add(actions, context, "look_at");
    }

    static void BuildPassage(InteractionContext context, List<IntentMessage> actions)
    {
        Add(actions, context, "go_to");
        Add(actions, context, "look_at");
    }

    static void BuildCatPlayerSocial(InteractionContext context, List<IntentMessage> actions)
    {
        if (CatPlayerSocialFsm.TryAppendDefaultSequence(context, actions))
            return;

        BuildLegacySocial(context, actions);
    }

    static void BuildCatCatSocial(InteractionContext context, List<IntentMessage> actions)
    {
        if (CatCatSocialFsm.TryAppendDefaultSequence(context, actions))
            return;

        BuildLegacySocial(context, actions);
    }

    static void BuildLegacySocial(InteractionContext context, List<IntentMessage> actions)
    {
        Add(actions, context, "go_to");
        Add(actions, context, "look_at");
        if (IntentIs(context, "SOCIALIZE") || IntentIs(context, "SEEK_PLAYER"))
        {
            Add(actions, context, "vocalize");
            Add(actions, context, "sit", targetKey: "");
        }
        else
        {
            Add(actions, context, "smell");
        }
    }

    static void BuildRest(InteractionContext context, List<IntentMessage> actions)
    {
        Add(actions, context, "go_to");
        Add(actions, context, "smell");

        if (!IntentIs(context, "REST"))
        {
            Add(actions, context, "look_around", targetKey: "");
            return;
        }

        float energy = context.Board != null && context.Board.mood != null
            ? context.Board.mood.energy
            : 0.6f;
        string action = energy < 0.35f || Contains(context.Style, "sleep") ? "sleep" : "lie";
        Add(actions, context, action, targetKey: "");
    }

    static void BuildToy(InteractionContext context, List<IntentMessage> actions)
    {
        Add(actions, context, "go_to");
        Add(actions, context, "smell");
        Add(actions, context, Contains(context.Style, "loud") ? "vocalize" : "scratch", targetKey: "");
    }

    static void BuildHint(InteractionContext context, List<IntentMessage> actions)
    {
        Add(actions, context, "go_to");
        Add(actions, context, "smell");
        Add(actions, context, "look_around", targetKey: "");
    }

    static void BuildPlace(InteractionContext context, List<IntentMessage> actions)
    {
        Add(actions, context, "go_to");
        Add(actions, context, "look_around", targetKey: "");
        Add(actions, context, "smell");
    }

    static void Add(
        List<IntentMessage> actions,
        InteractionContext context,
        string action,
        string targetKey = null,
        Vector3 directionHint = default)
    {
        if (actions == null || string.IsNullOrWhiteSpace(action))
            return;

        string target = targetKey ?? context.TargetId;
        actions.Add(IntentMessage.Create(
            action,
            LayerSource.Mind,
            -1f,
            directionHint,
            NextCommandId("interaction"),
            context.RequestId,
            target ?? ""));
    }

    static T FindOnTarget<T>(Transform target) where T : Component
    {
        if (target == null)
            return null;

        return target.GetComponent<T>()
            ?? target.GetComponentInParent<T>()
            ?? target.GetComponentInChildren<T>();
    }

    static bool IsCatTarget(InteractionContext context, SmartObject smart)
    {
        if (IsPlayerTarget(context, smart))
            return false;

        CreatureBlackboard targetBoard = FindOnTarget<CreatureBlackboard>(context.Target);
        if (targetBoard != null && targetBoard != context.Board)
            return true;

        return HasTag(smart, "entity.cat");
    }

    static bool IsPlayerTarget(InteractionContext context, SmartObject smart)
    {
        if (HasTag(smart, "entity.player") || HasTag(smart, "player"))
            return true;

        string name = context.Target != null ? context.Target.root.name : "";
        return Contains(name, "player");
    }

    static bool HasRestMarkup(Transform target, SmartObject smart)
    {
        if (HasTag(smart, "prop.rest") || HasTag(smart, "rest") ||
            HasTag(smart, "comfort") || HasTag(smart, "bed") || HasTag(smart, "nest"))
        {
            return true;
        }

        CatNavigationAnchors anchors = FindOnTarget<CatNavigationAnchors>(target);
        if (anchors == null)
            return false;

        IReadOnlyList<CatNavigationPoint> points = anchors.Points;
        for (int i = 0; i < points.Count; i++)
        {
            CatNavigationPoint point = points[i];
            if (point != null && point.kind == CatNavigationPointKind.Rest)
                return true;
        }

        return false;
    }

    static bool HasTag(SmartObject smart, string tag)
        => smart != null && smart.HasTag(tag);

    static bool IntentIs(InteractionContext context, string intent)
        => string.Equals(context.Intent, intent, StringComparison.OrdinalIgnoreCase);

    static bool Contains(string value, string needle)
        => !string.IsNullOrWhiteSpace(value) &&
           !string.IsNullOrWhiteSpace(needle) &&
           value.IndexOf(needle, StringComparison.OrdinalIgnoreCase) >= 0;
}
