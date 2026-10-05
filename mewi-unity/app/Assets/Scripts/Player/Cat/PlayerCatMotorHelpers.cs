using System.Collections.Generic;
using UnityEngine;

public static class PlayerCatMotorHelpers
{
    public static bool TryBuildApproachCat(
        Transform player,
        CreatureBlackboard targetCat,
        float minRadius,
        float maxRadius,
        string requestId,
        string correlationId,
        out IntentMessage goTo)
    {
        goTo = default;
        if (player == null || targetCat == null)
            return false;

        float distance = Vector3.Distance(player.position, targetCat.transform.position);
        if (distance <= maxRadius && distance >= minRadius)
            return false;

        string targetId = ResolveTargetId(targetCat);
        goTo = BuildIntent("go_to", requestId, targetId, correlationId);
        return true;
    }

    public static IntentMessage BuildFaceTarget(
        string requestId,
        string targetId,
        string correlationId)
        => BuildIntent("look_at", requestId, targetId, correlationId);

    public static IntentMessage BuildActionSignal(
        string requestId,
        string action,
        string targetId = "",
        string correlationId = "")
        => BuildIntent(action, requestId, targetId, correlationId);

    public static void BuildGesturePlan(
        Transform player,
        PlayerCatTargetLock target,
        string motorAction,
        bool requiresApproach,
        float minRadius,
        float maxRadius,
        string requestId,
        string correlationId,
        List<IntentMessage> actions)
    {
        if (actions == null || !target.IsValid)
            return;

        if (requiresApproach &&
            TryBuildApproachCat(player, target.TargetCat, minRadius, maxRadius, requestId, correlationId, out IntentMessage goTo))
        {
            actions.Add(goTo);
        }

        actions.Add(BuildFaceTarget(requestId, target.TargetId, correlationId));
        if (!string.IsNullOrWhiteSpace(motorAction))
            actions.Add(BuildActionSignal(requestId, motorAction, target.TargetId, correlationId));
    }

    public static string ResolveTargetId(CreatureBlackboard targetCat)
    {
        if (targetCat == null)
            return "";
        if (!string.IsNullOrWhiteSpace(targetCat.CreatureId))
            return targetCat.CreatureId.Trim().ToLowerInvariant();
        return targetCat.name.Trim().ToLowerInvariant();
    }

    static IntentMessage BuildIntent(
        string action,
        string requestId,
        string targetId,
        string correlationId)
    {
        return IntentMessage.Create(
            action,
            LayerSource.Mind,
            -1f,
            default,
            InteractionSequenceBuilder.NextCommandId("player_cat"),
            requestId ?? "",
            targetId ?? "",
            correlationId ?? "");
    }
}
