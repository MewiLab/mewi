using UnityEngine;

public sealed class MoodChannel : ISnapshotChannel
{
    public string ChannelId => "mood";

    public void Write(SnapshotPayload payload, CreatureBlackboard board, Transform self)
    {
        MoodModel m = board.mood;
        payload.mood = new MoodData
        {
            fear      = m.fear,
            trust     = m.trust,
            curiosity = m.curiosity,
            social    = m.social,
            energy    = m.energy,
        };
    }
}
