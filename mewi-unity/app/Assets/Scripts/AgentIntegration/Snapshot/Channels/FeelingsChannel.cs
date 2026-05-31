/// </summary>
// Cat-perspective felt-world channel: smell, sound, contact texture,
// temperature, moisture, vibration, taste, comfort, and danger.
// Reads CreatureBlackboard.feelingEvents and writes compact strings for the LLM.
/// </summary>
using System.Collections.Generic;
using UnityEngine;

public sealed class FeelingsChannel : ISnapshotChannel
{
    public string ChannelId => "feelings";

    readonly int _maxSmells;
    readonly int _maxSounds;
    readonly int _maxSignals;

    public FeelingsChannel(int maxSmells, int maxSounds, int maxSignals)
    {
        _maxSmells  = Mathf.Max(0, maxSmells);
        _maxSounds  = Mathf.Max(0, maxSounds);
        _maxSignals = Mathf.Max(0, maxSignals);
    }

    public void Write(SnapshotPayload payload, CreatureBlackboard board, Transform self)
    {
        var sorted = board != null && board.feelingEvents != null
            ? new List<FeelingEvent>(board.feelingEvents)
            : new List<FeelingEvent>();
        sorted.Sort(FeelingEvent.ComparePriority);

        var smells  = new List<string>(_maxSmells);
        var sounds  = new List<string>(_maxSounds);
        var signals = new List<string>(_maxSignals);

        for (int i = 0; i < sorted.Count; i++)
        {
            FeelingEvent evt = sorted[i];
            if (string.IsNullOrWhiteSpace(evt.description)) continue;

            string text = evt.ToSnapshotString(self);
            switch (evt.sense)
            {
                case FeelingSense.Smell:
                    if (smells.Count < _maxSmells) smells.Add(text);
                    break;

                case FeelingSense.Sound:
                    if (sounds.Count < _maxSounds) sounds.Add(text);
                    break;

                default:
                    if (signals.Count < _maxSignals) signals.Add(text);
                    break;
            }
        }

        payload.feelings = new FeelingsData
        {
            summary = BuildSummary(sorted),
            smells  = smells.ToArray(),
            sounds  = sounds.ToArray(),
            signals = signals.ToArray(),
        };
    }

    static string BuildSummary(List<FeelingEvent> sorted)
    {
        if (sorted == null || sorted.Count == 0) return "";

        var fragments = new List<string>(3);
        for (int i = 0; i < sorted.Count && fragments.Count < 3; i++)
        {
            FeelingEvent evt = sorted[i];
            if (!evt.includeInSummary) continue;

            string fragment = evt.ToSummaryFragment();
            if (!string.IsNullOrWhiteSpace(fragment))
                fragments.Add(fragment);
        }

        return fragments.Count == 0 ? "" : string.Join("; ", fragments);
    }
}
