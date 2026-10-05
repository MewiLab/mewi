using UnityEngine;

/// <summary>
/// Emits the compact high-level intent affordance contract for the backend.
/// </summary>
public sealed class AffordancesChannel : ISnapshotChannel
{
    public string ChannelId => "affordances";

    readonly int _maxTargets;

    public AffordancesChannel(int maxTargets)
    {
        _maxTargets = Mathf.Max(0, maxTargets);
    }

    public void Write(SnapshotPayload payload, CreatureBlackboard board, Transform self)
    {
        SnapshotAffordanceBuilder.Write(payload, board, self, _maxTargets);
    }
}
