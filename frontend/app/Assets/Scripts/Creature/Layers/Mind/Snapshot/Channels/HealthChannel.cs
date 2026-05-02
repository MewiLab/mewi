// HealthChannel.cs — writes drives like hunger.

using UnityEngine;

public sealed class HealthChannel : ISnapshotChannel
{
    public string ChannelId => "health";

    public void Write(SnapshotPayload payload, CreatureBlackboard board, Transform self)
    {
        payload.health = new HealthData { hunger = board.health.hunger };
    }
}
