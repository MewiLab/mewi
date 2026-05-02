// ISnapshotChannel.cs
//
// Contract for one semantic channel (eye perception, mood, spatial, …).
// Each channel reads one slice of state from the blackboard and writes its
// matching slot on the SnapshotPayload.
//
// SnapshotManager iterates the registered channels in order and produces
// the final JSON. Adding a new channel = implement this + register it.
//
// Channels are PLAIN C# classes — not MonoBehaviours. State they need
// (transforms, tunables) is passed in via constructor or context.

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
