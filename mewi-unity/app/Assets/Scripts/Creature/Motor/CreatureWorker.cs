using System;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// The mind-plan worker. Each tick:
///   1. If the body is busy with the previous command, do nothing.
///   2. Otherwise peek the next intent from the blackboard plan.
///   3. Translate it to a <see cref="MotorCommand"/> and hand it to
///      <see cref="MalbersAnimalAdapter.Apply"/>.
///   4. Pop the intent only after dispatch succeeds or a rejection is recorded.
///
/// Reports are accumulated as a nested per-plan result for the next websocket
/// tick; no HTTP callback is needed for runtime ordering.
/// MalbersAnimalAdapter is an implementation detail held privately here;
/// nothing else in the project should reference it.
/// </summary>
[RequireComponent(typeof(MalbersAnimalAdapter))]
public class CreatureWorker : MonoBehaviour
{
    CreatureBlackboard   _board;
    MalbersAnimalAdapter _adapter;

    [SerializeField] NamedTargetRegistry _targetRegistry;

    [Header("Debug")]
    [SerializeField] bool logWorkerDispatch = true;

    static readonly HashSet<string> _loggedMissingTargetKeys =
        new HashSet<string>(StringComparer.OrdinalIgnoreCase);

    readonly List<PlanStepExecutionReport> _currentPlanSteps = new List<PlanStepExecutionReport>();

    IntentMessage _activeIntent;
    float _activeStartedAt;
    float _planStartedAt;
    bool _hasActiveIntent;
    string _planRequestId = "";
    string _planId = "";
    bool _warnedUninitialized;

    public bool IsBusy => _adapter != null && _adapter.IsBusy;
    public string DebugState
    {
        get
        {
            if (_adapter == null) return "workerAdapter=null";
            string active = _hasActiveIntent ? DescribeIntent(_activeIntent) : "none";
            return $"workerAdapterBusy={_adapter.IsBusy} active={active} adapter=({_adapter.BuildNavigationDebug()})";
        }
    }

    public void Init(CreatureBlackboard board)
    {
        _board   = board;
        _adapter = GetComponent<MalbersAnimalAdapter>();

        if (_adapter == null)
        {
            Debug.LogError("[CreatureWorker] Missing MalbersAnimalAdapter on the same GameObject.");
            return;
        }

        _adapter.Init();

        if (_targetRegistry == null)
            _targetRegistry = FindFirstObjectByType<NamedTargetRegistry>();
    }

    public void Tick()
    {
        if (_board == null || _adapter == null)
        {
            if (!_warnedUninitialized)
            {
                Debug.LogWarning("[CreatureWorker] Tick skipped before Init completed; attach CreatureController or call Init(board).");
                _warnedUninitialized = true;
            }
            return;
        }

        if (_adapter.IsBusy) return;
        CompleteActiveIntentIfReady();

        if (!_board.TryPeekMindIntent(out IntentMessage intent))
        {
            CompletePlanIfReady();
            return;
        }

        BeginPlanIfNeeded(intent);

        if (!TryBuildCommand(intent, out MotorCommand cmd, out string rejectedReason))
        {
            if (logWorkerDispatch)
                Debug.LogWarning($"[CreatureWorker] rejected {DescribeIntent(intent)}: {rejectedReason}");
            RecordStep(intent, "rejected", rejectedReason, Time.time, Time.time);
            _board.TryPopMindIntent(out _);
            CompletePlanIfReady();
            return;
        }

        if (!_adapter.Apply(cmd))
        {
            if (logWorkerDispatch)
                Debug.LogWarning($"[CreatureWorker] adapter refused {DescribeIntent(intent)} as {cmd.Kind}");
            RecordStep(intent, "rejected", "adapter_refused", Time.time, Time.time);
            _board.TryPopMindIntent(out _);
            CompletePlanIfReady();
            return;
        }

        if (logWorkerDispatch)
            Debug.Log($"[CreatureWorker] dispatched {DescribeIntent(intent)} as {cmd.Kind}");

        _activeIntent = intent;
        _activeStartedAt = Time.time;
        _hasActiveIntent = true;
        _board.TryPopMindIntent(out _);

        if (IsValidatableIntent(intent.Intent))
        {
            GoalEventBus.Declare(
                CreatureIdForBus(),
                intent.Intent,
                intent.TargetKey ?? "",
                _activeStartedAt);
        }

        CompleteActiveIntentIfReady();
        CompletePlanIfReady();
    }

    bool TryBuildCommand(IntentMessage intent, out MotorCommand cmd, out string rejectedReason)
    {
        cmd = default;
        rejectedReason = "";

        switch (intent.Intent)
        {
            case "idle":        cmd = MotorCommand.Idle(); return true;
            case "stop":
            case "stop_moving": cmd = MotorCommand.Stop(); return true;
            case "wander":      cmd = MotorCommand.Wander(); return true;
            case "flee":        cmd = MotorCommand.Flee(intent.DirectionHint); return true;
            case "die":         cmd = MotorCommand.Death(); return true;

            case "go_to":
                Vector3 destination = intent.DirectionHint;
                if (!string.IsNullOrWhiteSpace(intent.TargetKey))
                {
                    if (!TryResolveTargetPosition(intent.TargetKey, out destination, out _, out rejectedReason))
                        return false;
                }
                else if (destination == Vector3.zero)
                {
                    if (logWorkerDispatch)
                    {
                        Debug.LogWarning(
                            "[CreatureWorker] go_to arrived without a target or destination; " +
                            "falling back to wander. For directed movement, send a visible target id.");
                    }
                    cmd = MotorCommand.Wander();
                    return true;
                }
                cmd = MotorCommand.GoTo(destination);
                return true;

            case "follow":
            case "investigate":
                Transform target = _board.followTarget;
                if (!string.IsNullOrWhiteSpace(intent.TargetKey))
                {
                    if (!TryResolveTarget(intent.TargetKey, out target, out rejectedReason))
                        return false;
                    _board.followTarget = target;
                }
                if (target == null && intent.Intent == "investigate")
                    target = _board.closestPlayer;
                if (target == null)
                {
                    rejectedReason = $"missing_target:{intent.Intent}";
                    return false;
                }
                cmd = MotorCommand.Follow(target);
                return true;

            case "flinch":
            case "scratch":
            case "look_around":
            case "nod_head":
            case "eat":
            case "drink":
            case "sit":
            case "lie":
            case "sleep":
            case "groom":
            case "smell":
            case "alert":
            case "vocalize":
                if (!_adapter.TryGetAbilityIndex(intent.Intent, out int abilityIndex))
                {
                    rejectedReason = $"unmapped_action:{intent.Intent}";
                    return false;
                }
                cmd = MotorCommand.Action(intent.Intent, abilityIndex);
                return true;

            default:
                rejectedReason = $"unknown_intent:{intent.Intent}";
                return false;
        }
    }

    bool TryResolveTarget(string key, out Transform target, out string rejectedReason)
    {
        target = null;
        rejectedReason = "";
        if (string.IsNullOrWhiteSpace(key))
        {
            rejectedReason = "missing_target_key";
            return false;
        }

        if (_board != null && _board.TryResolveRecentTarget(key, out target))
            return true;

        if (_targetRegistry == null)
            _targetRegistry = FindFirstObjectByType<NamedTargetRegistry>();

        if (_targetRegistry != null && _targetRegistry.TryResolve(key, out target))
            return true;

        GameObject found = GameObject.Find(key.Trim());
        if (found != null)
        {
            target = found.transform;
            return true;
        }

        rejectedReason = $"unknown_target:{key}";
        LogUnknownTargetOnce(key);
        return false;
    }

    bool TryResolveTargetPosition(string key, out Vector3 position, out Transform target, out string rejectedReason)
    {
        position = Vector3.zero;
        target = null;
        rejectedReason = "";

        if (_board != null && _board.TryResolveRecentTargetPosition(key, out position, out target))
            return true;

        if (_targetRegistry == null)
            _targetRegistry = FindFirstObjectByType<NamedTargetRegistry>();

        if (_targetRegistry != null && _targetRegistry.TryResolvePosition(key, out position, out target))
            return true;

        if (!TryResolveTarget(key, out target, out rejectedReason))
            return false;

        position = ResolveTargetPosition(target);
        return true;
    }

    static Vector3 ResolveTargetPosition(Transform target)
    {
        if (target == null) return Vector3.zero;

        SmartObject smartObject = target.GetComponent<SmartObject>()
            ?? target.GetComponentInParent<SmartObject>()
            ?? target.GetComponentInChildren<SmartObject>();

        return smartObject != null ? smartObject.Position : target.position;
    }

    void BeginPlanIfNeeded(IntentMessage intent)
    {
        if (_currentPlanSteps.Count > 0 || _hasActiveIntent)
            return;

        _planRequestId = intent.RequestId ?? "";
        _planId = string.IsNullOrWhiteSpace(_planRequestId)
            ? $"{(_board != null ? _board.CreatureId : name)}:{Time.frameCount}"
            : _planRequestId;
        _planStartedAt = Time.time;
    }

    void CompleteActiveIntentIfReady()
    {
        if (!_hasActiveIntent || (_adapter != null && _adapter.IsBusy))
            return;

        string adapterReason = "";
        NavigationCompletionReason navReason = NavigationCompletionReason.None;
        if (_adapter != null)
        {
            adapterReason = _adapter.LastCommandCompletionReason ?? "";
            navReason = _adapter.LastNavigationCompletionReason;
        }

        SelfConfirmIfGeometric(_activeIntent, navReason);

        string status;
        string reason;
        if (IsValidatableIntent(_activeIntent.Intent))
        {
            bool confirmed = GoalEventBus.TryConsume(
                CreatureIdForBus(),
                _activeIntent.Intent,
                _activeIntent.TargetKey ?? "",
                _activeStartedAt,
                out string confirmedReason);

            if (!confirmed && _activeIntent.Intent == "go_to" && TryRecoverGoTo(_activeIntent, navReason))
            {
                confirmed = GoalEventBus.TryConsume(
                    CreatureIdForBus(),
                    _activeIntent.Intent,
                    _activeIntent.TargetKey ?? "",
                    _activeStartedAt,
                    out confirmedReason);
            }

            if (confirmed)
            {
                bool isRecovered = !string.IsNullOrEmpty(confirmedReason)
                    && confirmedReason.StartsWith("recovered_via_teleport", StringComparison.Ordinal);
                status = isRecovered ? "recovered" : "completed";
                reason = string.IsNullOrWhiteSpace(confirmedReason) ? adapterReason : confirmedReason;
            }
            else
            {
                status = "failed";
                reason = ComposeFailureReason("not_confirmed_by_world", adapterReason, navReason);
            }
        }
        else
        {
            status = "completed";
            reason = !string.IsNullOrWhiteSpace(adapterReason)
                ? adapterReason
                : (navReason != NavigationCompletionReason.None ? navReason.ToString() : "");
        }

        RecordStep(_activeIntent, status, reason, _activeStartedAt, Time.time);
        _hasActiveIntent = false;
    }

    /// <summary>
    /// For purely geometric intents (currently <c>go_to</c>) the cat itself
    /// confirms arrival when the watchdog reports an honest arrival. Warps,
    /// failures, and cancels do not produce a confirm — so TryConsume will
    /// miss and the step will report as <c>failed</c> downstream.
    /// </summary>
    void SelfConfirmIfGeometric(IntentMessage intent, NavigationCompletionReason navReason)
    {
        if (intent.Intent != "go_to") return;
        if (navReason != NavigationCompletionReason.Arrived &&
            navReason != NavigationCompletionReason.ArrivedAfterRepath)
            return;

        GoalEventBus.Confirm(
            CreatureIdForBus(),
            "go_to",
            intent.TargetKey ?? "",
            Time.time,
            navReason.ToString());
    }

    /// <summary>
    /// Last-resort recovery for <c>go_to</c>: when the world refused to confirm
    /// natural arrival, resolve the target position and ask the adapter to
    /// teleport the cat there. Fires a <see cref="GoalEventBus.Confirm"/> with a
    /// <c>recovered_via_teleport:*</c> reason so the second TryConsume picks it
    /// up and the step is reported as <c>recovered</c> rather than <c>failed</c>.
    /// </summary>
    bool TryRecoverGoTo(IntentMessage intent, NavigationCompletionReason navReason)
    {
        if (_adapter == null) return false;
        if (string.IsNullOrWhiteSpace(intent.TargetKey)) return false;

        if (!TryResolveTargetPosition(intent.TargetKey, out Vector3 destination, out _, out _))
            return false;

        string warpReason;
        if (navReason == NavigationCompletionReason.WarpedToNavMesh ||
            navReason == NavigationCompletionReason.WarpedRaw)
        {
            warpReason = navReason.ToString();
        }
        else
        {
            if (!_adapter.TryWarpTo(destination, out warpReason))
                return false;
        }

        if (logWorkerDispatch)
            Debug.Log($"[CreatureWorker] recovery teleport for go_to target={intent.TargetKey} reason={warpReason}");

        GoalEventBus.Confirm(
            CreatureIdForBus(),
            "go_to",
            intent.TargetKey,
            Time.time,
            "recovered_via_teleport:" + warpReason);
        return true;
    }

    static bool IsValidatableIntent(string intentName)
    {
        if (string.IsNullOrWhiteSpace(intentName)) return false;
        switch (intentName)
        {
            case "go_to":
            case "eat":
                return true;
            default:
                return false;
        }
    }

    static string ComposeFailureReason(string primary, string adapterReason, NavigationCompletionReason navReason)
    {
        if (!string.IsNullOrWhiteSpace(adapterReason))
            return $"{primary}:{adapterReason}";
        if (navReason != NavigationCompletionReason.None)
            return $"{primary}:{navReason}";
        return primary;
    }

    string CreatureIdForBus()
    {
        return _board != null ? _board.CreatureId : name;
    }

    void CompletePlanIfReady()
    {
        if (_hasActiveIntent || (_adapter != null && _adapter.IsBusy)) return;
        if (_board != null && _board.HasMindPlan) return;
        if (_currentPlanSteps.Count == 0) return;

        var report = new PlanExecutionReport
        {
            agent_id    = _board != null ? _board.CreatureId : name,
            requestId   = _planRequestId,
            planId      = _planId,
            status      = BuildPlanStatus(),
            startedAt   = _planStartedAt,
            completedAt = Time.time,
            steps       = _currentPlanSteps.ToArray(),
        };

        _board.EnqueuePlanExecutionReport(report);
        _currentPlanSteps.Clear();
        _planRequestId = "";
        _planId = "";
    }

    void RecordStep(IntentMessage intent, string status, string reason, float startedAt, float endedAt)
    {
        _currentPlanSteps.Add(new PlanStepExecutionReport
        {
            commandId = intent.CommandId ?? "",
            requestId = intent.RequestId ?? "",
            action    = intent.Intent ?? "",
            target    = intent.TargetKey ?? "",
            status    = status ?? "",
            reason    = reason ?? "",
            startedAt = startedAt,
            endedAt   = endedAt,
        });
    }

    static string DescribeIntent(IntentMessage intent)
    {
        string target = string.IsNullOrWhiteSpace(intent.TargetKey) ? "" : $" target={intent.TargetKey}";
        string command = string.IsNullOrWhiteSpace(intent.CommandId) ? "" : $" command={intent.CommandId}";
        return $"{intent.Intent}{target}{command}";
    }

    string BuildPlanStatus()
    {
        bool sawCompleted = false;
        bool sawRecovered = false;
        bool sawRejected = false;
        bool sawFailed = false;

        for (int i = 0; i < _currentPlanSteps.Count; i++)
        {
            string status = _currentPlanSteps[i].status;
            if (status == "completed") sawCompleted = true;
            else if (status == "recovered") sawRecovered = true;
            else if (status == "failed") sawFailed = true;
            else if (status == "rejected") sawRejected = true;
        }

        if (sawFailed) return (sawCompleted || sawRecovered || sawRejected) ? "completed_with_failures" : "failed";
        if (sawRejected) return (sawCompleted || sawRecovered) ? "completed_with_rejections" : "rejected";
        if (sawRecovered) return "completed_with_recoveries";
        return "completed";
    }

    void LogUnknownTargetOnce(string key)
    {
        string normalized = string.IsNullOrWhiteSpace(key) ? "(empty)" : key.Trim();
        if (!_loggedMissingTargetKeys.Add(normalized))
            return;

        var known = new List<string>();
        if (_targetRegistry == null)
            _targetRegistry = FindFirstObjectByType<NamedTargetRegistry>();

        if (_targetRegistry != null)
        {
            foreach (string knownKey in _targetRegistry.KnownKeys)
            {
                if (known.Count >= 10) break;
                known.Add(knownKey);
            }
        }

        string knownText = known.Count > 0 ? string.Join(", ", known) : "(none registered)";
        string creatureId = _board != null ? _board.CreatureId : name;
        Debug.LogError($"[CreatureWorker] Unknown target '{normalized}' for creature '{creatureId}'. Known target keys: {knownText}");
    }
}
