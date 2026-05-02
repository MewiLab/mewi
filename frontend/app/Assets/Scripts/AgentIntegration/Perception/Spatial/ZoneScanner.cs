// ZoneScanner.cs
//
// Tracks which ZoneVolumes the cat is currently inside.
//
// Tracks active COLLIDERS (not ZoneVolume components directly).
// WriteToBlackboard() derives the active zone set by walking each collider's
// ancestor chain — so a ZoneVolume with no collider of its own (a container
// like ZV_Harbor) is automatically included whenever any of its descendant
// trigger colliders are active.
//
// Sorting: hierarchy depth ascending → shallowest (broadest) zone first.
// Python reads zones[0] for broad context, zones[-1] for most-specific place.
//
// Primary mechanism: OnTriggerEnter/Exit — instant, zero per-frame cost.
// Safety net: periodic XZ bounds check in Tick() catches missed exits
//   (a known Unity edge case when colliders resize, objects teleport,
//    or the Rigidbody goes to sleep). Checks XZ only — Y is ignored so
//   the cat's elevated pivot does not falsely evict thin, ground-level volumes.

using System.Collections.Generic;
using UnityEngine;

public class ZoneScanner : MonoBehaviour
{
    [Tooltip("Layers containing ZoneVolume trigger volumes. Used only for the spawn-time seed.")]
    public LayerMask zoneLayers = ~0;

    [Tooltip("How often (seconds) to run the missed-exit recovery check.")]
    public float recoveryInterval = 0.5f;

    [Tooltip("Log zone enter/exit transitions for scene authoring verification.")]
    public bool logTransitions = false;

    [Tooltip("Radius for the spawn-time OverlapSphere seed. Must reach ground-level zone " +
             "colliders from the cat's pivot (increase if cat pivot is well above the ground).")]
    public float seedRadius = 1.0f;

    readonly HashSet<Collider> _activeColliders = new();
    readonly Collider[]        _seedBuffer      = new Collider[32];
    float _recoveryTimer;

    CreatureBlackboard _board;

    // ─── Init ────────────────────────────────────────────────────────────────

    public void Init(CreatureBlackboard board)
    {
        _board = board;
        SeedActiveZones();
        WriteToBlackboard();
    }

    // ─── Trigger events — primary source of truth ────────────────────────────

    void OnTriggerEnter(Collider other)
    {
        if (!IsZoneTrigger(other) || !_activeColliders.Add(other)) return;
        if (logTransitions)
        {
            var zv = other.GetComponentInParent<ZoneVolume>();
            Debug.Log($"[ZoneScanner] enter → {other.name} ({zv?.EffectiveZoneId})");
        }
        if (_board != null) WriteToBlackboard();
    }

    void OnTriggerExit(Collider other)
    {
        if (!_activeColliders.Remove(other)) return;
        if (logTransitions)
        {
            var zv = other.GetComponentInParent<ZoneVolume>();
            Debug.Log($"[ZoneScanner] exit  ← {other.name} ({zv?.EffectiveZoneId})");
        }
        if (_board != null) WriteToBlackboard();
    }

    // ─── Tick — periodic safety net only ─────────────────────────────────────

    public void Tick()
    {
        if (_board == null) return;

        _recoveryTimer += Time.deltaTime;
        if (_recoveryTimer < recoveryInterval) return;
        _recoveryTimer = 0f;

        RecoverMissedExits();
    }

    // ─── Internal ────────────────────────────────────────────────────────────

    // One-shot probe at spawn: OnTriggerEnter doesn't fire for zones the cat
    // starts inside. OverlapSphere is used here only once, not every frame.
    void SeedActiveZones()
    {
        int n = Physics.OverlapSphereNonAlloc(
            transform.position, seedRadius, _seedBuffer, zoneLayers, QueryTriggerInteraction.Collide);

        for (int i = 0; i < n; i++)
        {
            var col = _seedBuffer[i];
            if (IsZoneTrigger(col)) _activeColliders.Add(col);
        }
    }

    // XZ-only AABB check — no OverlapSphere, no edge oscillation.
    // Zone volumes are ground-level footprints; the cat's pivot may sit above a thin
    // collider while the cat is clearly standing on it, so Y is intentionally ignored.
    void RecoverMissedExits()
    {
        bool changed = false;
        Vector3 pos  = transform.position;

        _activeColliders.RemoveWhere(col =>
        {
            if (col == null)
            {
                changed = true;
                return true;
            }
            Bounds b = col.bounds;
            bool outsideXZ = pos.x < b.min.x || pos.x > b.max.x ||
                             pos.z < b.min.z || pos.z > b.max.z;
            if (outsideXZ)
            {
                if (logTransitions)
                    Debug.Log($"[ZoneScanner] recovery exit ← {col.name}");
                changed = true;
                return true;
            }
            return false;
        });

        if (changed) WriteToBlackboard();
    }

    // A collider counts as a zone trigger if it has a ZoneVolume anywhere in its parent chain.
    static bool IsZoneTrigger(Collider c) => c.GetComponentInParent<ZoneVolume>() != null;

    // Derive the active zone set by walking each active collider's ancestor chain.
    // Container zones (ZoneVolume with no collider of their own, like ZV_Harbor) are
    // included automatically when any descendant trigger is active.
    void WriteToBlackboard()
    {
        var zones = new HashSet<ZoneVolume>();

        foreach (var col in _activeColliders)
        {
            var t = col.transform;
            while (t != null)
            {
                var zv = t.GetComponent<ZoneVolume>();
                if (zv != null) zones.Add(zv);
                t = t.parent;
            }
        }

        var sorted = new List<ZoneVolume>(zones);
        sorted.Sort((a, b) => HierarchyDepth(a.transform).CompareTo(HierarchyDepth(b.transform)));

        _board.activeZones.Clear();
        _board.activeZones.AddRange(sorted);
    }

    static int HierarchyDepth(Transform t)
    {
        int d = 0;
        while (t.parent != null) { d++; t = t.parent; }
        return d;
    }
}
