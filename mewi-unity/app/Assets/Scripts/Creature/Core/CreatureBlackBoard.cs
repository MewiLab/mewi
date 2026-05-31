using System;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// Per-creature runtime state buffer
/// Holds Unity-local queues, sensory state, and short-lived lookup caches.
/// Durable memory belongs to the backend.
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

    /// <summary>Latest behavior weights read by CatBehaviorFSM.</summary>
    public CatBehaviorWeights MindWeights { get; private set; } = new CatBehaviorWeights();

    /// <summary>Optional target key the FSM should bias toward.</summary>
    public string MindFocusTarget { get; private set; } = "";

    /// <summary>True when empty-queue decisions come from the behavior FSM.</summary>
    public bool DirectiveModeEnabled { get; private set; }

    // -------------------------------------------------------------------------
    // Perception State
    // -------------------------------------------------------------------------

    [HideInInspector] public Transform closestPlayer;
    [HideInInspector] public float     closestPlayerDist = Mathf.Infinity;
    [HideInInspector] public bool      playerInSight;

    /// <summary>Motor target currently used for follow-style movement.</summary>
    [HideInInspector] public Transform followTarget;

    /// <summary>Frame-local sensory events written by perception.</summary>
    public List<SensoryEvent> sensorEvents = new List<SensoryEvent>();

    /// <summary>Frame-local feeling events written by feeling relays.</summary>
    public List<FeelingEvent> feelingEvents = new List<FeelingEvent>();

    /// <summary>Current spatial zones, ordered outermost to innermost.</summary>
    [HideInInspector] public List<ZoneVolume> activeZones = new List<ZoneVolume>();

    // -------------------------------------------------------------------------
    // Vitals
    // -------------------------------------------------------------------------

    public MoodModel   mood   = new MoodModel();
    public HealthModel health = new HealthModel();

    // -------------------------------------------------------------------------
    // Identity
    // -------------------------------------------------------------------------

    public string CreatureId
    {
        get
        {
            if (string.IsNullOrWhiteSpace(creatureId))
                creatureId = gameObject.name;
            return creatureId;
        }
    }

    // -------------------------------------------------------------------------
    // Mind Action Queue
    // -------------------------------------------------------------------------

    public IntentMessage? MindIntent
    {
        get
        {
            return TryPeekMindIntent(out var head) ? head : (IntentMessage?)null;
        }
    }

    public int  QueuedMindIntentCount => PendingMindIntentCount();
    public bool HasMindPlan           => TryPeekMindIntent(out _);

    /// <summary>Replace the queue with one explicit action.</summary>
    public void SetMindIntent(
        string intent,
        Vector3 directionHint = default,
        string commandId = "",
        string requestId = "",
        string targetKey = "")
    {
        _mindQueue.Clear();
        _mindQueue.Enqueue(IntentMessage.Create(intent, LayerSource.Mind, -1f, directionHint, commandId, requestId, targetKey));
    }

    /// <summary>Replace all queued mind actions with a backend-authored plan.</summary>
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
    }

    /// <summary>Insert local follow-up actions immediately after the active action.</summary>
    public void InsertMindIntentsAfterCurrent(IEnumerable<IntentMessage> intents)
    {
        if (intents == null)
            return;

        var pending = new List<IntentMessage>();
        foreach (var intent in intents)
        {
            if (string.IsNullOrWhiteSpace(intent.Intent))
                continue;
            pending.Add(intent);
        }

        if (pending.Count == 0)
            return;

        IntentMessage[] existing = _mindQueue.ToArray();
        _mindQueue.Clear();

        if (existing.Length == 0)
        {
            for (int i = 0; i < pending.Count; i++)
                _mindQueue.Enqueue(pending[i]);
            return;
        }

        _mindQueue.Enqueue(existing[0]);
        for (int i = 0; i < pending.Count; i++)
            _mindQueue.Enqueue(pending[i]);
        for (int i = 1; i < existing.Length; i++)
            _mindQueue.Enqueue(existing[i]);
    }

    public void ClearMindPlan()
    {
        _mindQueue.Clear();
        followTarget = null;
    }

    /// <summary>Peek the active action without removing it.</summary>
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

    /// <summary>Peek the active action, or return idle when the queue is empty.</summary>
    public IntentMessage ResolveActiveIntent()
    {
        return TryPeekMindIntent(out var head)
            ? head
            : IntentMessage.Create("idle", LayerSource.Mind);
    }

    /// <summary>Remove and return the active action.</summary>
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

    /// <summary>Append one FSM-generated micro-action to the action queue.</summary>
    public void EnqueueMindMicroAction(IntentMessage intent)
    {
        if (string.IsNullOrWhiteSpace(intent.Intent))
            return;
        _mindQueue.Enqueue(intent);
    }

    // -------------------------------------------------------------------------
    // FSM Controls
    // -------------------------------------------------------------------------

    /// <summary>Switch empty-queue behavior to CatBehaviorFSM for this play session.</summary>
    public void EnableDirectiveMode() => DirectiveModeEnabled = true;

    /// <summary>Replace behavior weights and optional focus target for CatBehaviorFSM.</summary>
    public void SetMindWeights(CatBehaviorWeights weights, string focusTarget = "")
    {
        if (weights != null)
            MindWeights = weights;
        MindFocusTarget = focusTarget ?? "";
    }

    // -------------------------------------------------------------------------
    // Report Queue
    // -------------------------------------------------------------------------

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

    // -------------------------------------------------------------------------
    // Gameplay Updates
    // -------------------------------------------------------------------------

    /// <summary>Called when this creature takes a bite.</summary>
    public void RecordBite(float fullnessGain = 0.35f)
    {
        health.AddFullness(fullnessGain);
    }

    /// <summary>Refresh Inspector-only queue labels.</summary>
    public void UpdateDebugDisplay()
    {
        int queued = QueuedMindIntentCount;
        _debugMindSlot  = TryPeekMindIntent(out var head) ? head.ToString() : "—";
        _debugMindQueue = queued > 0 ? $"{queued} queued" : "empty";
    }

    // -------------------------------------------------------------------------
    // Queue Helpers
    // -------------------------------------------------------------------------

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

    // -------------------------------------------------------------------------
    // Recent Target Cache
    // -------------------------------------------------------------------------

    struct RecentTargetRecord
    {
        public Transform target;
        public Vector3 perceivedPosition;
        public bool hasPerceivedPosition;
    }

    /// <summary>Maps target keys from snapshots/plans to live Unity objects.</summary>
    readonly Dictionary<string, RecentTargetRecord> _recentTargets =
        new Dictionary<string, RecentTargetRecord>(StringComparer.OrdinalIgnoreCase);

    /// <summary>Remember a perceived target and its current position.</summary>
    public void RememberPerceivedTarget(string key, Transform target)
        => RememberPerceivedTarget(key, target, target != null ? target.position : Vector3.zero);

    /// <summary>Remember a perceived target and the position reported to the backend.</summary>
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

    /// <summary>Resolve a recent target key to a live Transform.</summary>
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

        _recentTargets.Remove(normalized);
        return false;
    }

    /// <summary>Resolve a recent target key to its last perceived position.</summary>
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
}
