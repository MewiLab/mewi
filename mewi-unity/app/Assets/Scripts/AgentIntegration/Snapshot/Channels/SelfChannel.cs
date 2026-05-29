// SelfChannel.cs
//
// Writes "where I am" + "what I'm currently doing" — the basic self-context.
// ZoneScanner's activeZones is the current spatial source of truth.

using UnityEngine;

public sealed class SelfChannel : ISnapshotChannel
{
    public string ChannelId => "self";

    public void Write(SnapshotPayload payload, CreatureBlackboard board, Transform self)
    {
        payload.self = new SelfData
        {
            location       = ResolveLocation(board),
            current_action = board.ResolveActiveIntent().Intent,
        };
    }

    static string ResolveLocation(CreatureBlackboard board)
    {
        if (board != null && board.activeZones != null && board.activeZones.Count > 0)
        {
            ZoneVolume mostSpecific = board.activeZones[board.activeZones.Count - 1];
            return mostSpecific != null ? mostSpecific.EffectiveZoneId : "";
        }

        return "";
    }
}
