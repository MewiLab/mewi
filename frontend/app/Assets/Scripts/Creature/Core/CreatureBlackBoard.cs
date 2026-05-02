using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// Shared data bus using Brooks' Subsumption Architecture. 
/// Layers read/write to typed Intent slots in a fixed priority: Reflex (highest) -> Tactical -> Mind (lowest).
/// </summary>
public class CreatureBlackboard : MonoBehaviour
{


    [Header("Intent slots (read-only in Inspector)")]
    [SerializeField] string _debugReflexSlot   = "—";
    [SerializeField] string _debugTacticalSlot  = "—";
    [SerializeField] string _debugMindSlot      = "—";
    [SerializeField] string _debugResolved      = "—";

    IntentMessage? _reflexIntent;
    IntentMessage? _tacticalIntent;
    IntentMessage? _mindIntent;

    public IntentMessage? ReflexIntent  => _reflexIntent?.IsActive == true ? _reflexIntent : null;
    public IntentMessage? TacticalIntent => _tacticalIntent?.IsActive == true ? _tacticalIntent : null;
    public IntentMessage? MindIntent  => _mindIntent?.IsActive == true ? _mindIntent : null;

    public void SetReflexIntent(string intent, float duration, Vector3 directionHint = default)
    {
        _reflexIntent = IntentMessage.Create(intent, LayerSource.Reflex, duration, directionHint);
        LogEvent($"reflex: {intent} ({duration:F1}s)");
    }

    public void SetTacticalCurrent(string intent, Vector3 directionHint = default)
    {
        _tacticalIntent = IntentMessage.Create(intent, LayerSource.Tactical, -1f, directionHint);
    }

    public void SetMindIntent(string intent, Vector3 directionHint = default)
    {
        _mindIntent = IntentMessage.Create(intent, LayerSource.Mind, -1f, directionHint);
        LogEvent($"mind suggests: {intent}");
    }

    public void ClearReflexIntent()
    {
        _reflexIntent = null;
    }

    public void ClearTacticalIntent()
    {
        _tacticalIntent = null;
    }

    public void ClearMindIntent()
    {
        _mindIntent = null;
    }

    public IntentMessage ResolveActiveIntent()
    {
        // Check reflex — auto-expires based on duration
        if (_reflexIntent.HasValue && _reflexIntent.Value.IsActive)
            return _reflexIntent.Value;

        // Reflex expired? Clear it so we don't re-check a stale struct
        if (_reflexIntent.HasValue && !_reflexIntent.Value.IsActive)
            _reflexIntent = null;

        // Check tactical — indefinite duration, always active until replaced
        if (_tacticalIntent.HasValue && _tacticalIntent.Value.IsActive)
            return _tacticalIntent.Value;

        // Check mind — shouldn't normally reach here (tactical should always have something)
        if (_mindIntent.HasValue && _mindIntent.Value.IsActive)
            return _mindIntent.Value;

        // Fallback: nothing is set yet (first frame, or everything cleared)
        return IntentMessage.Create("idle", LayerSource.Tactical);
    }

    /// <summary>
    /// Is a reflex currently overriding tactical? Convenience check for layers
    /// that need to know if they're being suppressed.
    /// </summary>
    /// <summary>
    /// Is a reflex currently overriding tactical? Convenience check for layers
    /// that need to know if they're being suppressed.
    /// </summary>
    public bool IsReflexActive => _reflexIntent.HasValue && _reflexIntent.Value.IsActive;


    // ─────────────────────────────────────────────
    // LEGACY COMPAT — kept during migration, will remove
    // ─────────────────────────────────────────────

    public void SetCurrentHunger(float h) => health.hunger = h;
    public float GetCurrentHunger() => health.hunger;


    // ─────────────────────────────────────────────
    // EVENT LOG
    // ─────────────────────────────────────────────

    public Queue<string> recent_events = new Queue<string>();

    public void LogEvent(string e)
    {
        recent_events.Enqueue(e);
        if (recent_events.Count > 10) recent_events.Dequeue();
    }

    public string GetRecentEventsSummary()
    {
        if (recent_events.Count == 0) return "nothing notable";
        return string.Join("; ", recent_events);
    }


    // ─────────────────────────────────────────────
    // PERCEPTION — written by CreaturePerception
    // ─────────────────────────────────────────────

    [HideInInspector] public Transform closestPlayer;
    [HideInInspector] public float     closestPlayerDist = Mathf.Infinity;

    /// <summary>Named target for the "follow" mind intent. Set by AgentMindBridge.</summary>
    [HideInInspector] public Transform followTarget;
    [HideInInspector] public Vector3   lastHeardSoundDir;
    [HideInInspector] public float     lastHeardSoundTime = -999f;
    [HideInInspector] public bool      playerInSight;
    [HideInInspector] public bool      playerApproachingFast;

    /// <summary>Recent sensory events for this frame, cleared each tick.</summary>
    public List<SensoryEvent> sensorEvents = new List<SensoryEvent>();

    /// <summary>Semantic zones the cat currently stands in. Written by SmartZoneTracker.</summary>
    [HideInInspector] public HashSet<string> currentZones = new HashSet<string>();

    // ─────────────────────────────────────────────
    // SPATIAL CONTEXT — written by ZoneScanner
    //   Sorted outermost → innermost by collider volume.
    //   SpatialChannel reads this to build the zones[] wire array.
    //   Each ZoneVolume carries its own id, type, confinement, surface.
    // ─────────────────────────────────────────────

    [HideInInspector] public List<ZoneVolume> activeZones = new List<ZoneVolume>();


    // ─────────────────────────────────────────────
    // REFLEX — gaze override (not an intent, a parallel channel)
    // ─────────────────────────────────────────────

    [HideInInspector] public bool    isStartled;
    [HideInInspector] public float   startleEndTime;
    [HideInInspector] public Vector3 gazeOverrideTarget;
    [HideInInspector] public bool    hasGazeOverride;


    // ─────────────────────────────────────────────
    // MOOD — written by PeriodicMind
    // ─────────────────────────────────────────────

    public MoodModel   mood   = new MoodModel();
    public HealthModel health = new HealthModel();


    // ─────────────────────────────────────────────
    // FRAME MANAGEMENT
    // ─────────────────────────────────────────────

    /// <summary>
    /// Reset per-frame transient data. Called at start of each tick.
    /// NOTE: Intent slots are NOT cleared here — they persist across frames.
    /// Only per-frame sensor data is cleared.
    /// </summary>
    public void ClearFrameFlags()
    {
        //sensorEvents.Clear(); this will have bug move to perception layer for its own maintain
        hasGazeOverride       = false;
        playerApproachingFast = false;
    }

    /// <summary>Update Inspector debug strings. Call at end of frame.</summary>
    public void UpdateDebugDisplay()
    {
        _debugReflexSlot  = ReflexIntent.HasValue  ? ReflexIntent.Value.ToString()  : "—";
        _debugTacticalSlot = TacticalIntent.HasValue ? TacticalIntent.Value.ToString() : "—";
        _debugMindSlot    = MindIntent.HasValue  ? MindIntent.Value.ToString()  : "—";

        var resolved = ResolveActiveIntent();
        _debugResolved = resolved.ToString();
    }


    // simulate
    public void ScoreDrives()
    // Just a cheap simulation of the external perception between agent and virtual world
    {
        health.hunger = Mathf.Clamp01(health.hunger + Time.deltaTime * 0.05f);
    }


    public int pendingActionId;
}