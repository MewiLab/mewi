using System;
using System.Collections.Generic;

/// <summary>
/// Single-process publish/subscribe bus for "the cat declared an intent →
/// the world confirms it actually happened" handshakes.
///
/// Used to replace CreatureWorker's hardcoded "completed" status with honest
/// world-driven feedback. See ADR-008.
///
/// Contract:
///   - <see cref="Declare"/>: CreatureWorker announces a validatable intent at
///     dispatch time. Declares are not strictly required — they exist for
///     diagnostics and possible future timeout policy; <see cref="TryConsume"/>
///     does not depend on a prior Declare.
///   - <see cref="Confirm"/>: the relevant world entity (EdibleObject for eat,
///     CreatureWorker itself for go_to arrival, …) records a successful
///     completion. Subsequent confirms for the same (creature, action, target)
///     overwrite the previous one.
///   - <see cref="TryConsume"/>: CreatureWorker reads at completion time. A
///     confirm older than the intent's start time is treated as stale and
///     discarded. A successful consume removes the entry so the next intent
///     of the same shape starts clean.
///
/// Single-threaded. All callers run on Unity's main thread.
/// </summary>
public static class GoalEventBus
{
    readonly struct Key : IEquatable<Key>
    {
        public readonly string CreatureId;
        public readonly string Action;
        public readonly string TargetId;

        public Key(string creatureId, string action, string targetId)
        {
            CreatureId = (creatureId ?? "").Trim();
            Action     = (action     ?? "").Trim();
            TargetId   = (targetId   ?? "").Trim();
        }

        public bool Equals(Key other) =>
            string.Equals(CreatureId, other.CreatureId, StringComparison.OrdinalIgnoreCase) &&
            string.Equals(Action,     other.Action,     StringComparison.OrdinalIgnoreCase) &&
            string.Equals(TargetId,   other.TargetId,   StringComparison.OrdinalIgnoreCase);

        public override bool Equals(object obj) => obj is Key other && Equals(other);

        public override int GetHashCode() =>
            HashCode.Combine(
                CreatureId.ToLowerInvariant(),
                Action.ToLowerInvariant(),
                TargetId.ToLowerInvariant());
    }

    readonly struct Confirmation
    {
        public readonly float At;
        public readonly string Reason;

        public Confirmation(float at, string reason)
        {
            At = at;
            Reason = reason ?? "";
        }
    }

    static readonly Dictionary<Key, Confirmation> _confirmations = new Dictionary<Key, Confirmation>();
    static readonly Dictionary<Key, float> _declarations = new Dictionary<Key, float>();

    /// <summary>Cat-side: announce an intent is now in flight. Optional but recommended.</summary>
    public static void Declare(string creatureId, string action, string targetId, float startedAt)
    {
        var key = new Key(creatureId, action, targetId);
        _declarations[key] = startedAt;
    }

    /// <summary>
    /// World-side guard: true only while the worker has an active declared
    /// intent for this exact creature/action/target. Confirmation emitters use
    /// this to avoid turning ambient trigger contact into fake success.
    /// </summary>
    public static bool HasDeclaration(string creatureId, string action, string targetId)
    {
        var key = new Key(creatureId, action, targetId);
        return _declarations.ContainsKey(key);
    }

    /// <summary>World-side: record that this intent actually completed.</summary>
    public static void Confirm(string creatureId, string action, string targetId, float at, string reason)
    {
        var key = new Key(creatureId, action, targetId);
        _confirmations[key] = new Confirmation(at, reason);
    }

    /// <summary>
    /// Cat-side: at completion, take the confirmation if one exists and is not
    /// older than <paramref name="since"/> (typically the intent's start time).
    /// Returns true on hit, false on miss. Removes the entry either way so the
    /// next intent of the same shape starts clean.
    /// </summary>
    public static bool TryConsume(string creatureId, string action, string targetId, float since, out string reason)
    {
        var key = new Key(creatureId, action, targetId);
        _declarations.Remove(key);

        if (!_confirmations.TryGetValue(key, out var confirmation))
        {
            reason = "";
            return false;
        }

        _confirmations.Remove(key);

        if (confirmation.At < since)
        {
            reason = "";
            return false;
        }

        reason = confirmation.Reason;
        return true;
    }

    /// <summary>Drop everything. Intended for tests and scene reload hooks.</summary>
    public static void Reset()
    {
        _confirmations.Clear();
        _declarations.Clear();
    }
}
