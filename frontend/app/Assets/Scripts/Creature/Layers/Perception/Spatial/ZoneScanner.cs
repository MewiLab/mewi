// ZoneScanner.cs
//
// Tracks which ZoneVolumes the cat is currently inside, and writes the
// computed hierarchy back to the blackboard.
//
// Eye perception (CreaturePerception) answers "what's near me?".
// This answers "where am I?" — at every level (District > Area > Surface).
//
// Implementation:
//   - Trigger-driven (cheap): OnTriggerEnter/Exit add/remove ZoneVolumes
//     from a HashSet. No per-frame overlap query.
//   - At Init time: a one-shot OverlapSphere seeds the set so the cat
//     correctly knows it's "in Harbor" even on a fresh spawn.
//   - On every Tick(): writes a sorted hierarchy into the blackboard.
//
// Sort order:
//     ZoneLayer (District → Area → Surface)
//     then collider bounds size descending (largest first).
//
// Innermost confinement and surface_material are taken from the smallest
// (last) zone, falling back up the chain when a zone leaves them empty.

using System.Collections.Generic;
using UnityEngine;

public class ZoneScanner : MonoBehaviour
{
    [Tooltip("Layers containing ZoneVolume trigger volumes. Used only for the initial seed.")]
    public LayerMask zoneLayers = ~0;

    [Tooltip("Log zone enter/exit events. Useful for verifying the scene authoring.")]
    public bool logTransitions = false;

    readonly HashSet<ZoneVolume> _active   = new HashSet<ZoneVolume>();
    readonly Collider[]          _seedBuffer = new Collider[16];

    CreatureBlackboard _board;

    public void Init(CreatureBlackboard board)
    {
        _board = board;
        SeedActiveZones();
        WriteToBlackboard();
    }

    void OnTriggerEnter(Collider other)
    {
        var zv = other.GetComponentInParent<ZoneVolume>();
        if (zv == null) return;
        if (_active.Add(zv) && logTransitions)
            Debug.Log($"[ZoneScanner] entered {zv.EffectiveZoneId} ({zv.layer})");
    }

    void OnTriggerExit(Collider other)
    {
        var zv = other.GetComponentInParent<ZoneVolume>();
        if (zv == null) return;
        if (_active.Remove(zv) && logTransitions)
            Debug.Log($"[ZoneScanner] exited {zv.EffectiveZoneId} ({zv.layer})");
    }

    /// <summary>
    /// Re-publish the hierarchy to the blackboard. Called once per Tick from
    /// CreatureController so SpatialChannel always sees a fresh snapshot.
    /// </summary>
    public void Tick()
    {
        if (_board == null) return;
        WriteToBlackboard();
    }

    // OnTriggerEnter only fires on transitions — if the cat starts INSIDE
    // a zone (common at spawn) we'd never learn about it. Probe at Init.
    void SeedActiveZones()
    {
        int n = Physics.OverlapSphereNonAlloc(
            transform.position, 0.05f, _seedBuffer, zoneLayers, QueryTriggerInteraction.Collide);

        for (int i = 0; i < n; i++)
        {
            var zv = _seedBuffer[i].GetComponentInParent<ZoneVolume>();
            if (zv != null) _active.Add(zv);
        }
    }

    void WriteToBlackboard()
    {
        // Drop any zones whose colliders were destroyed.
        _active.RemoveWhere(zv => zv == null);

        // Sort: ZoneLayer ascending (District first), then volume descending.
        var sorted = new List<ZoneVolume>(_active);
        sorted.Sort(CompareZones);

        var hierarchy = _board.locationHierarchy;
        hierarchy.Clear();
        for (int i = 0; i < sorted.Count; i++)
            hierarchy.Add(sorted[i].EffectiveZoneId);

        // Innermost wins for confinement + surface; fall back up the chain.
        ConfinementLevel confinement = ConfinementLevel.Open;
        string surface = "";
        for (int i = sorted.Count - 1; i >= 0; i--)
        {
            // First non-default we hit, walking innermost → outermost.
            if (i == sorted.Count - 1) confinement = sorted[i].confinement;
            if (string.IsNullOrEmpty(surface) && !string.IsNullOrEmpty(sorted[i].surfaceMaterial))
                surface = sorted[i].surfaceMaterial;
        }

        _board.confinement     = confinement;
        _board.surfaceMaterial = surface;
    }

    static int CompareZones(ZoneVolume a, ZoneVolume b)
    {
        int byLayer = a.layer.CompareTo(b.layer);
        if (byLayer != 0) return byLayer;

        // Same layer → bigger volume first (District encompasses everything).
        Vector3 sa = a.Collider != null ? a.Collider.bounds.size : Vector3.zero;
        Vector3 sb = b.Collider != null ? b.Collider.bounds.size : Vector3.zero;
        return sb.sqrMagnitude.CompareTo(sa.sqrMagnitude);
    }
}
