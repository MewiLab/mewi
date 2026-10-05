using UnityEngine;

public interface ISnapshotChannel
{
    /// <summary>
    /// Stable identifier — used for logging and (eventually) for selectively
    /// disabling individual channels at runtime.
    /// </summary>
    string ChannelId { get; }

    /// <summary>
    /// Populate the channel's slot on the payload. Implementations should
    /// not mutate the blackboard or trigger side effects.
    /// </summary>
    void Write(SnapshotPayload payload, CreatureBlackboard board, Transform self);
}
