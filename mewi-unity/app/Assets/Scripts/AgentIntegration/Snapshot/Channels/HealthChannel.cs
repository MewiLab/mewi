// HealthChannel.cs — writes body drives.

using UnityEngine;

public sealed class HealthChannel : ISnapshotChannel
{
    public string ChannelId => "health";

    public void Write(SnapshotPayload payload, CreatureBlackboard board, Transform self)
    {
        payload.health = new HealthData { fullness = board.health.fullness };
    }
}
