// SelfChannel.cs
//
// Writes "where I am" + "what I'm currently doing" — the basic self-context.
// Prefer ZoneScanner's activeZones, because it is the current spatial source
// of truth. currentZones is kept only as a legacy SmartZoneTracker fallback.

using System.Collections.Generic;
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

        return board != null ? JoinZones(board.currentZones) : "";
    }

    static string JoinZones(HashSet<string> zones)
    {
        if (zones == null || zones.Count == 0) return "";
        return string.Join(",", zones);
    }
}
