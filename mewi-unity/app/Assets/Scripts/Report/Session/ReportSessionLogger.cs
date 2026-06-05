using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using UnityEngine;
using UnityEngine.SceneManagement;

/// <summary>
/// Closed-session behavioral report logger for mewi-report raw JSON.
/// It records factual player/cat session events only; Python owns all report
/// values. Live cat micro-action feedback uses PlanExecutionReport instead.
/// </summary>
public class ReportSessionLogger : MonoBehaviour
{
    [Serializable]
    public class ReportCatBinding
    {
        public string catId;
        public CreatureBlackboard blackboard;

        public Transform Transform => blackboard != null ? blackboard.transform : null;
    }

    [Header("Report Identity")]
    [SerializeField] string userId = "local_user";
    [SerializeField] string buildOverride = "";

    [Header("Actors")]
    [Tooltip("Human-controlled actor. This may use the same creature prefab as NPC cats.")]
    [SerializeField] Transform humanActor;
    [SerializeField] CreatureBlackboard humanBlackboard;
    [SerializeField] List<ReportCatBinding> reportCats = new List<ReportCatBinding>();

    [Header("Derived Human Actions")]
    [SerializeField] bool deriveProximityActions = true;
    [Tooltip("Seconds between distance samples used to derive approach/retreat.")]
    [SerializeField, Min(0.05f)] float proximitySampleInterval = 0.5f;
    [Tooltip("Distance change required before an approach/retreat event is recorded.")]
    [SerializeField, Min(0.01f)] float approachDistanceDeltaMeters = 0.35f;
    [Tooltip("Only derive approach/retreat while the human is within this distance of the target cat.")]
    [SerializeField, Min(0.1f)] float approachMaxDistanceMeters = 8f;
    [Tooltip("Minimum time between derived proximity actions to avoid event spam.")]
    [SerializeField, Min(0f)] float derivedActionCooldownSeconds = 1.5f;
    [Tooltip("When the human remains near the same cat with very low distance change, record wait.")]
    [SerializeField] bool deriveWaitActions = true;
    [SerializeField, Min(0.01f)] float waitDistanceJitterMeters = 0.08f;
    [SerializeField, Min(0.1f)] float waitMinSeconds = 2.0f;

    [Header("Derived Cat State")]
    [Tooltip("Automatically log each bound cat's action + trust by polling its blackboard, so cat events don't need manual Record calls.")]
    [SerializeField] bool logCatStateChanges = true;
    [Tooltip("Seconds between cat-state samples.")]
    [SerializeField, Min(0.05f)] float catSampleInterval = 0.5f;
    [Tooltip("Minimum trust change (0-100 scale) that triggers a cat event when the action has not changed.")]
    [SerializeField, Range(1, 100)] int catTrustChangeThreshold = 1;

    [Header("Session")]
    [SerializeField] bool startSessionOnStart = true;
    [SerializeField] string schemaVersion = ReportSessionPayload.RawSchemaV2;
    [SerializeField] bool saveLocalOnSessionEnd = true;
    [SerializeField] bool sendToBackendOnSessionEnd = false;
    [SerializeField] string sessionIdPrefix = "unity-session";
    [SerializeField] ReportSessionSender sender;
    [Tooltip("Optional local outbox. When assigned, saved JSON goes to {user}/pending and can be sent manually.")]
    [SerializeField] ReportSessionFileOutbox fileOutbox;

    [Header("In-Game Send")]
    [Tooltip("Show an on-screen button during play to send the current (still running) session without quitting.")]
    [SerializeField] bool showInGameSendButton = true;
    [Tooltip("Optional hotkey that also sends the current session while playing.")]
    [SerializeField] KeyCode sendCurrentSessionKey = KeyCode.F9;

    [Header("Export")]
    [Tooltip("Optional absolute export folder. Empty uses Application.persistentDataPath/mewi_report_sessions.")]
    [SerializeField] string exportDirectory = "";
    [Tooltip("Optional file name override. Empty uses {session_id}.json.")]
    [SerializeField] string exportFileName = "";

    readonly List<ReportEvent> _events = new List<ReportEvent>();
    readonly List<ReportMultiCatEncounter> _encounters = new List<ReportMultiCatEncounter>();
    ReportSessionPayload _lastPayload;
    int _nextEventIndex = 1;

    bool _sessionActive;
    int _nextSessionIndex = 1;
    float _sessionStartedAt;
    string _sessionId = "";
    string _timestampStart = "";
    bool _isQuitting;

    float _lastSampleAt = -1f;
    float _lastDistance = -1f;
    float _lastDerivedActionAt = -999f;
    float _stationarySince = -1f;
    string _lastNearestCatId = "";
    string _lastDerivedAction = "";

    float _lastCatSampleAt = -1f;
    readonly Dictionary<string, CatStateSample> _catState = new Dictionary<string, CatStateSample>();

    struct CatStateSample
    {
        public string action;
        public int trust;
    }

    void Awake()
    {
        ResolveActorDefaults();
    }

    void OnEnable()
    {
        PlayerCatActionEmitter.GlobalActionEmitted += RecordPlayerCatActionEvent;
        CreatureSocialStimulusBus.GlobalStimulusDelivered += RecordSocialStimulusDelivered;
        CreatureSocialStimulusPolicy.GlobalReactionDirectiveChosen += RecordNpcReactionDirectiveChosen;
    }

    void OnDisable()
    {
        PlayerCatActionEmitter.GlobalActionEmitted -= RecordPlayerCatActionEvent;
        CreatureSocialStimulusBus.GlobalStimulusDelivered -= RecordSocialStimulusDelivered;
        CreatureSocialStimulusPolicy.GlobalReactionDirectiveChosen -= RecordNpcReactionDirectiveChosen;
    }

    void Start()
    {
        if (startSessionOnStart)
            StartSession();
    }

    void Update()
    {
#if ENABLE_LEGACY_INPUT_MANAGER
        if (sendCurrentSessionKey != KeyCode.None && Input.GetKeyDown(sendCurrentSessionKey))
            SendCurrentSession();
#endif

        if (!_sessionActive)
            return;

        if (deriveProximityActions)
            SampleHumanProximity();

        if (logCatStateChanges)
            SampleCatState();
    }

    void OnGUI()
    {
        if (!showInGameSendButton)
            return;

        const float w = 220f, h = 34f, pad = 10f;
        var rect = new Rect(pad, pad, w, h);
        int events = _sessionActive ? _events.Count : 0;
        string label = _sessionActive
            ? $"Send report now ({events} events)"
            : "Send last report";
        if (GUI.Button(rect, label))
            SendCurrentSession();
    }

    void OnApplicationQuit()
    {
        _isQuitting = true;
        if (_sessionActive)
            EndSession(saveLocalOnSessionEnd);
    }

    public void ConfigurePlayerIdentity(
        string nextUserId,
        Transform actor,
        CreatureBlackboard actorBlackboard,
        string nextSessionIdPrefix = "")
    {
        if (!string.IsNullOrWhiteSpace(nextUserId))
            userId = nextUserId.Trim();
        if (!string.IsNullOrWhiteSpace(nextSessionIdPrefix))
            sessionIdPrefix = nextSessionIdPrefix.Trim();
        if (actor != null)
            humanActor = actor;
        if (actorBlackboard != null)
            humanBlackboard = actorBlackboard;
    }

    [ContextMenu("Report/Start Session")]
    public void StartSession()
    {
        if (_sessionActive)
            EndSession(false);

        ResolveActorDefaults();
        _events.Clear();
        _encounters.Clear();

        _sessionActive = true;
        _sessionStartedAt = Time.time;
        _timestampStart = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ", CultureInfo.InvariantCulture);
        _sessionId = $"{sessionIdPrefix}-{_nextSessionIndex:00}-{DateTime.UtcNow:yyyyMMddHHmmss}";

        _lastSampleAt = -1f;
        _lastDistance = -1f;
        _lastDerivedActionAt = -999f;
        _stationarySince = -1f;
        _lastNearestCatId = "";
        _lastDerivedAction = "";
        _nextEventIndex = 1;

        _lastCatSampleAt = -1f;
        _catState.Clear();
    }

    [ContextMenu("Report/End Session")]
    public void EndSessionFromInspector()
    {
        EndSession(false);
    }

    public void EndSession(bool exportAfterEnd)
    {
        if (!_sessionActive)
            return;

        var session = new ReportSession
        {
            session_id = _sessionId,
            session_index = _nextSessionIndex,
            timestamp_start = _timestampStart,
            timestamp_end = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ", CultureInfo.InvariantCulture),
            close_reason = "game_session_closed",
            duration_seconds = Mathf.Max(0f, Time.time - _sessionStartedAt),
            events = _events.ToArray(),
            multi_cat_encounters = _encounters.ToArray(),
        };
        _lastPayload = BuildPayload(session);

        _nextSessionIndex++;
        _sessionActive = false;
        _events.Clear();
        _encounters.Clear();

        string savedPath = "";
        if (exportAfterEnd)
            savedPath = SaveToJsonFile(_lastPayload);

        if (sendToBackendOnSessionEnd && !_isQuitting)
        {
            if (fileOutbox != null && !string.IsNullOrEmpty(savedPath))
                fileOutbox.SendFile(savedPath);
            else if (sender != null)
                sender.Send(_lastPayload);
        }
    }

    /// <summary>
    /// Save and send the current session WITHOUT ending it, so a report can be
    /// delivered mid-game. The session keeps running and accumulating events;
    /// later flushes (and the final EndSession) reuse the same session_id, so the
    /// backend simply overwrites with the newest snapshot.
    /// </summary>
    [ContextMenu("Report/Send Current Session (in-game)")]
    public void SendCurrentSession()
    {
        ReportSessionPayload payload = BuildPayload();
        if (payload == null || payload.session == null)
        {
            Debug.LogWarning("[ReportSessionLogger] no session to send yet.");
            return;
        }

        if (fileOutbox != null)
        {
            string path = fileOutbox.SavePending(payload);
            fileOutbox.SendFile(path);
            Debug.Log($"[ReportSessionLogger] sent current session {payload.session.session_id} " +
                      $"({payload.session.events.Length} events) via outbox.");
        }
        else if (sender != null)
        {
            sender.Send(payload);
            Debug.Log($"[ReportSessionLogger] sent current session {payload.session.session_id} " +
                      $"({payload.session.events.Length} events) directly.");
        }
        else
        {
            Debug.LogWarning("[ReportSessionLogger] no sender or outbox assigned; cannot send.");
        }
    }

    public void RecordHumanAction(string action)
    {
        RecordHumanAction(action, null, null);
    }

    public void RecordHumanAction(string action, ReportEventParams paramsData, ReportEventMeta meta)
    {
        if (!_sessionActive)
            StartSession();

        string canonical = ReportActionClassifier.ToSnakeCase(action);
        if (string.IsNullOrEmpty(canonical))
            return;

        ReportEventParams eventParams = paramsData ?? BuildHumanParams(null, "");
        _events.Add(new ReportEvent
        {
            event_id = NextEventId(),
            correlation_id = "",
            t = EventTime(),
            actor = "human",
            actor_id = HumanActorId(),
            action = canonical,
            cat_id = "",
            target_id = eventParams.target_id ?? "",
            phase = "completed",
            status = "",
            trust_before = 0,
            trust_after = 0,
            trigger = "",
            @params = eventParams,
            meta = meta ?? BuildMeta("manual", ""),
        });
    }

    /// <summary>
    /// Use this when the human-controlled prefab runs the same motor intents as
    /// cats. go_to/investigate/follow only become report "approach" when the
    /// target is one of the configured report cats.
    /// </summary>
    public void RecordHumanMotorIntent(string intent, Transform target)
    {
        ReportCatBinding cat = FindCatBinding(target);
        bool targetIsReportCat = cat != null;
        string action = ReportActionClassifier.FromHumanMotorIntent(intent, targetIsReportCat);

        var paramsData = BuildHumanParams(target, targetIsReportCat ? cat.catId : "");
        var meta = BuildMeta("manual_motor_intent", $"motor_intent={intent}");
        RecordHumanAction(action, paramsData, meta);
    }

    public void RecordHumanMotorIntent(string intent)
    {
        ReportCatBinding nearest = FindNearestCat(out float distance);
        Transform target = nearest != null && distance <= approachMaxDistanceMeters ? nearest.Transform : null;
        RecordHumanMotorIntent(intent, target);
    }

    public void RecordOfferItem(string itemId)
    {
        ReportCatBinding nearest = FindNearestCat(out float distance);
        var paramsData = BuildHumanParams(nearest != null ? nearest.Transform : null, nearest != null ? nearest.catId : "");
        paramsData.item_id = itemId ?? "";
        paramsData.distance_to_nearest_cat_m = MissingIfInvalid(distance);
        RecordHumanAction(ReportActionClassifier.OfferItem, paramsData, BuildMeta("manual_offer", ""));
    }

    public void RecordPetAttempt()
    {
        ReportCatBinding nearest = FindNearestCat(out float distance);
        var paramsData = BuildHumanParams(nearest != null ? nearest.Transform : null, nearest != null ? nearest.catId : "");
        paramsData.distance_to_nearest_cat_m = MissingIfInvalid(distance);
        RecordHumanAction(ReportActionClassifier.PetAttempt, paramsData, BuildMeta("manual_pet", ""));
    }

    public void RecordCallOut()
    {
        ReportCatBinding nearest = FindNearestCat(out float distance);
        var paramsData = BuildHumanParams(nearest != null ? nearest.Transform : null, nearest != null ? nearest.catId : "");
        paramsData.distance_to_nearest_cat_m = MissingIfInvalid(distance);
        RecordHumanAction(ReportActionClassifier.CallOut, paramsData, BuildMeta("manual_call", ""));
    }

    public void RecordPlayerCatActionEvent(PlayerCatActionEvent actionEvent)
    {
        if (string.IsNullOrWhiteSpace(actionEvent.Kind))
            return;

        if (!_sessionActive)
            StartSession();

        string targetId = actionEvent.TargetCatId ?? "";
        var paramsData = new ReportEventParams
        {
            zone_id = CurrentZoneId(humanBlackboard),
            target_id = targetId,
            item_id = "",
            subtype = "",
            initiated_by = "player_cat_social_fsm",
            behavior_key = actionEvent.BehaviorKey,
            motor_action = actionEvent.MotorAction,
            social_act_kind = "",
            source_event_id = "",
            distance_to_player_m = -1f,
            distance_to_nearest_cat_m = MissingIfInvalid(actionEvent.DistanceMeters),
            facing_dot = MissingIfInvalid(actionEvent.FacingDot),
            confidence = MissingIfInvalid(actionEvent.Confidence),
            speed_mps = -1f,
        };

        _events.Add(new ReportEvent
        {
            event_id = string.IsNullOrWhiteSpace(actionEvent.EventId) ? NextEventId() : actionEvent.EventId,
            correlation_id = actionEvent.CorrelationId ?? "",
            t = EventTime(),
            actor = "player_cat",
            actor_id = string.IsNullOrWhiteSpace(actionEvent.ActorId) ? HumanActorId() : actionEvent.ActorId,
            action = ReportActionClassifier.ToSnakeCase(actionEvent.Kind),
            cat_id = "",
            target_id = targetId,
            phase = string.IsNullOrWhiteSpace(actionEvent.Phase) ? "completed" : actionEvent.Phase,
            status = "",
            trust_before = 0,
            trust_after = 0,
            trigger = "",
            @params = paramsData,
            meta = BuildMeta("player_cat_social_fsm", ""),
        });
    }

    public void RecordSocialStimulusDelivered(SocialStimulus stimulus)
    {
        if (!stimulus.IsValid)
            return;

        if (!_sessionActive)
            StartSession();

        var paramsData = new ReportEventParams
        {
            zone_id = "",
            target_id = stimulus.TargetCatId ?? "",
            item_id = "",
            subtype = "",
            initiated_by = "creature_social_stimulus_bus",
            behavior_key = "",
            motor_action = "",
            social_act_kind = "",
            source_event_id = stimulus.SourceEventId ?? "",
            distance_to_player_m = -1f,
            distance_to_nearest_cat_m = MissingIfInvalid(stimulus.DistanceMeters),
            facing_dot = MissingIfInvalid(stimulus.FacingDot),
            confidence = MissingIfInvalid(stimulus.Confidence),
            speed_mps = -1f,
        };

        _events.Add(new ReportEvent
        {
            event_id = stimulus.EventId,
            correlation_id = stimulus.CorrelationId ?? "",
            t = EventTime(),
            actor = "system",
            actor_id = "",
            action = "social_stimulus_delivered",
            cat_id = "",
            target_id = stimulus.TargetCatId ?? "",
            phase = "delivered",
            status = "",
            trust_before = 0,
            trust_after = 0,
            trigger = "",
            @params = paramsData,
            meta = BuildMeta("creature_social_stimulus_bus", ""),
        });
    }

    public void RecordNpcReactionDirectiveChosen(
        CreatureBlackboard board,
        SocialStimulus stimulus,
        CreatureBlackboard.MindDirective directive)
    {
        if (board == null || !stimulus.IsValid || !directive.IsValid)
            return;

        if (!_sessionActive)
            StartSession();

        string catId = board.CreatureId.Trim().ToLowerInvariant();
        string socialKind = directive.SocialAct.kind ?? "";
        var paramsData = new ReportEventParams
        {
            zone_id = CurrentZoneId(board),
            target_id = stimulus.ActorId ?? "",
            item_id = "",
            subtype = "",
            initiated_by = "creature_social_stimulus_policy",
            behavior_key = socialKind,
            motor_action = "",
            social_act_kind = socialKind,
            source_event_id = stimulus.SourceEventId ?? "",
            distance_to_player_m = MissingIfInvalid(stimulus.DistanceMeters),
            distance_to_nearest_cat_m = -1f,
            facing_dot = MissingIfInvalid(stimulus.FacingDot),
            confidence = MissingIfInvalid(stimulus.Confidence),
            speed_mps = -1f,
        };

        _events.Add(new ReportEvent
        {
            event_id = NextEventId(),
            correlation_id = stimulus.CorrelationId ?? "",
            t = EventTime(),
            actor = "cat",
            actor_id = catId,
            action = ReportActionClassifier.ToSnakeCase(socialKind),
            cat_id = catId,
            target_id = stimulus.ActorId ?? "",
            phase = "chosen",
            status = "",
            trust_before = TrustScore(board),
            trust_after = TrustScore(board),
            trigger = "social_stimulus",
            @params = paramsData,
            meta = BuildMeta("creature_social_stimulus_policy", directive.Reason),
        });
    }

    public void RecordCatActionById(string catId, string action, int trustBefore, int trustAfter, string trigger)
    {
        ReportCatBinding cat = FindCatBinding(catId);
        RecordCatAction(cat, action, trustBefore, trustAfter, trigger, null, null);
    }

    public void RecordCatAction(
        ReportCatBinding cat,
        string action,
        int trustBefore,
        int trustAfter,
        string trigger,
        ReportEventParams paramsData,
        ReportEventMeta meta,
        string correlationId = "")
    {
        if (cat == null || string.IsNullOrWhiteSpace(cat.catId))
            return;

        if (!_sessionActive)
            StartSession();

        ReportEventParams eventParams = paramsData ?? BuildCatParams(cat);
        _events.Add(new ReportEvent
        {
            event_id = NextEventId(),
            correlation_id = correlationId ?? "",
            t = EventTime(),
            actor = "cat",
            actor_id = cat.catId.Trim().ToLowerInvariant(),
            action = ReportActionClassifier.ToSnakeCase(action),
            cat_id = cat.catId.Trim().ToLowerInvariant(),
            target_id = eventParams.target_id ?? "",
            phase = "completed",
            status = "",
            trust_before = Mathf.Clamp(trustBefore, 0, 100),
            trust_after = Mathf.Clamp(trustAfter, 0, 100),
            trigger = ReportActionClassifier.ToSnakeCase(trigger),
            @params = eventParams,
            meta = meta ?? BuildMeta("manual_cat", ""),
        });
    }

    public void RecordCatCurrentTrust(string catId, string action, string trigger)
    {
        ReportCatBinding cat = FindCatBinding(catId);
        if (cat == null)
            return;

        int trust = TrustScore(cat.blackboard);
        RecordCatAction(cat, action, trust, trust, trigger, null, null);
    }

    public void RecordMultiCatEncounter(string[] catsPresent, string humanAction, string outcome)
    {
        if (!_sessionActive)
            StartSession();

        _encounters.Add(new ReportMultiCatEncounter
        {
            t = EventTime(),
            cats_present = catsPresent ?? Array.Empty<string>(),
            human_action = ReportActionClassifier.ToSnakeCase(humanAction),
            outcome = ReportActionClassifier.ToSnakeCase(outcome),
        });
    }

    [ContextMenu("Report/Save JSON")]
    public void SaveToJsonFileFromInspector()
    {
        SaveToJsonFile();
    }

    public string SaveToJsonFile()
    {
        return SaveToJsonFile(BuildPayload());
    }

    public string SaveToJsonFile(ReportSessionPayload payload)
    {
        if (payload == null || payload.session == null)
        {
            Debug.LogWarning("[ReportSessionLogger] no report session payload to save.");
            return "";
        }

        if (fileOutbox != null)
            return fileOutbox.SavePending(payload);

        string dir = string.IsNullOrWhiteSpace(exportDirectory)
            ? Path.Combine(Application.persistentDataPath, "mewi_report_sessions", SafePathSegment(payload.user_id))
            : exportDirectory.Trim();

        Directory.CreateDirectory(dir);
        string safeFileName = string.IsNullOrWhiteSpace(exportFileName)
            ? $"{SafePathSegment(payload.session.session_id)}.json"
            : SafeFileName(exportFileName.Trim());
        string path = Path.Combine(dir, safeFileName);

        File.WriteAllText(path, JsonUtility.ToJson(payload, true));
        Debug.Log($"[ReportSessionLogger] saved {path}");
        return path;
    }

    public string ExportJson()
    {
        ReportSessionPayload payload = BuildPayload();
        return payload != null ? JsonUtility.ToJson(payload, true) : "";
    }

    public ReportSessionPayload BuildPayload()
    {
        if (_sessionActive)
            return BuildPayload(CurrentSessionSnapshot());
        return _lastPayload;
    }

    ReportSessionPayload BuildPayload(ReportSession session)
    {
        return new ReportSessionPayload
        {
            schema_version = string.IsNullOrWhiteSpace(schemaVersion)
                ? ReportSessionPayload.RawSchemaV1
                : schemaVersion.Trim(),
            user_id = string.IsNullOrWhiteSpace(userId) ? "local_user" : userId.Trim(),
            source = BuildSource(),
            session = session,
        };
    }

    ReportSession CurrentSessionSnapshot()
    {
        if (!_sessionActive)
            return null;

        return new ReportSession
        {
            session_id = _sessionId,
            session_index = _nextSessionIndex,
            timestamp_start = _timestampStart,
            timestamp_end = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ", CultureInfo.InvariantCulture),
            close_reason = "in_progress_snapshot",
            duration_seconds = Mathf.Max(0f, Time.time - _sessionStartedAt),
            events = _events.ToArray(),
            multi_cat_encounters = _encounters.ToArray(),
        };
    }

    void SampleHumanProximity()
    {
        if (humanActor == null)
            return;

        if (_lastSampleAt >= 0f && Time.time - _lastSampleAt < proximitySampleInterval)
            return;

        ReportCatBinding nearest = FindNearestCat(out float distance);
        if (nearest == null)
            return;

        float now = Time.time;
        float elapsed = _lastSampleAt >= 0f ? now - _lastSampleAt : 0f;
        bool sameCat = string.Equals(_lastNearestCatId, nearest.catId, StringComparison.OrdinalIgnoreCase);

        if (!sameCat || _lastDistance < 0f || elapsed <= Mathf.Epsilon)
        {
            _lastNearestCatId = nearest.catId;
            _lastDistance = distance;
            _lastSampleAt = now;
            _stationarySince = -1f;
            return;
        }

        float speed;
        if (ReportActionClassifier.IsApproachByDistance(_lastDistance, distance, approachDistanceDeltaMeters, approachMaxDistanceMeters, out speed, elapsed))
        {
            RecordDerivedHumanProximityAction(ReportActionClassifier.Approach, nearest, distance, speed);
            _stationarySince = -1f;
        }
        else if (ReportActionClassifier.IsRetreatByDistance(_lastDistance, distance, approachDistanceDeltaMeters, approachMaxDistanceMeters, out speed, elapsed))
        {
            RecordDerivedHumanProximityAction(ReportActionClassifier.Retreat, nearest, distance, speed);
            _stationarySince = -1f;
        }
        else if (deriveWaitActions && distance <= approachMaxDistanceMeters && Mathf.Abs(distance - _lastDistance) <= waitDistanceJitterMeters)
        {
            if (_stationarySince < 0f)
                _stationarySince = now;
            if (now - _stationarySince >= waitMinSeconds)
                RecordDerivedHumanProximityAction(ReportActionClassifier.Wait, nearest, distance, 0f);
        }
        else
        {
            _stationarySince = -1f;
        }

        _lastNearestCatId = nearest.catId;
        _lastDistance = distance;
        _lastSampleAt = now;
    }

    void SampleCatState()
    {
        if (_lastCatSampleAt >= 0f && Time.time - _lastCatSampleAt < catSampleInterval)
            return;
        _lastCatSampleAt = Time.time;

        for (int i = 0; i < reportCats.Count; i++)
        {
            ReportCatBinding cat = reportCats[i];
            if (cat == null || cat.blackboard == null || string.IsNullOrWhiteSpace(cat.catId))
                continue;

            IntentMessage active = cat.blackboard.ResolveActiveMicroAction();
            string action = ReportActionClassifier.ToSnakeCase(active.Intent);
            if (string.IsNullOrEmpty(action))
                continue;
            int trust = TrustScore(cat.blackboard);
            string key = cat.catId.Trim().ToLowerInvariant();

            bool seen = _catState.TryGetValue(key, out CatStateSample last);
            bool actionChanged = !seen || !string.Equals(last.action, action, StringComparison.OrdinalIgnoreCase);
            bool trustChanged = !seen || Mathf.Abs(trust - last.trust) >= catTrustChangeThreshold;
            if (!actionChanged && !trustChanged)
                continue;

            int trustBefore = seen ? last.trust : trust;
            string trigger = actionChanged ? "action_changed" : "trust_changed";
            ReportEventParams paramsData = BuildCatParams(cat);
            paramsData.behavior_key = action;
            paramsData.motor_action = action;
            RecordCatAction(cat, action, trustBefore, trust, trigger, paramsData, BuildMeta("cat_state_sampler", trigger), active.CorrelationId);
            _catState[key] = new CatStateSample { action = action, trust = trust };
        }
    }

    void RecordDerivedHumanProximityAction(string action, ReportCatBinding targetCat, float distance, float speedMps)
    {
        if (Time.time - _lastDerivedActionAt < derivedActionCooldownSeconds
            && string.Equals(_lastDerivedAction, action, StringComparison.OrdinalIgnoreCase))
            return;

        var paramsData = BuildHumanParams(targetCat != null ? targetCat.Transform : null, targetCat != null ? targetCat.catId : "");
        paramsData.distance_to_nearest_cat_m = distance;
        paramsData.speed_mps = speedMps;
        paramsData.initiated_by = "derived_proximity";

        string derivation = "distance_delta";
        if (action == ReportActionClassifier.Approach)
            derivation = $"distance decreased by >= {approachDistanceDeltaMeters:F2}m";
        else if (action == ReportActionClassifier.Retreat)
            derivation = $"distance increased by >= {approachDistanceDeltaMeters:F2}m";
        else if (action == ReportActionClassifier.Wait)
            derivation = $"distance stable for >= {waitMinSeconds:F1}s";

        RecordHumanAction(action, paramsData, BuildMeta("proximity_sampler", derivation));
        _lastDerivedActionAt = Time.time;
        _lastDerivedAction = action;
    }

    ReportEventParams BuildHumanParams(Transform target, string targetId)
    {
        var data = new ReportEventParams
        {
            zone_id = CurrentZoneId(humanBlackboard),
            target_id = targetId ?? "",
            item_id = "",
            subtype = "",
            initiated_by = "",
            behavior_key = "",
            motor_action = "",
            social_act_kind = "",
            source_event_id = "",
            distance_to_player_m = -1f,
            distance_to_nearest_cat_m = -1f,
            facing_dot = -1f,
            confidence = -1f,
            speed_mps = -1f,
        };

        if (humanActor != null && target != null)
            data.distance_to_nearest_cat_m = Vector3.Distance(humanActor.position, target.position);

        return data;
    }

    ReportEventParams BuildCatParams(ReportCatBinding cat)
    {
        Transform catTransform = cat != null ? cat.Transform : null;
        var data = new ReportEventParams
        {
            zone_id = CurrentZoneId(cat != null ? cat.blackboard : null),
            target_id = "",
            item_id = "",
            subtype = "",
            initiated_by = "",
            behavior_key = "",
            motor_action = "",
            social_act_kind = "",
            source_event_id = "",
            distance_to_player_m = -1f,
            distance_to_nearest_cat_m = -1f,
            facing_dot = -1f,
            confidence = -1f,
            speed_mps = -1f,
        };

        if (humanActor != null && catTransform != null)
            data.distance_to_player_m = Vector3.Distance(catTransform.position, humanActor.position);

        return data;
    }

    ReportEventMeta BuildMeta(string sourceSystem, string derivation)
    {
        return new ReportEventMeta
        {
            source_system = sourceSystem ?? "",
            recorder = nameof(ReportSessionLogger),
            derivation = derivation ?? "",
            note = "",
        };
    }

    ReportSource BuildSource()
    {
        return new ReportSource
        {
            app = "mewi-unity",
            build = string.IsNullOrWhiteSpace(buildOverride) ? Application.version : buildOverride.Trim(),
            platform = Application.platform.ToString(),
            scene = SceneManager.GetActiveScene().name,
        };
    }

    ReportCatBinding FindNearestCat(out float distance)
    {
        distance = Mathf.Infinity;
        if (humanActor == null)
            return null;

        ReportCatBinding nearest = null;
        for (int i = 0; i < reportCats.Count; i++)
        {
            ReportCatBinding cat = reportCats[i];
            Transform target = cat != null ? cat.Transform : null;
            if (target == null || IsSameActor(humanActor, target))
                continue;

            float d = Vector3.Distance(humanActor.position, target.position);
            if (d < distance)
            {
                distance = d;
                nearest = cat;
            }
        }

        return nearest;
    }

    ReportCatBinding FindCatBinding(string catId)
    {
        if (string.IsNullOrWhiteSpace(catId))
            return null;

        string normalized = catId.Trim();
        for (int i = 0; i < reportCats.Count; i++)
        {
            ReportCatBinding cat = reportCats[i];
            if (cat == null) continue;
            if (string.Equals(cat.catId, normalized, StringComparison.OrdinalIgnoreCase))
                return cat;
        }
        return null;
    }

    ReportCatBinding FindCatBinding(Transform target)
    {
        if (target == null)
            return null;

        for (int i = 0; i < reportCats.Count; i++)
        {
            ReportCatBinding cat = reportCats[i];
            Transform catTransform = cat != null ? cat.Transform : null;
            if (catTransform == null)
                continue;

            if (target == catTransform || target.root == catTransform.root || target.IsChildOf(catTransform) || catTransform.IsChildOf(target))
                return cat;
        }

        return null;
    }

    float EventTime()
    {
        return _sessionActive ? Mathf.Max(0f, Time.time - _sessionStartedAt) : 0f;
    }

    string NextEventId()
    {
        return $"evt-{_nextEventIndex++:000000}";
    }

    string HumanActorId()
    {
        if (humanBlackboard != null && !string.IsNullOrWhiteSpace(humanBlackboard.CreatureId))
            return humanBlackboard.CreatureId.Trim();
        if (humanActor != null && !string.IsNullOrWhiteSpace(humanActor.name))
            return humanActor.name.Trim();
        return "player";
    }

    static bool IsSameActor(Transform a, Transform b)
    {
        if (a == null || b == null)
            return false;
        return a == b || a.root == b.root;
    }

    static string CurrentZoneId(CreatureBlackboard board)
    {
        if (board == null || board.activeZones == null || board.activeZones.Count == 0)
            return "";

        ZoneVolume zone = board.activeZones[board.activeZones.Count - 1];
        return zone != null ? zone.EffectiveZoneId : "";
    }

    static int TrustScore(CreatureBlackboard board)
    {
        if (board == null || board.mood == null)
            return 0;
        return Mathf.Clamp(Mathf.RoundToInt(board.mood.trust * 100f), 0, 100);
    }

    static float MissingIfInvalid(float value)
    {
        return float.IsNaN(value) || float.IsInfinity(value) ? -1f : value;
    }

    static string SafePathSegment(string value)
    {
        if (string.IsNullOrWhiteSpace(value))
            return "unknown";

        char[] chars = value.Trim().ToCharArray();
        for (int i = 0; i < chars.Length; i++)
        {
            char c = chars[i];
            if (!(char.IsLetterOrDigit(c) || c == '_' || c == '-' || c == '.'))
                chars[i] = '_';
        }
        return new string(chars);
    }

    static string SafeFileName(string value)
    {
        string safe = SafePathSegment(value);
        return safe.EndsWith(".json", StringComparison.OrdinalIgnoreCase)
            ? safe
            : $"{safe}.json";
    }

    void ResolveActorDefaults()
    {
        if (humanActor == null)
            humanActor = transform;
        if (humanBlackboard == null && humanActor != null)
            humanBlackboard = humanActor.GetComponent<CreatureBlackboard>();
        if (sender == null)
            sender = GetComponent<ReportSessionSender>();
        if (fileOutbox == null)
            fileOutbox = GetComponent<ReportSessionFileOutbox>();
    }
}
