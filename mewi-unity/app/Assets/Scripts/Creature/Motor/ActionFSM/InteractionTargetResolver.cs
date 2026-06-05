using UnityEngine;

/// <summary>
/// Thin target lookup used by the behavior graph. Mirrors the motor's target
/// resolution without giving providers access to motor internals.
/// </summary>
public static class InteractionTargetResolver
{
    public static bool TryResolve(
        CreatureBlackboard board,
        string targetId,
        out Transform target)
    {
        target = null;
        if (string.IsNullOrWhiteSpace(targetId))
            return false;

        string key = targetId.Trim();

        if (board != null && board.TryResolveRecentTarget(key, out target))
            return true;

        NamedTargetRegistry registry = Object.FindFirstObjectByType<NamedTargetRegistry>();
        if (registry != null && registry.TryResolve(key, out target))
            return true;

        GameObject found = GameObject.Find(key);
        if (found == null)
            return false;

        target = found.transform;
        return true;
    }
}
