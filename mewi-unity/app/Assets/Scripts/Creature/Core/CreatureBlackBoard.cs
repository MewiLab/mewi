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
    /// <summary>Backend-authored high-level intent. Graph workers consume these.</summary>
    [Serializable]
    public struct MindDirective
    {
        public string RequestId;
        public string CorrelationId;
        public string Intent;
        public string FocusTarget;
        public string Mood;
        public string Style;
        public string Reason;
        public SocialAct SocialAct;

        public bool IsValid => !string.IsNullOrWhiteSpace(Intent);

        public static MindDirective Create(
            string intent,
            string focusTarget = "",
            string reason = "",
            string mood = "",
            string style = "",
            SocialAct socialAct = default,
            string requestId = "",
            string correlationId = "")
        {
            return new MindDirective
            {
                RequestId = requestId ?? "",
                CorrelationId = correlationId ?? "",
                Intent = string.IsNullOrWhiteSpace(intent) ? "" : intent.Trim().ToUpperInvariant(),
                FocusTarget = focusTarget ?? "",
                Mood = mood ?? "",
                Style = style ?? "",
                Reason = reason ?? "",
                SocialAct = socialAct,
            };
        }
    }

    [Header("Identity")]
    [SerializeField] string creatureId = "";

    [Header("Intent queues (read-only in Inspector)")]
    [SerializeField] string _debugIntentQueue = "—";
    [SerializeField] string _debugMicroActionSlot  = "—";
    [SerializeField] string _debugMicroActionQueue = "—";

    // High Level Intent from LLM: SOCIALIZE,...
    readonly Queue<MindDirective> _intentQueue = new Queue<MindDirective>();
    // Interrupt Queue with user action
    readonly Queue<SocialStimulus> _socialStimulusQueue = new Queue<SocialStimulus>();
    // Actual action with malber Animal Controll via adapter pattern design
    readonly Queue<IntentMessage> _microActionQueue = new Queue<IntentMessage>();
    // The micro action report for llm workflow not session final report
    readonly Queue<PlanExecutionReport> _completedPlanReports = new Queue<PlanExecutionReport>();

    /// <summary>Latest behavior weights read by CatBehaviorGraph (scoring fallback).</summary>
    public CatBehaviorWeights MindWeights { get; private set; } = new CatBehaviorWeights();

    /// <summary>Graph worker's active high-level intent (e.g. "SOCIALIZE", "EXPLORE").
    /// CatBehaviorGraph maps this to a behavior node; empty falls back to scoring.</summary>
    public string MindDirectiveIntent { get; private set; } = "";

    /// <summary>Target id the active directive points at; the graph biases actions toward it.</summary>
    public string MindFocusTarget { get; private set; } = "";
    public string MindDirectiveRequestId { get; private set; } = "";
    public string MindDirectiveCorrelationId { get; private set; } = "";
    public string MindDirectiveMood { get; private set; } = "";
    public string MindDirectiveStyle { get; private set; } = "";
    public string MindDirectiveReason { get; private set; } = "";
    public SocialAct MindDirectiveSocialAct { get; private set; }
    public MindDirective ActiveMindDirective { get; private set; }

    /// <summary>
    /// Raised whenever this creature produces a social line to "say" (a bubble
    /// hint). UI such as CatNameplateUI listens to render a speech bubble.
    /// The string is the spoken text; tone carries an optional style hint.
    /// </summary>
    public event Action<string, string> SocialLineSpoken;

    /// <summary>Manually surface a spoken line (e.g. from gameplay scripts).</summary>
    public void SpeakSocialLine(string say, string tone = "")
    {
        if (string.IsNullOrWhiteSpace(say))
            return;
        SocialLineSpoken?.Invoke(say.Trim(), tone ?? "");
    }

    /// <summary>True when the intent worker may refill the micro-action queue.</summary>
    public bool IntentWorkerEnabled { get; private set; }

    public bool HasActiveMindDirective => !string.IsNullOrWhiteSpace(MindDirectiveIntent);
    public string LastMicroActionIntent { get; private set; } = "";
    public string LastMicroActionTarget { get; private set; } = "";
    public string LastMicroActionStatus { get; private set; } = "";
    public string LastMicroActionReason { get; private set; } = "";
    public bool LastMicroActionFailed =>
        string.Equals(LastMicroActionStatus, "failed", StringComparison.OrdinalIgnoreCase) ||
        string.Equals(LastMicroActionStatus, "rejected", StringComparison.OrdinalIgnoreCase);

    /// <summary>Compatibility alias for older call sites and docs.</summary>
    public bool DirectiveModeEnabled => IntentWorkerEnabled;

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
                creatureId = NormalizeCreatureId(gameObject.name);
            return NormalizeCreatureId(creatureId);
        }
    }

    public void SetCreatureId(string id)
    {
        if (string.IsNullOrWhiteSpace(id))
            return;

        creatureId = NormalizeCreatureId(id);
    }

    static string NormalizeCreatureId(string value)
    {
        if (string.IsNullOrWhiteSpace(value))
            return "";

        string trimmed = value.Trim();
        return !string.Equals(trimmed, "player_cat", StringComparison.OrdinalIgnoreCase)
            && trimmed.EndsWith("_cat", StringComparison.OrdinalIgnoreCase)
            ? trimmed.Substring(0, trimmed.Length - 4)
            : trimmed;
    }

    // -------------------------------------------------------------------------
    // High-Level Intent Queue
    // -------------------------------------------------------------------------

    public int QueuedIntentCount => _intentQueue.Count;
    public bool HasPendingDirective => _intentQueue.Count > 0;

    /// <summary>Append one backend-authored high-level intent for the intent worker.</summary>
    public void EnqueueMindDirective(string intent, string focusTarget = "", string reason = "")
        => EnqueueMindDirective(MindDirective.Create(intent, focusTarget, reason));

    public void EnqueueMindDirective(MindDirective directive)
    {
        if (!directive.IsValid)
            return;
        _intentQueue.Enqueue(directive);
    }

    public bool TryPopMindDirective(out MindDirective directive)
    {
        if (_intentQueue.Count == 0)
        {
            directive = default;
            return false;
        }

        directive = _intentQueue.Dequeue();
        return true;
    }

    public void ClearMindDirectives() => _intentQueue.Clear();

    // -------------------------------------------------------------------------
    // Local Social Stimulus Queue
    // -------------------------------------------------------------------------

    public int QueuedSocialStimulusCount => _socialStimulusQueue.Count;
    public bool HasSocialStimulus => _socialStimulusQueue.Count > 0;

    public void EnqueueSocialStimulus(SocialStimulus stimulus)
    {
        if (!stimulus.IsValid)
            return;

        CoalesceSocialStimulus(stimulus);
        _socialStimulusQueue.Enqueue(stimulus);
    }

    public bool TryPeekSocialStimulus(out SocialStimulus stimulus)
    {
        if (_socialStimulusQueue.Count == 0)
        {
            stimulus = default;
            return false;
        }

        stimulus = _socialStimulusQueue.Peek();
        return true;
    }

    public bool TryPopSocialStimulus(out SocialStimulus stimulus)
    {
        if (_socialStimulusQueue.Count == 0)
        {
            stimulus = default;
            return false;
        }

        stimulus = _socialStimulusQueue.Dequeue();
        return true;
    }

    public void ClearSocialStimuli()
    {
        _socialStimulusQueue.Clear();
    }

    // -------------------------------------------------------------------------
    // Micro-Action Queue
    // -------------------------------------------------------------------------

    public IntentMessage? MicroAction
    {
        get
        {
            return TryPeekMicroAction(out var head) ? head : (IntentMessage?)null;
        }
    }

    public int  QueuedMicroActionCount => PendingMicroActionCount();
    public bool HasMicroActionPlan     => TryPeekMicroAction(out _);

    /// <summary>Replace the micro-action queue with one explicit body action.</summary>
    public void SetMicroAction(
        string intent,
        Vector3 directionHint = default,
        string commandId = "",
        string requestId = "",
        string targetKey = "",
        string correlationId = "")
    {
        _microActionQueue.Clear();
        _microActionQueue.Enqueue(IntentMessage.Create(intent, LayerSource.Mind, -1f, directionHint, commandId, requestId, targetKey, correlationId));
    }

    /// <summary>Replace all queued micro-actions with a backend-authored legacy plan.</summary>
    public void ReplaceMicroActionPlan(IEnumerable<IntentMessage> intents)
    {
        _microActionQueue.Clear();

        if (intents != null)
        {
            foreach (var intent in intents)
            {
                if (string.IsNullOrWhiteSpace(intent.Intent))
                    continue;
                _microActionQueue.Enqueue(intent);
            }
        }
    }

    /// <summary>Insert local follow-up actions immediately after the active action.</summary>
    public void InsertMicroActionsAfterCurrent(IEnumerable<IntentMessage> intents)
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

        IntentMessage[] existing = _microActionQueue.ToArray();
        _microActionQueue.Clear();

        if (existing.Length == 0)
        {
            for (int i = 0; i < pending.Count; i++)
                _microActionQueue.Enqueue(pending[i]);
            return;
        }

        _microActionQueue.Enqueue(existing[0]);
        for (int i = 0; i < pending.Count; i++)
            _microActionQueue.Enqueue(pending[i]);
        for (int i = 1; i < existing.Length; i++)
            _microActionQueue.Enqueue(existing[i]);
    }

    public void ClearMicroActionPlan()
    {
        _microActionQueue.Clear();
        followTarget = null;
    }

    /// <summary>Peek the active action without removing it.</summary>
    public bool TryPeekMicroAction(out IntentMessage head)
    {
        TrimInactiveMicroActions();
        if (_microActionQueue.Count == 0)
        {
            head = default;
            return false;
        }

        head = _microActionQueue.Peek();
        return true;
    }

    /// <summary>Peek the active action, or return idle when the queue is empty.</summary>
    public IntentMessage ResolveActiveMicroAction()
    {
        return TryPeekMicroAction(out var head)
            ? head
            : IntentMessage.Create("idle", LayerSource.Mind);
    }

    /// <summary>Remove and return the active action.</summary>
    public bool TryPopMicroAction(out IntentMessage popped)
    {
        TrimInactiveMicroActions();

        if (_microActionQueue.Count == 0)
        {
            popped = default;
            followTarget = null;
            return false;
        }

        popped = _microActionQueue.Dequeue();
        if (_microActionQueue.Count == 0)
            followTarget = null;
        return true;
    }

    /// <summary>Append one graph-generated micro-action to the action queue.</summary>
    public void EnqueueMicroAction(IntentMessage intent)
    {
        if (string.IsNullOrWhiteSpace(intent.Intent))
            return;
        _microActionQueue.Enqueue(intent);
    }

    public IntentMessage? MindIntent => MicroAction;
    public int  QueuedMindIntentCount => QueuedMicroActionCount;
    public bool HasMindPlan           => HasMicroActionPlan;

    public void SetMindIntent(
        string intent,
        Vector3 directionHint = default,
        string commandId = "",
        string requestId = "",
        string targetKey = "")
        => SetMicroAction(intent, directionHint, commandId, requestId, targetKey);

    public void ReplaceMindPlan(IEnumerable<IntentMessage> intents)
        => ReplaceMicroActionPlan(intents);

    public void InsertMindIntentsAfterCurrent(IEnumerable<IntentMessage> intents)
        => InsertMicroActionsAfterCurrent(intents);

    public void ClearMindPlan() => ClearMicroActionPlan();

    public bool TryPeekMindIntent(out IntentMessage head)
        => TryPeekMicroAction(out head);

    public IntentMessage ResolveActiveIntent()
        => ResolveActiveMicroAction();

    public bool TryPopMindIntent(out IntentMessage popped)
        => TryPopMicroAction(out popped);

    public void EnqueueMindMicroAction(IntentMessage intent)
        => EnqueueMicroAction(intent);

    // -------------------------------------------------------------------------
    // Graph Controls
    // -------------------------------------------------------------------------

    /// <summary>Allow the intent worker to refill the micro-action queue.</summary>
    public void EnableIntentWorker() => IntentWorkerEnabled = true;

    /// <summary>Compatibility alias for older code paths.</summary>
    public void EnableDirectiveMode() => EnableIntentWorker();

    /// <summary>
    /// Apply the active high-level intent and target. The graph reads the intent
    /// to pick a node and the target to aim its actions.
    /// </summary>
    public void SetMindDirective(string intent, string focusTarget = "")
        => SetMindDirective(MindDirective.Create(intent, focusTarget));

    public void SetMindDirective(MindDirective directive)
    {
        ActiveMindDirective = directive.IsValid
            ? MindDirective.Create(
                directive.Intent,
                directive.FocusTarget,
                directive.Reason,
                directive.Mood,
                directive.Style,
                directive.SocialAct,
                directive.RequestId,
                directive.CorrelationId)
            : default;
        MindDirectiveRequestId = ActiveMindDirective.RequestId ?? "";
        MindDirectiveCorrelationId = ActiveMindDirective.CorrelationId ?? "";
        MindDirectiveIntent = ActiveMindDirective.Intent ?? "";
        MindFocusTarget = ActiveMindDirective.FocusTarget ?? "";
        MindDirectiveMood = ActiveMindDirective.Mood ?? "";
        MindDirectiveStyle = ActiveMindDirective.Style ?? "";
        MindDirectiveReason = ActiveMindDirective.Reason ?? "";
        MindDirectiveSocialAct = ActiveMindDirective.SocialAct;
        ClearLastMicroActionOutcome();

        SocialAct social = ActiveMindDirective.SocialAct;
        if (!string.IsNullOrWhiteSpace(social.say))
            SpeakSocialLine(social.say, social.tone);
    }

    public void ClearActiveMindDirective()
    {
        ActiveMindDirective = default;
        MindDirectiveRequestId = "";
        MindDirectiveCorrelationId = "";
        MindDirectiveIntent = "";
        MindFocusTarget = "";
        MindDirectiveMood = "";
        MindDirectiveStyle = "";
        MindDirectiveReason = "";
        MindDirectiveSocialAct = default;
        ClearLastMicroActionOutcome();
    }

    public void RecordMicroActionOutcome(IntentMessage intent, string status, string reason)
    {
        LastMicroActionIntent = intent.Intent ?? "";
        LastMicroActionTarget = intent.TargetKey ?? "";
        LastMicroActionStatus = status ?? "";
        LastMicroActionReason = reason ?? "";
    }

    public void ClearLastMicroActionOutcome()
    {
        LastMicroActionIntent = "";
        LastMicroActionTarget = "";
        LastMicroActionStatus = "";
        LastMicroActionReason = "";
    }

    /// <summary>Replace the graph scoring weights used when no directive is active.</summary>
    public void SetMindWeights(CatBehaviorWeights weights)
    {
        if (weights != null)
            MindWeights = weights;
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
        int queued = QueuedMicroActionCount;
        _debugIntentQueue = _intentQueue.Count > 0 ? $"{_intentQueue.Count} queued" : "empty";
        _debugMicroActionSlot  = TryPeekMicroAction(out var head) ? head.ToString() : "—";
        _debugMicroActionQueue = queued > 0 ? $"{queued} queued" : "empty";
    }

    // -------------------------------------------------------------------------
    // Queue Helpers
    // -------------------------------------------------------------------------

    void TrimInactiveMicroActions()
    {
        while (_microActionQueue.Count > 0 && !_microActionQueue.Peek().IsActive)
            _microActionQueue.Dequeue();

        if (_microActionQueue.Count == 0)
            followTarget = null;
    }

    int PendingMicroActionCount()
    {
        TrimInactiveMicroActions();
        return Mathf.Max(0, _microActionQueue.Count - 1);
    }

    void CoalesceSocialStimulus(SocialStimulus incoming)
    {
        if (_socialStimulusQueue.Count == 0)
            return;

        SocialStimulus[] existing = _socialStimulusQueue.ToArray();
        _socialStimulusQueue.Clear();
        for (int i = 0; i < existing.Length; i++)
        {
            if (!existing[i].SameCoalescingKey(incoming))
                _socialStimulusQueue.Enqueue(existing[i]);
        }
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
