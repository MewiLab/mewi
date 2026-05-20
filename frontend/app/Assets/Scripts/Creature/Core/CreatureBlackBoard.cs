using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// Shared data bus for creature state.
/// Mind-only runtime: PeriodicMind enqueues a plan, the motor worker peeks
/// the head intent each tick and pops it once the body finishes executing.
/// </summary>
public class CreatureBlackboard : MonoBehaviour
{
    [Header("Identity")]
    [SerializeField] string creatureId = "";

    [Header("Intent slots (read-only in Inspector)")]
    [SerializeField] string _debugMindSlot  = "—";
    [SerializeField] string _debugMindQueue = "—";

    IntentMessage? _mindIntent;
    readonly Queue<IntentMessage> _mindQueue = new Queue<IntentMessage>();
    readonly Queue<PlanExecutionReport> _completedPlanReports = new Queue<PlanExecutionReport>();

    public string CreatureId
    {
        get
        {
            if (string.IsNullOrWhiteSpace(creatureId))
                creatureId = gameObject.name;
            return creatureId;
        }
    }

    public IntentMessage? MindIntent  => _mindIntent?.IsActive == true ? _mindIntent : null;
    public int  QueuedMindIntentCount => _mindQueue.Count;
    public bool HasMindPlan           => MindIntent.HasValue || _mindQueue.Count > 0;

    public void SetMindIntent(
        string intent,
        Vector3 directionHint = default,
        string commandId = "",
        string requestId = "",
        string targetKey = "")
    {
        _mindQueue.Clear();
        _mindIntent = IntentMessage.Create(intent, LayerSource.Mind, -1f, directionHint, commandId, requestId, targetKey);
        LogEvent($"mind suggests: {intent}");
    }

    public void ReplaceMindPlan(IEnumerable<IntentMessage> intents)
    {
        _mindIntent = null;
        _mindQueue.Clear();

        if (intents != null)
        {
            foreach (var intent in intents)
            {
                if (string.IsNullOrWhiteSpace(intent.Intent))
                    continue;
                _mindQueue.Enqueue(intent);
            }
        }

        PromoteNextMindIntent();
        int stepCount = (MindIntent.HasValue ? 1 : 0) + _mindQueue.Count;
        LogEvent($"mind plan queued: {stepCount} step(s)");
    }

    public void ClearMindPlan()
    {
        _mindIntent = null;
        _mindQueue.Clear();
        followTarget = null;
    }

    public void ClearMindIntent()
    {
        _mindIntent = null;
        PromoteNextMindIntent();
    }

    /// <summary>
    /// Pop the current head intent and advance the queue. Returns the popped
    /// intent. False when there was nothing active to pop.
    /// </summary>
    public bool TryPopMindIntent(out IntentMessage popped)
    {
        if (_mindIntent.HasValue && _mindIntent.Value.IsActive)
        {
            popped = _mindIntent.Value;
            _mindIntent = null;
            PromoteNextMindIntent();
            return true;
        }

        popped = default;
        _mindIntent = null;
        PromoteNextMindIntent();
        return false;
    }

    public void EnqueuePlanExecutionReport(PlanExecutionReport report)
    {
        if (report == null) return;
        _completedPlanReports.Enqueue(report);
    }

    public bool TryPopPlanExecutionReport(out PlanExecutionReport report)
    {
        if (_completedPlanReports.Count > 0)
        {
            report = _completedPlanReports.Dequeue();
            return true;
        }

        report = null;
        return false;
    }

    /// <summary>
    /// Peek the current head intent without removing it. Expired heads are
    /// skipped so a stale slot cannot block the rest of the queued plan.
    /// </summary>
    public bool TryPeekMindIntent(out IntentMessage head)
    {
        if (_mindIntent.HasValue && !_mindIntent.Value.IsActive)
            _mindIntent = null;

        if (!_mindIntent.HasValue && !PromoteNextMindIntent())
        {
            head = default;
            return false;
        }

        head = _mindIntent.Value;
        return head.IsActive;
    }

    /// <summary>Peek the current head intent, or "idle" when nothing is queued.</summary>
    public IntentMessage ResolveActiveIntent()
    {
        if (_mindIntent.HasValue && _mindIntent.Value.IsActive)
            return _mindIntent.Value;

        if (_mindIntent.HasValue && !_mindIntent.Value.IsActive)
            _mindIntent = null;

        if (PromoteNextMindIntent())
            return _mindIntent.Value;

        return IntentMessage.Create("idle", LayerSource.Mind);
    }

    bool PromoteNextMindIntent()
    {
        while (_mindQueue.Count > 0)
        {
            _mindIntent = _mindQueue.Dequeue();
            if (_mindIntent.Value.IsActive)
                return true;
        }

        _mindIntent = null;
        followTarget = null;
        return false;
    }

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
    [HideInInspector] public bool      playerInSight;

    /// <summary>Resolved target currently used by the motor for follow-style movement.</summary>
    [HideInInspector] public Transform followTarget;

    /// <summary>Recent sensory events for this frame, cleared each tick.</summary>
    public List<SensoryEvent> sensorEvents = new List<SensoryEvent>();

    /// <summary>Semantic zones the cat currently stands in. Written by SmartZoneTracker.</summary>
    [HideInInspector] public HashSet<string> currentZones = new HashSet<string>();

    /// <summary>
    /// Spatial zones, outermost → innermost by collider volume. Written by ZoneScanner,
    /// read by SpatialChannel.
    /// </summary>
    [HideInInspector] public List<ZoneVolume> activeZones = new List<ZoneVolume>();

    // ─────────────────────────────────────────────
    // MOOD — written by PeriodicMind
    // ─────────────────────────────────────────────

    public MoodModel   mood   = new MoodModel();
    public HealthModel health = new HealthModel();

    // ─────────────────────────────────────────────
    // FRAME MANAGEMENT
    // ─────────────────────────────────────────────

    /// <summary>Update Inspector debug strings. Call at end of frame.</summary>
    public void UpdateDebugDisplay()
    {
        _debugMindSlot  = MindIntent.HasValue  ? MindIntent.Value.ToString()  : "—";
        _debugMindQueue = _mindQueue.Count > 0 ? $"{_mindQueue.Count} queued" : "empty";
    }

    /// <summary>Cheap simulation of hunger climb between perception ticks.</summary>
    public void ScoreDrives()
    {
        health.hunger = Mathf.Clamp01(health.hunger + Time.deltaTime * 0.05f);
    }
}
