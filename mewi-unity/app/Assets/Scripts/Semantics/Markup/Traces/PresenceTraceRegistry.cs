using System;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// Small runtime store for slowly decaying place traces.
/// Zones stay static; traces are dynamic marks left on those zones.
/// </summary>
public static class PresenceTraceRegistry
{
    const float MinReportIntensity = 0.08f;

    static readonly Dictionary<string, List<PresenceTrace>> _byZone =
        new Dictionary<string, List<PresenceTrace>>(StringComparer.OrdinalIgnoreCase);

    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
    static void Reset()
    {
        _byZone.Clear();
    }

    public static void Record(
        ZoneVolume zone,
        string ownerId,
        string ownerKind,
        string description,
        float strength,
        float lifetimeSeconds,
        int maxTracesPerZone)
    {
        if (zone == null || string.IsNullOrWhiteSpace(ownerId))
            return;

        string zoneId = zone.EffectiveZoneId;
        if (string.IsNullOrWhiteSpace(zoneId))
            return;

        float now = Time.time;
        if (!_byZone.TryGetValue(zoneId, out List<PresenceTrace> traces))
        {
            traces = new List<PresenceTrace>();
            _byZone[zoneId] = traces;
        }

        Prune(traces, now);

        PresenceTrace trace = FindTrace(traces, ownerId, ownerKind);
        if (trace == null)
        {
            trace = new PresenceTrace
            {
                zoneId = zoneId,
                ownerId = ownerId.Trim(),
                ownerKind = Normalize(ownerKind, "cat"),
            };
            traces.Add(trace);
        }

        trace.description = string.IsNullOrWhiteSpace(description)
            ? $"{trace.ownerKind} scent trail"
            : description.Trim();
        trace.strength = Mathf.Clamp01(Mathf.Max(trace.strength, 0f) + Mathf.Clamp01(strength));
        trace.lastUpdatedAt = now;
        trace.lifetimeSeconds = Mathf.Max(1f, lifetimeSeconds);

        CapWeakest(traces, Mathf.Max(1, maxTracesPerZone), now);
    }

    public static void AppendFeelingEvents(
        List<ZoneVolume> activeZones,
        string observerId,
        List<FeelingEvent> output,
        int maxEvents)
    {
        if (activeZones == null || output == null || maxEvents <= 0)
            return;

        float now = Time.time;
        int emitted = 0;

        for (int i = activeZones.Count - 1; i >= 0 && emitted < maxEvents; i--)
        {
            ZoneVolume zone = activeZones[i];
            if (zone == null) continue;

            string zoneId = zone.EffectiveZoneId;
            if (!_byZone.TryGetValue(zoneId, out List<PresenceTrace> traces))
                continue;

            Prune(traces, now);
            traces.Sort((a, b) => b.IntensityAt(now).CompareTo(a.IntensityAt(now)));

            for (int j = 0; j < traces.Count && emitted < maxEvents; j++)
            {
                PresenceTrace trace = traces[j];
                if (IsSameOwner(trace.ownerId, observerId))
                    continue;

                float intensity = trace.IntensityAt(now);
                if (intensity < MinReportIntensity)
                    continue;

                output.Add(FeelingEvent.Create(
                    FeelingSense.Smell,
                    ZoneVolumeUtility.CenterOrTransform(zone),
                    intensity,
                    zone.transform,
                    zoneId,
                    SnapshotDescription(trace, now),
                    SnapshotMeaning(trace, now),
                    "presence_trace",
                    false,
                    true));
                emitted++;
            }
        }
    }

    static PresenceTrace FindTrace(List<PresenceTrace> traces, string ownerId, string ownerKind)
    {
        string normalizedKind = Normalize(ownerKind, "cat");
        for (int i = 0; i < traces.Count; i++)
        {
            PresenceTrace trace = traces[i];
            if (trace == null) continue;
            if (IsSameOwner(trace.ownerId, ownerId) &&
                string.Equals(trace.ownerKind, normalizedKind, StringComparison.OrdinalIgnoreCase))
            {
                return trace;
            }
        }
        return null;
    }

    static void Prune(List<PresenceTrace> traces, float now)
    {
        for (int i = traces.Count - 1; i >= 0; i--)
        {
            PresenceTrace trace = traces[i];
            if (trace == null || trace.IsExpired(now))
                traces.RemoveAt(i);
        }
    }

    static void CapWeakest(List<PresenceTrace> traces, int maxTraces, float now)
    {
        if (traces.Count <= maxTraces)
            return;

        traces.Sort((a, b) => b.IntensityAt(now).CompareTo(a.IntensityAt(now)));
        traces.RemoveRange(maxTraces, traces.Count - maxTraces);
    }

    static string SnapshotDescription(PresenceTrace trace, float now)
    {
        string freshness = FreshnessLabel(trace, now);
        return $"{freshness} {trace.description} from {trace.ownerId}";
    }

    static string SnapshotMeaning(PresenceTrace trace, float now)
    {
        string freshness = FreshnessLabel(trace, now);
        return $"{trace.ownerId} was here {freshness}";
    }

    static string FreshnessLabel(PresenceTrace trace, float now)
    {
        float t = trace.IntensityAt(now);
        if (t >= 0.65f) return "fresh";
        if (t >= 0.3f) return "lingering";
        return "faint old";
    }

    static bool IsSameOwner(string a, string b)
    {
        return !string.IsNullOrWhiteSpace(a) &&
               !string.IsNullOrWhiteSpace(b) &&
               string.Equals(a.Trim(), b.Trim(), StringComparison.OrdinalIgnoreCase);
    }

    static string Normalize(string value, string fallback)
    {
        return string.IsNullOrWhiteSpace(value) ? fallback : value.Trim().ToLowerInvariant();
    }
}
