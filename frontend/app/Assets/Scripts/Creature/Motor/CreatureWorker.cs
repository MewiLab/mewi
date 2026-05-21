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
                    if (!TryResolveTarget(intent.TargetKey, out Transform t, out rejectedReason))
                        return false;
                    destination = t.position;
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
                cmd = MotorCommand.Action(abilityIndex);
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

        string reason = "";
        if (_adapter != null && _adapter.LastNavigationCompletionReason != NavigationCompletionReason.None)
            reason = _adapter.LastNavigationCompletionReason.ToString();

        RecordStep(_activeIntent, "completed", reason, _activeStartedAt, Time.time);
        _hasActiveIntent = false;
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
        bool sawRejected = false;
        bool sawFailed = false;

        for (int i = 0; i < _currentPlanSteps.Count; i++)
        {
            string status = _currentPlanSteps[i].status;
            if (status == "completed") sawCompleted = true;
            else if (status == "failed") sawFailed = true;
            else if (status == "rejected") sawRejected = true;
        }

        if (sawFailed) return sawCompleted || sawRejected ? "completed_with_failures" : "failed";
        if (sawRejected) return sawCompleted ? "completed_with_rejections" : "rejected";
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
