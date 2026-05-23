using System;
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

    [Header("Intent queue (read-only in Inspector)")]
    [SerializeField] string _debugMindSlot  = "—";
    [SerializeField] string _debugMindQueue = "—";

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

    public IntentMessage? MindIntent
    {
        get
        {
            return TryPeekMindIntent(out var head) ? head : (IntentMessage?)null;
        }
    }

    public int  QueuedMindIntentCount => PendingMindIntentCount();
    public bool HasMindPlan           => TryPeekMindIntent(out _);

    public void SetMindIntent(
        string intent,
        Vector3 directionHint = default,
        string commandId = "",
        string requestId = "",
        string targetKey = "")
    {
        _mindQueue.Clear();
        _mindQueue.Enqueue(IntentMessage.Create(intent, LayerSource.Mind, -1f, directionHint, commandId, requestId, targetKey));
        LogEvent($"mind suggests: {intent}");
    }

    public void ReplaceMindPlan(IEnumerable<IntentMessage> intents)
    {
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

        int stepCount = ActiveMindIntentCount();
        LogEvent($"mind plan queued: {stepCount} step(s)");
    }

    public void ClearMindPlan()
    {
        _mindQueue.Clear();
        followTarget = null;
    }

    /// <summary>
    /// Pop the current queue head. Returns the popped intent. False when there
    /// was nothing active to pop.
    /// </summary>
    public bool TryPopMindIntent(out IntentMessage popped)
    {
        TrimInactiveMindIntents();

        if (_mindQueue.Count == 0)
        {
            popped = default;
            followTarget = null;
            return false;
        }

        popped = _mindQueue.Dequeue();
        if (_mindQueue.Count == 0)
            followTarget = null;
        return true;
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
        TrimInactiveMindIntents();
        if (_mindQueue.Count == 0)
        {
            head = default;
            return false;
        }

        head = _mindQueue.Peek();
        return true;
    }

    /// <summary>Peek the current head intent, or "idle" when nothing is queued.</summary>
    public IntentMessage ResolveActiveIntent()
    {
        return TryPeekMindIntent(out var head)
            ? head
            : IntentMessage.Create("idle", LayerSource.Mind);
    }

    void TrimInactiveMindIntents()
    {
        while (_mindQueue.Count > 0 && !_mindQueue.Peek().IsActive)
            _mindQueue.Dequeue();

        if (_mindQueue.Count == 0)
            followTarget = null;
    }

    int PendingMindIntentCount()
    {
        TrimInactiveMindIntents();
        return Mathf.Max(0, _mindQueue.Count - 1);
    }

    int ActiveMindIntentCount()
    {
        TrimInactiveMindIntents();
        return _mindQueue.Count;
    }

    // ─────────────────────────────────────────────
    // EATING INVENTORY (see ADR-008)
    // ─────────────────────────────────────────────

    /// <summary>Total bites consumed across all food sources this session.</summary>
    [HideInInspector] public int totalBitesEaten;

    /// <summary>Time of the most recent bite. -1 if the cat has never eaten.</summary>
    [HideInInspector] public float lastAteAt = -1f;

    /// <summary>Most recently consumed food's id (SmartObject label or GameObject name).</summary>
    [HideInInspector] public string lastEatenFoodId = "";

    /// <summary>
    /// Called by <see cref="EdibleObject"/> when this cat takes a bite. Updates
    /// inventory counters used by perception and by future episodic memory, and
    /// raises fullness by the food's nutrition value so the next planning tick
    /// sees the cat as satisfied.
    /// </summary>
    public void RecordBite(string foodId, float t, float fullnessGain = 0.35f)
    {
        totalBitesEaten++;
        lastAteAt = t;
        lastEatenFoodId = string.IsNullOrWhiteSpace(foodId) ? "" : foodId.Trim();
        health.AddFullness(fullnessGain);
    }

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

    struct RecentTargetRecord
    {
        public Transform target;
        public Vector3 perceivedPosition;
        public bool hasPerceivedPosition;
    }

    /// <summary>Recent visible target keys mapped back to their Unity transforms and perceived positions.</summary>
    readonly Dictionary<string, RecentTargetRecord> _recentTargets =
        new Dictionary<string, RecentTargetRecord>(StringComparer.OrdinalIgnoreCase);

    /// <summary>Recent felt-world events for this frame, cleared each perception tick.</summary>
    public List<FeelingEvent> feelingEvents = new List<FeelingEvent>();

    public void RememberPerceivedTarget(string key, Transform target)
        => RememberPerceivedTarget(key, target, target != null ? target.position : Vector3.zero);

    public void RememberPerceivedTarget(string key, Transform target, Vector3 perceivedPosition)
    {
        if (string.IsNullOrWhiteSpace(key) || target == null) return;
        _recentTargets[key.Trim()] = new RecentTargetRecord
        {
            target = target,
            perceivedPosition = perceivedPosition,
            hasPerceivedPosition = true,
        };
    }

    public bool TryResolveRecentTarget(string key, out Transform target)
    {
        target = null;
        if (string.IsNullOrWhiteSpace(key)) return false;

        string normalized = key.Trim();
        if (_recentTargets.TryGetValue(normalized, out var record) && record.target != null)
        {
            target = record.target;
            return true;
        }

        if (target == null)
            _recentTargets.Remove(normalized);

        return false;
    }

    public bool TryResolveRecentTargetPosition(string key, out Vector3 position, out Transform target)
    {
        position = Vector3.zero;
        target = null;
        if (string.IsNullOrWhiteSpace(key)) return false;

        string normalized = key.Trim();
        if (!_recentTargets.TryGetValue(normalized, out var record))
            return false;

        if (record.target == null)
        {
            _recentTargets.Remove(normalized);
            return false;
        }

        target = record.target;
        position = record.hasPerceivedPosition ? record.perceivedPosition : record.target.position;
        return true;
    }

    /// <summary>
    /// Current spatial zones, outermost → innermost. Written by ZoneScanner,
    /// read by SelfChannel and SpatialChannel.
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
        int queued = QueuedMindIntentCount;
        _debugMindSlot  = TryPeekMindIntent(out var head) ? head.ToString() : "—";
        _debugMindQueue = queued > 0 ? $"{queued} queued" : "empty";
    }

}
