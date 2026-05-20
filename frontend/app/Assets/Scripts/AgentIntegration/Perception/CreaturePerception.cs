using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// Sense layer — writes perception data to the blackboard at a configurable tick rate.
/// All other layers read from the blackboard, never do their own physics queries.
/// </summary>
public class CreaturePerception : MonoBehaviour
{
    CreatureBlackboard _board;
    CreatureConfig     _config;
    Transform          _self;

    [Header("Tick Rate")]
    [Tooltip("Seconds between each perception scan.")]
    public float tickInterval = 10f;
    float _elapsed;
    float _timeSinceLastTick;

    [Header("Environment Scan")]
    [Tooltip("Assign Player, Animal, Enemy, and Item layers here.")]
    public LayerMask scanLayers;
    public float     scanRadius = 1f; // Ensure this is large enough to cover sightRange
    readonly Collider[] _scanBuffer = new Collider[32];

    [Header("Semantic Scan")]
    [Tooltip("Assign the 'SemanticProp' layer (or any layer carrying SmartObject-tagged trigger colliders).")]
    public LayerMask semanticLayer;
    readonly Collider[] _semanticBuffer = new Collider[32];

    // State for approach speed estimation for MULTIPLE creatures simultaneously
    readonly Dictionary<Transform, Vector3> _prevPositions  = new Dictionary<Transform, Vector3>();
    readonly Dictionary<Transform, float>   _speedEstimates = new Dictionary<Transform, float>();

    public void Init(CreatureBlackboard board, CreatureConfig config)
    {
        _board  = board;
        _config = config;
        _self   = transform;
    }

    public void Tick()
    {
        _elapsed += Time.deltaTime;
        
        if (tickInterval > 0f && _elapsed < tickInterval) return;

        // Record exactly how much time passed for accurate speed calculation
        _timeSinceLastTick = tickInterval > 0f ? tickInterval : Time.deltaTime;
        _elapsed = 0f;

        ScanEnvironment();
        //LogSensorBatch();
    }

    // ── Unified Perception ────────────────────────────────────────────────────

    void ScanEnvironment()
    {
        _board.sensorEvents.Clear();

        int n = Physics.OverlapSphereNonAlloc(_self.position, scanRadius, _scanBuffer, scanLayers);

        Transform closestCreature = null;
        float     closestDist     = float.MaxValue;
        bool      closestInSight  = false;

        // Track who we saw this frame so we can clean up old data from the dictionary
        HashSet<Transform> seenThisFrame = new HashSet<Transform>();
        // Dedupe bone hits — a ragdoll/skinned rig exposes many colliders per root
        HashSet<Transform> emittedRoots  = new HashSet<Transform>();

        for (int i = 0; i < n; i++)
        {
            Collider col = _scanBuffer[i];
            if (col.transform == _self) continue;

            // Walk up to the meaningful root. For animals/players this lifts bone
            // colliders (Head, Spine, R Forearm…) up to the CreatureController root.
            var       cc      = col.GetComponentInParent<CreatureController>();
            Transform targetT = cc != null ? cc.transform : col.transform;
            if (targetT == _self) continue;
            if (!emittedRoots.Add(targetT)) continue;   // already reported this root this tick

            Vector3 toTarget = targetT.position - _self.position;
            float   dist     = toTarget.magnitude;

            seenThisFrame.Add(targetT);

            // 1. Emit Generic Nearby Event.
            //    Creatures: prefer their SmartObject (e.g. entity.cat.kitten) if authored,
            //    otherwise fall back to a generic "cat" category.
            //    Non-creatures on scanLayers aren't tagged as semantic props here —
            //    props come through ScanSmartObjects() on the dedicated semantic layer.
            if (cc != null)
            {
                var so = cc.GetComponentInChildren<SmartObject>();
                string label    = so != null ? so.Label            : targetT.name;
                string category = so != null ? so.SpecificCategory : "cat";

                float intensity = 1f - Mathf.Clamp01(dist / scanRadius);
                _board.sensorEvents.Add(SensoryEvent.Create(
                    SensoryEvent.SenseType.NearbyObject,
                    so != null ? so.Position : targetT.position,
                    intensity, targetT, label, category));
            }

            // 2. Creature-Specific Logic (Sight & Approach Speed)
            if (cc != null)
            {
                bool inSight = IsInSight(toTarget, dist);

                // Update Blackboard's "Closest Target" variables
                if (dist < closestDist)
                {
                    closestDist     = dist;
                    closestCreature = targetT;
                    closestInSight  = inSight;
                }

                // Update how fast this specific creature is moving towards us
                float approachSpeed = UpdateApproachSpeed(targetT, dist);

                // Sight check
                if (inSight)
                {
                    // Note: You might want to rename PlayerNearby to CreatureNearby in your Enum!
                    EmitEvent(SensoryEvent.SenseType.PlayerNearby, targetT, 1f - (dist / _config.sightRange), targetT.name);
                }

                // Fast Approach Check (e.g., someone is running at the cat)
                if (approachSpeed > _config.fastApproachSpeed && dist < _config.personalSpaceRadius * 3f)
                {
                    // Note: You might want to rename PlayerApproachFast to CreatureApproachFast
                    EmitEvent(SensoryEvent.SenseType.PlayerApproachFast, targetT, Mathf.Clamp01(approachSpeed / 6f), targetT.name);
                }
            }
        }

        // Update the blackboard with the most relevant (closest) creature found
        // Note: You might want to rename closestPlayer to closestCreature in the Blackboard script
        _board.closestPlayer     = closestCreature;
        _board.closestPlayerDist = closestCreature != null ? closestDist : Mathf.Infinity;
        _board.playerInSight     = closestInSight;

        CleanupOldPositions(seenThisFrame);

        ScanSmartObjects();
    }

    void ScanSmartObjects()
    {
        int n = Physics.OverlapSphereNonAlloc(_self.position, scanRadius, _semanticBuffer, semanticLayer);
        // Dedupe by SmartObject instance — multiple colliders can share one component.
        HashSet<SmartObject> emitted = new HashSet<SmartObject>();

        for (int i = 0; i < n; i++)
        {
            var so = _semanticBuffer[i].GetComponentInParent<SmartObject>();
            if (so == null) continue;
            if (!emitted.Add(so)) continue;

            float dist      = Vector3.Distance(_self.position, so.Position);
            float intensity = 1f - Mathf.Clamp01(dist / scanRadius);

            _board.sensorEvents.Add(SensoryEvent.Create(
                SensoryEvent.SenseType.NearbyObject,
                so.Position,
                intensity,
                so.transform,
                so.Label,
                so.SpecificCategory,
                so.tags != null ? so.tags.ToArray() : System.Array.Empty<string>()
            ));
        }
    }

    bool IsInSight(Vector3 toTarget, float dist)
        => dist <= _config.sightRange
        && Vector3.Angle(_self.forward, toTarget.normalized) <= _config.fieldOfViewDeg * 0.5f;

    float UpdateApproachSpeed(Transform target, float currentDist)
    {
        float speedEstimate = 0f;

        if (_prevPositions.TryGetValue(target, out Vector3 prevPos))
        {
            float prevDist = (prevPos - _self.position).magnitude;
            float closing  = (prevDist - currentDist) / _timeSinceLastTick; // Fixed time division
            
            float currentEstimate = _speedEstimates.GetValueOrDefault(target, 0f);
            speedEstimate = Mathf.Lerp(currentEstimate, closing, 0.3f);
            
            _speedEstimates[target] = speedEstimate;
        }

        _prevPositions[target] = target.position;
        return speedEstimate;
    }

    void CleanupOldPositions(HashSet<Transform> currentlySeen)
    {
        // Remove tracking data for creatures that have walked out of range to prevent memory leaks
        List<Transform> keysToRemove = new List<Transform>();
        foreach (var key in _prevPositions.Keys)
        {
            if (!currentlySeen.Contains(key)) keysToRemove.Add(key);
        }

        foreach (var key in keysToRemove)
        {
            _prevPositions.Remove(key);
            _speedEstimates.Remove(key);
        }
    }

    void EmitEvent(SensoryEvent.SenseType type, Transform src, float intensity, string label = null)
        => _board.sensorEvents.Add(SensoryEvent.Create(type, src.position, intensity, src, label));

    // ── External injection ────────────────────────────────────────────────────

    public void OnSoundHeard(Vector3 soundPos, float loudness)
    {
        float dist = Vector3.Distance(_self.position, soundPos);
        if (dist > _config.hearingRange) return;

        EmitEvent(SensoryEvent.SenseType.SoundHeard, null, Mathf.Clamp01(loudness * (1f - dist / _config.hearingRange)), "Sound");
    }

    // ── Debug ────────────────────────────────────────────────────
    
    void LogSensorBatch()
    {
        if (_board.sensorEvents.Count == 0) return;

        string report = string.Join("\n", _board.sensorEvents);
        Debug.Log($"<color=cyan>Perception Tick Report ({_board.sensorEvents.Count} events):</color>\n" + report);
        
        // _board.sensorEvents.Clear(); 
    }
}