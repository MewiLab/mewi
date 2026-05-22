using System;
using System.Collections.Generic;
using UnityEngine;

[DisallowMultipleComponent]
public class AttachmentBehaviorLogger : MonoBehaviour
{
    [Header("Identity")]
    [SerializeField] CreatureBlackboard blackboard;
    [SerializeField] string catAssignedType = AttachmentAssignedCatTypes.Avoidant;

    [Header("Player Source")]
    [SerializeField] Transform playerOverride;

    [Header("Sampling")]
    [SerializeField, Min(0.05f)] float sampleIntervalSeconds = 0.25f;
    [SerializeField, Min(0f)] float nearDistanceMeters = 2f;
    [SerializeField, Min(0f)] float farDistanceMeters = 5f;
    [SerializeField, Min(0.01f)] float approachDeltaMeters = 0.6f;
    [SerializeField, Min(0.01f)] float retreatDeltaMeters = 0.8f;
    [SerializeField, Min(0f)] float duplicateEventCooldownSeconds = 1f;

    [Header("Automatic Events")]
    [SerializeField] bool logDistanceEvents = true;
    [SerializeField] bool logMindIntentEvents = true;

    [Header("Debug")]
    [SerializeField] bool debugLogEvents;

    readonly List<AttachmentEventPayload> _events = new List<AttachmentEventPayload>();
    readonly Dictionary<string, float> _lastEventTimes = new Dictionary<string, float>(StringComparer.Ordinal);

    string _sessionId = "";
    float _sessionStartedAt;
    float _nextSampleAt;
    float _lastDistance = Mathf.Infinity;
    bool _hasDistanceSample;
    bool _hasSeenPlayer;
    bool _wasNear;
    bool _wasFarOrAbsent = true;
    string _lastObservedIntent = "";

    public string SessionId => _sessionId;
    public string CatId => blackboard != null ? blackboard.CreatureId : gameObject.name;
    public int EventCount => _events.Count;
    public IReadOnlyList<AttachmentEventPayload> Events => _events;

    public string CatAssignedType
    {
        get => AttachmentAssignedCatTypes.Normalize(catAssignedType);
        set => catAssignedType = AttachmentAssignedCatTypes.Normalize(value);
    }

    void Awake()
    {
        AutoWire();
        ResetSession();
    }

    void OnValidate()
    {
        catAssignedType = AttachmentAssignedCatTypes.Normalize(catAssignedType);
        farDistanceMeters = Mathf.Max(farDistanceMeters, nearDistanceMeters);
    }

    void Update()
    {
        if (Time.time < _nextSampleAt)
            return;

        _nextSampleAt = Time.time + sampleIntervalSeconds;

        if (logDistanceEvents)
            SamplePlayerDistance();

        if (logMindIntentEvents)
            SampleMindIntent();
    }

    public void UseBlackboard(CreatureBlackboard fallbackBlackboard)
    {
        if (blackboard == null)
            blackboard = fallbackBlackboard;
    }

    public void ResetSession()
    {
        _sessionId = Guid.NewGuid().ToString("D");
        _sessionStartedAt = Time.time;
        _nextSampleAt = Time.time;
        _events.Clear();
        _lastEventTimes.Clear();
        _lastDistance = Mathf.Infinity;
        _hasDistanceSample = false;
        _hasSeenPlayer = false;
        _wasNear = false;
        _wasFarOrAbsent = true;
        _lastObservedIntent = "";
    }

    public AttachmentSessionPayload BuildPayload()
    {
        AutoWire();
        if (string.IsNullOrWhiteSpace(_sessionId))
            ResetSession();

        return new AttachmentSessionPayload
        {
            session_id = _sessionId,
            cat_id = CatId,
            cat_assigned_type = CatAssignedType,
            events = _events.ToArray(),
        };
    }

    public bool LogPlayerInteracted(string source = "manual", string note = "")
    {
        return LogEvent(AttachmentEventTypes.PlayerInteracted, source, "", "", note);
    }

    public bool LogCatWithdrew(string source = "manual", string action = "", string target = "", string note = "")
    {
        return LogEvent(AttachmentEventTypes.CatWithdrew, source, action, target, note);
    }

    public bool LogCatSoughtPlayer(string source = "manual", string action = "", string target = "", string note = "")
    {
        return LogEvent(AttachmentEventTypes.CatSoughtPlayer, source, action, target, note);
    }

    public bool LogPlayerReturnedAfterAbsence(string source = "manual", string note = "")
    {
        return LogEvent(AttachmentEventTypes.PlayerReturnedAfterAbsence, source, "", "", note);
    }

    public bool LogEvent(string eventType, string source = "manual", string action = "", string target = "", string note = "")
    {
        AutoWire();
        float distance = CurrentDistanceOrDefault();
        bool playerVisible = blackboard != null && blackboard.playerInSight;
        string intent = CurrentMindIntent(out string targetKey);

        return RecordEvent(
            eventType,
            distance,
            source,
            action,
            target,
            note,
            intent,
            targetKey,
            playerVisible,
            enforceCooldown: true);
    }

    void SamplePlayerDistance()
    {
        if (!TryGetCurrentPlayerDistance(out float distance, out bool playerVisible))
        {
            if (!_wasFarOrAbsent)
            {
                string missingTargetKey;
                string missingIntent = CurrentMindIntent(out missingTargetKey);
                RecordEvent(
                    AttachmentEventTypes.PlayerLeft,
                    Mathf.Max(0f, farDistanceMeters),
                    "distance_sample",
                    "",
                    "",
                    "no visible player target",
                    missingIntent,
                    missingTargetKey,
                    false,
                    enforceCooldown: true);
            }

            _wasFarOrAbsent = true;
            _wasNear = false;
            _hasDistanceSample = false;
            return;
        }

        bool isNear = distance <= nearDistanceMeters;
        bool isFar = distance >= farDistanceMeters;
        string targetKey;
        string currentIntent = CurrentMindIntent(out targetKey);

        if (_hasSeenPlayer && _wasFarOrAbsent && isNear)
        {
            RecordEvent(
                AttachmentEventTypes.PlayerReturnedAfterAbsence,
                distance,
                "distance_sample",
                "",
                "",
                "player crossed from absent/far into near range",
                currentIntent,
                targetKey,
                playerVisible,
                enforceCooldown: true);
        }

        if (isNear && !_wasNear)
        {
            RecordEvent(
                AttachmentEventTypes.PlayerNear,
                distance,
                "distance_sample",
                "",
                "",
                "",
                currentIntent,
                targetKey,
                playerVisible,
                enforceCooldown: true);
        }

        if (isFar && !_wasFarOrAbsent)
        {
            RecordEvent(
                AttachmentEventTypes.PlayerFar,
                distance,
                "distance_sample",
                "",
                "",
                "",
                currentIntent,
                targetKey,
                playerVisible,
                enforceCooldown: true);
        }

        if (_hasDistanceSample)
        {
            float distanceDelta = _lastDistance - distance;
            if (distanceDelta >= approachDeltaMeters)
            {
                RecordEvent(
                    AttachmentEventTypes.PlayerApproached,
                    distance,
                    "distance_sample",
                    "",
                    "",
                    "",
                    currentIntent,
                    targetKey,
                    playerVisible,
                    enforceCooldown: true);
            }
            else if (-distanceDelta >= retreatDeltaMeters)
            {
                RecordEvent(
                    AttachmentEventTypes.PlayerRetreated,
                    distance,
                    "distance_sample",
                    "",
                    "",
                    "",
                    currentIntent,
                    targetKey,
                    playerVisible,
                    enforceCooldown: true);
            }
        }

        _hasSeenPlayer = true;
        _hasDistanceSample = true;
        _lastDistance = distance;
        _wasNear = isNear;

        if (isFar)
            _wasFarOrAbsent = true;
        else if (isNear)
            _wasFarOrAbsent = false;
    }

    void SampleMindIntent()
    {
        string targetKey;
        string intent = CurrentMindIntent(out targetKey);
        if (string.Equals(intent, _lastObservedIntent, StringComparison.Ordinal))
            return;

        _lastObservedIntent = intent;
        if (string.IsNullOrWhiteSpace(intent))
            return;

        if (IsCatWithdrawalIntent(intent))
        {
            RecordEvent(
                AttachmentEventTypes.CatWithdrew,
                CurrentDistanceOrDefault(),
                "mind_intent",
                intent,
                targetKey,
                "",
                intent,
                targetKey,
                blackboard != null && blackboard.playerInSight,
                enforceCooldown: true);
            return;
        }

        if (IsCatSeekingPlayerIntent(intent, targetKey))
        {
            RecordEvent(
                AttachmentEventTypes.CatSoughtPlayer,
                CurrentDistanceOrDefault(),
                "mind_intent",
                intent,
                targetKey,
                "",
                intent,
                targetKey,
                blackboard != null && blackboard.playerInSight,
                enforceCooldown: true);
        }
    }

    bool RecordEvent(
        string eventType,
        float distance,
        string source,
        string action,
        string target,
        string note,
        string catIntent,
        string targetKey,
        bool playerVisible,
        bool enforceCooldown)
    {
        string rawEventType = eventType;
        eventType = AttachmentEventTypes.Normalize(eventType);
        if (string.IsNullOrWhiteSpace(eventType))
        {
            Debug.LogWarning($"[AttachmentBehaviorLogger] ignored unknown event type '{rawEventType}'");
            return false;
        }

        float now = Time.time;
        if (enforceCooldown &&
            _lastEventTimes.TryGetValue(eventType, out float lastAt) &&
            now - lastAt < duplicateEventCooldownSeconds)
        {
            return false;
        }

        _lastEventTimes[eventType] = now;

        var payload = new AttachmentEventPayload
        {
            event_name = eventType,
            event_type = eventType,
            @event = eventType,
            t = Mathf.Max(0f, now - _sessionStartedAt),
            distance = Mathf.Max(0f, distance),
            meta = new AttachmentEventMeta
            {
                source = source ?? "",
                action = action ?? "",
                target = target ?? "",
                note = note ?? "",
                cat_intent = catIntent ?? "",
                target_key = targetKey ?? "",
                player_visible = playerVisible,
            },
        };

        payload.meta.zone = CurrentZoneId();
        _events.Add(payload);

        if (debugLogEvents)
            Debug.Log($"[AttachmentBehaviorLogger] {payload.@event} t={payload.t:F2} distance={payload.distance:F2} source={payload.meta.source}");

        return true;
    }

    bool TryGetCurrentPlayerDistance(out float distance, out bool playerVisible)
    {
        AutoWire();
        playerVisible = blackboard != null && blackboard.playerInSight;

        Transform player = playerOverride;
        if (player == null && blackboard != null)
            player = blackboard.closestPlayer;

        if (player == null)
        {
            distance = Mathf.Infinity;
            return false;
        }

        if (blackboard != null &&
            player == blackboard.closestPlayer &&
            !float.IsInfinity(blackboard.closestPlayerDist) &&
            blackboard.closestPlayerDist >= 0f)
        {
            distance = blackboard.closestPlayerDist;
            return true;
        }

        distance = Vector3.Distance(transform.position, player.position);
        return true;
    }

    float CurrentDistanceOrDefault()
    {
        return TryGetCurrentPlayerDistance(out float distance, out _)
            ? distance
            : Mathf.Max(0f, farDistanceMeters);
    }

    string CurrentMindIntent(out string targetKey)
    {
        targetKey = "";
        if (blackboard == null || !blackboard.MindIntent.HasValue)
            return "";

        IntentMessage intent = blackboard.MindIntent.Value;
        targetKey = intent.TargetKey ?? "";
        return intent.Intent ?? "";
    }

    string CurrentZoneId()
    {
        if (blackboard == null || blackboard.activeZones == null || blackboard.activeZones.Count == 0)
            return "";

        ZoneVolume innermost = blackboard.activeZones[blackboard.activeZones.Count - 1];
        return innermost != null ? innermost.EffectiveZoneId : "";
    }

    void AutoWire()
    {
        if (blackboard != null)
            return;

        blackboard = GetComponent<CreatureBlackboard>();
        if (blackboard == null)
            blackboard = GetComponentInParent<CreatureBlackboard>();
        if (blackboard == null)
            blackboard = GetComponentInChildren<CreatureBlackboard>();
    }

    static bool IsCatWithdrawalIntent(string intent)
    {
        if (string.IsNullOrWhiteSpace(intent))
            return false;

        switch (intent.Trim().ToLowerInvariant())
        {
            case "flee":
            case "hide":
                return true;
            default:
                return false;
        }
    }

    static bool IsCatSeekingPlayerIntent(string intent, string targetKey)
    {
        if (string.IsNullOrWhiteSpace(intent))
            return false;

        string normalized = intent.Trim().ToLowerInvariant();
        if (normalized == "follow")
            return true;

        if (normalized != "go_to")
            return false;

        if (string.IsNullOrWhiteSpace(targetKey))
            return false;

        string target = targetKey.Trim().ToLowerInvariant();
        return target.Contains("player") || target.Contains("human");
    }
}
