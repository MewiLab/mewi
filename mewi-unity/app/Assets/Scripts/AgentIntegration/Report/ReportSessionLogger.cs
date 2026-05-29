using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using UnityEngine;
using UnityEngine.SceneManagement;

/// <summary>
/// Offline behavioral report logger for mewi-report raw JSON.
/// It records factual session events only; Python owns all report values.
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

    [Header("Session")]
    [SerializeField] bool startSessionOnStart = true;
    [SerializeField] bool saveLocalOnSessionEnd = true;
    [SerializeField] bool sendToBackendOnSessionEnd = false;
    [SerializeField] string sessionIdPrefix = "unity-session";
    [SerializeField] ReportSessionSender sender;

    [Header("Export")]
    [Tooltip("Optional absolute export folder. Empty uses Application.persistentDataPath/mewi_report_sessions.")]
    [SerializeField] string exportDirectory = "";
    [Tooltip("Optional file name override. Empty uses {session_id}.json.")]
    [SerializeField] string exportFileName = "";

    readonly List<ReportEvent> _events = new List<ReportEvent>();
    readonly List<ReportMultiCatEncounter> _encounters = new List<ReportMultiCatEncounter>();
    ReportSessionPayload _lastPayload;

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

    void Awake()
    {
        ResolveActorDefaults();
    }

    void Start()
    {
        if (startSessionOnStart)
            StartSession();
    }

    void Update()
    {
        if (!_sessionActive || !deriveProximityActions)
            return;

        SampleHumanProximity();
    }

    void OnApplicationQuit()
    {
        _isQuitting = true;
        if (_sessionActive)
            EndSession(saveLocalOnSessionEnd);
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
            duration_seconds = Mathf.Max(0f, Time.time - _sessionStartedAt),
            events = _events.ToArray(),
            multi_cat_encounters = _encounters.ToArray(),
        };
        _lastPayload = BuildPayload(session);

        _nextSessionIndex++;
        _sessionActive = false;
        _events.Clear();
        _encounters.Clear();

        if (exportAfterEnd)
            SaveToJsonFile(_lastPayload);

        if (sendToBackendOnSessionEnd && !_isQuitting && sender != null)
            sender.Send(_lastPayload);
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

        _events.Add(new ReportEvent
        {
            t = EventTime(),
            actor = "human",
            action = canonical,
            cat_id = "",
            trust_before = 0,
            trust_after = 0,
            trigger = "",
            @params = paramsData ?? BuildHumanParams(null, ""),
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

    public void RecordCatActionById(string catId, string action, int trustBefore, int trustAfter, string trigger)
    {
        ReportCatBinding cat = FindCatBinding(catId);
        RecordCatAction(cat, action, trustBefore, trustAfter, trigger, null, null);
    }

    public void RecordCatAction(ReportCatBinding cat, string action, int trustBefore, int trustAfter, string trigger, ReportEventParams paramsData, ReportEventMeta meta)
    {
        if (cat == null || string.IsNullOrWhiteSpace(cat.catId))
            return;

        if (!_sessionActive)
            StartSession();

        _events.Add(new ReportEvent
        {
            t = EventTime(),
            actor = "cat",
            action = ReportActionClassifier.ToSnakeCase(action),
            cat_id = cat.catId.Trim().ToLowerInvariant(),
            trust_before = Mathf.Clamp(trustBefore, 0, 100),
            trust_after = Mathf.Clamp(trustAfter, 0, 100),
            trigger = ReportActionClassifier.ToSnakeCase(trigger),
            @params = paramsData ?? BuildCatParams(cat),
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
            schema_version = "mewi.report.raw.v1",
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
            distance_to_player_m = -1f,
            distance_to_nearest_cat_m = -1f,
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
            distance_to_player_m = -1f,
            distance_to_nearest_cat_m = -1f,
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
    }
}
