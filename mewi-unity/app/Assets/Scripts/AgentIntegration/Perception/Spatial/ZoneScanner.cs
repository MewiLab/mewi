// ZoneScanner.cs
//
// Current-location spatial source of truth.
//
// Authoring model:
//   ZV_Harbor                    ZoneVolume, no collider needed
//     ZV_Bamboo_Boardwalk        ZoneVolume for this named place
//       BoardwalkFootprint_A     trigger Collider on SemanticZone
//       BoardwalkFootprint_B     trigger Collider on SemanticZone
//
// The collider children do not each need ZoneVolume. Only attach ZoneVolume to
// semantic places you want in the snapshot. The scanner samples the cat's
// current position, finds trigger colliders under ZoneVolume ancestors, walks
// up the hierarchy, and writes activeZones broadest -> most specific.

using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Serialization;

public class ZoneScanner : MonoBehaviour
{
    [Tooltip("Preferred layers containing ZoneVolume trigger colliders.")]
    public LayerMask zoneLayers = ~0;

    [FormerlySerializedAs("recoveryInterval")]
    [Tooltip("How often, in seconds, to rescan the cat's current containing zones.")]
    public float scanInterval = 0.25f;

    [FormerlySerializedAs("seedRadius")]
    [Tooltip("Overlap radius around the cat pivot. Increase if the pivot is above thin ground-level zone colliders.")]
    public float sampleRadius = 1.0f;

    [FormerlySerializedAs("logTransitions")]
    [Tooltip("Log when the current zone chain changes.")]
    public bool logChanges = false;

    [Tooltip("Also scan all layers and filter by ZoneVolume. Useful when child collider layers are mixed during scene authoring.")]
    public bool scanAllLayersFallback = true;

    readonly Collider[] _buffer = new Collider[128];
    readonly HashSet<Collider> _sampledColliders = new();

    CreatureBlackboard _board;
    float _scanTimer;

    public void Init(CreatureBlackboard board)
    {
        _board = board;
        RefreshNow();
    }

    public void Tick()
    {
        if (_board == null) return;

        _scanTimer += Time.deltaTime;
        if (_scanTimer < Mathf.Max(0.02f, scanInterval)) return;
        RefreshNow();
    }

    /// <summary>
    /// Rebuild active zones immediately from the current position. Call after
    /// teleports/warps because trigger callbacks are not the source of truth.
    /// </summary>
    public void RefreshNow()
    {
        if (_board == null) return;

        _scanTimer = 0f;
        _sampledColliders.Clear();
        AddZoneCollidersAtPosition(transform.position, sampleRadius, zoneLayers, _sampledColliders);

        if (scanAllLayersFallback && zoneLayers.value != ~0)
            AddZoneCollidersAtPosition(transform.position, sampleRadius, ~0, _sampledColliders);

        var zones = BuildZoneChain(_sampledColliders);
        zones.Sort(CompareBroadToSpecific);
        WriteToBlackboard(zones);
    }

    static List<ZoneVolume> BuildZoneChain(HashSet<Collider> colliders)
    {
        var zones = new HashSet<ZoneVolume>();

        foreach (Collider col in colliders)
        {
            if (col == null) continue;

            Transform t = col.transform;
            while (t != null)
            {
                ZoneVolume zone = t.GetComponent<ZoneVolume>();
                if (zone != null)
                    zones.Add(zone);
                t = t.parent;
            }
        }

        return new List<ZoneVolume>(zones);
    }

    void WriteToBlackboard(List<ZoneVolume> zones)
    {
        if (logChanges && ZoneChainChanged(_board.activeZones, zones))
            Debug.Log($"[ZoneScanner] current zones: {FormatZoneChain(zones)}");

        _board.activeZones.Clear();
        _board.activeZones.AddRange(zones);
    }

    void AddZoneCollidersAtPosition(
        Vector3 position,
        float radius,
        LayerMask layerMask,
        HashSet<Collider> activeColliders)
    {
        int n = Physics.OverlapSphereNonAlloc(
            position,
            Mathf.Max(0.01f, radius),
            _buffer,
            layerMask,
            QueryTriggerInteraction.Collide);

        for (int i = 0; i < n; i++)
        {
            Collider col = _buffer[i];
            if (IsZoneTrigger(col))
                activeColliders.Add(col);
        }
    }

    static bool IsZoneTrigger(Collider c)
    {
        if (c == null || !c.isTrigger) return false;
        return c.GetComponentInParent<ZoneVolume>() != null;
    }

    static int CompareBroadToSpecific(ZoneVolume a, ZoneVolume b)
    {
        float av = BoundsVolume(a);
        float bv = BoundsVolume(b);
        int bySize = bv.CompareTo(av);
        if (bySize != 0) return bySize;
        return HierarchyDepth(a.transform).CompareTo(HierarchyDepth(b.transform));
    }

    static float BoundsVolume(ZoneVolume zone)
    {
        if (ZoneVolumeUtility.TryGetBounds(zone, out Bounds bounds))
            return Mathf.Max(0.0001f, bounds.size.x * bounds.size.y * bounds.size.z);
        return float.PositiveInfinity;
    }

    static int HierarchyDepth(Transform t)
    {
        int d = 0;
        while (t.parent != null)
        {
            d++;
            t = t.parent;
        }
        return d;
    }

    static bool ZoneChainChanged(List<ZoneVolume> previous, List<ZoneVolume> next)
    {
        int previousCount = previous != null ? previous.Count : 0;
        int nextCount = next != null ? next.Count : 0;
        if (previousCount != nextCount) return true;

        for (int i = 0; i < previousCount; i++)
        {
            if (previous[i] != next[i]) return true;
        }
        return false;
    }

    static string FormatZoneChain(List<ZoneVolume> zones)
    {
        if (zones == null || zones.Count == 0) return "(none)";

        var ids = new List<string>(zones.Count);
        for (int i = 0; i < zones.Count; i++)
        {
            if (zones[i] != null)
                ids.Add(zones[i].EffectiveZoneId);
        }
        return string.Join(" > ", ids);
    }
}
