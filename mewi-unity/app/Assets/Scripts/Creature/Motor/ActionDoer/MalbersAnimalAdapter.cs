using UnityEngine;
using UnityEngine.AI;
using MalbersAnimations;
using MalbersAnimations.Controller;
using MalbersAnimations.Controller.AI;

/// <summary>
/// The only file in the project that talks to Malbers.
///
/// Single entry point: <see cref="Apply"/>. The worker hands the body one
/// <see cref="MotorCommand"/> at a time; this class translates it into
/// MAnimal / MAnimalAIControl calls, then runs to completion on its own
/// (modes finish via OnModeEnd; navigation finishes via OnArrived / arrival
/// distance check).
///
/// <see cref="IsBusy"/> is true while a command is still being executed; the
/// worker checks that before popping the next intent.
/// </summary>
public class MalbersAnimalAdapter : MonoBehaviour
{
    [Header("Malbers References")]
    public MAnimal          animal;
    public MAnimalAIControl aiControl;

    [Header("Mode Setup")]
    [Tooltip("ModeID asset for the 'Action' mode. Optional: Malbers Action mode is usually ID 4.")]
    public ModeID actionMode;
    [Tooltip("Fallback Action mode ID used when no ModeID asset is assigned. Malbers default Action mode is 4.")]
    public int actionModeId = 4;

    [Header("Action Ability Indices (match MAnimal Action mode list order)")]
    public int startleAbilityIndex   = 1;
    public int scratchAbilityIndex   = 0;
    public int lookAroundAbilityIndex = 0;
    public int nodHeadAbilityIndex   = 0;
    public int eatAbilityIndex       = 2;
    public int drinkAbilityIndex     = 7;
    public int sitAbilityIndex       = 8;
    public int lieAbilityIndex       = 11;
    public int sleepAbilityIndex     = 6;
    public int groomAbilityIndex     = 0;
    public int smellAbilityIndex     = 16;
    public int alertAbilityIndex     = 0;
    public int vocalizeAbilityIndex  = 20;

    [Header("Action Execution")]
    public ActionExecutionConfig actionExecutionConfig = new ActionExecutionConfig();

    [Header("Simple Climb")]
    [Tooltip("Fallback climb time when a climb point does not provide one.")]
    public float defaultClimbSeconds = 3f;
    [Tooltip("Fallback input axis fed into Malbers Climb. Vector3.forward means climb up.")]
    public Vector3 defaultClimbInputAxis = Vector3.forward;
    [Tooltip("Rotate the cat to the climb point transform before activating Climb.")]
    public bool snapToClimbPointRotation = true;

    [Header("Stances")]
    public StanceID defaultStance;
    public StanceID sneakStance;

    [Header("Speed indices (Ground SpeedSet)")]
    [Tooltip("Walk = 1, Trot = 2, Run = 3 — match your MSpeedSet list order")]
    public int walkSpeedIndex = 1;
    public int trotSpeedIndex = 2;
    public int runSpeedIndex  = 3;

    [Header("State References")]
    public StateID deathState;

    [Header("Wander / Flee primitives")]
    public float wanderRadius   = 10f;
    public float fleeDistance   = 15f;

    [Header("Navigation")]
    public float navMeshDestinationSampleRadius = 2f;
    public float navMeshStartSampleRadius       = 2f;
    public bool  useManualNavMeshFallback       = true;
    public float manualNavArrivalDistance       = 0.65f;
    public float manualNavCornerDistance        = 0.35f;
    public float manualNavRepathInterval        = 0.5f;

    [Header("Route Safety")]
    [Tooltip("Reject complete NavMesh paths that are too close to edges or fail optional ground probes.")]
    public bool rejectRiskyNavMeshPaths = true;
    [Tooltip("Shared safety checks used before the cat commits to a NavMesh route.")]
    public NavigationSafetyConfig navigationSafety = new NavigationSafetyConfig();
    [Tooltip("When the direct route is risky, search for a safe intermediate NavMesh waypoint.")]
    public bool useSafeDetours = true;
    public int maxSafeDetourHops = 2;
    public float safeDetourSearchRadius = 7f;
    public float safeDetourRadiusStep = 1.5f;
    public int safeDetourSamplesPerRing = 16;

    [Header("Facing")]
    [Tooltip("Degrees per second used by face_sun / face_target commands.")]
    public float faceTargetTurnSpeedDegrees = 360f;
    [Tooltip("Horizontal angle considered close enough to finish a facing command.")]
    public float faceTargetAngleTolerance = 3f;
    [Tooltip("Safety timeout so a facing command cannot block the plan forever.")]
    public float faceTargetMaxSeconds = 1.5f;

    [Tooltip("Temporary reliability mode: skip pathfinding for go_to and warp directly to the requested target.")]
    public bool teleportGoToImmediately = false;

    [Tooltip("Backup plan: if realistic go_to cannot find a complete walk path, use the old direct teleport instead of waiting for watchdog timeout.")]
    public bool teleportUnreachableGoToBackup = true;

    [Header("Recovery")]
    public NavigationRecoveryConfig recoveryConfig = new NavigationRecoveryConfig();

    [Header("Debug")]
    public bool logIntentProof = true;

    public int  ActionModeId => actionMode != null ? actionMode.ID : actionModeId;
    public bool IsBusy => _climbInFlight || _faceTargetInFlight || _actionInFlight || _actionWatchdog.IsBusy || (_hasActiveNavigationDestination && !_hasArrived);

    public bool TryGetAbilityIndex(string intent, out int abilityIndex)
    {
        switch (intent)
        {
            case "flinch":
            case "stun":
            case "startle":     abilityIndex = FirstPositive(startleAbilityIndex, 1); return abilityIndex > 0;
            case "scratch":     abilityIndex = FirstPositive(scratchAbilityIndex, 10); return abilityIndex > 0;
            case "dig":         abilityIndex = 10; return true;
            case "look_around": abilityIndex = FirstPositive(lookAroundAbilityIndex, 19); return abilityIndex > 0;
            case "nod_head":
            case "yes":         abilityIndex = FirstPositive(nodHeadAbilityIndex, 107); return abilityIndex > 0;
            case "no":          abilityIndex = 108; return true;
            case "eat":         abilityIndex = eatAbilityIndex; return abilityIndex > 0;
            case "drink":       abilityIndex = drinkAbilityIndex; return abilityIndex > 0;
            case "sit":         abilityIndex = sitAbilityIndex; return abilityIndex > 0;
            case "lie":         abilityIndex = lieAbilityIndex; return abilityIndex > 0;
            case "sleep":       abilityIndex = sleepAbilityIndex; return abilityIndex > 0;
            case "groom":       abilityIndex = FirstPositive(groomAbilityIndex, 29); return abilityIndex > 0;
            case "smell":       abilityIndex = smellAbilityIndex; return abilityIndex > 0;
            case "alert":       abilityIndex = FirstPositive(alertAbilityIndex, 19); return abilityIndex > 0;
            case "vocalize":
            case "meow":        abilityIndex = FirstPositive(vocalizeAbilityIndex, 20); return abilityIndex > 0;
            case "crawl":       abilityIndex = 9; return true;
            case "open_chest":  abilityIndex = 18; return true;
            case "shake":       abilityIndex = 26; return true;
            case "push":        abilityIndex = 13; return true;
            case "poop":        abilityIndex = 24; return true;
            case "pee":         abilityIndex = 25; return true;
        }
        abilityIndex = 0;
        return abilityIndex > 0;
    }

    static int FirstPositive(int preferred, int fallback)
    {
        return preferred > 0 ? preferred : fallback;
    }

    bool _hasActiveNavigationDestination;
    Vector3 _activeNavigationDestination;
    bool _usingManualNavigation;
    Vector3 _manualNavigationDestination;
    Vector3 _manualNavigationCorner;
    Vector3 _manualNavigationDirection;
    NavMeshPath _manualPath;
    NavMeshPath _navigationValidationPath;
    int _manualCornerIndex;
    float _manualRepathTimer;
    bool _hasQueuedNavigationDestination;
    Vector3 _queuedNavigationDestination;
    int _queuedNavigationHop;

    bool _hasArrived;
    bool _actionInFlight;
    bool _climbInFlight;
    bool _faceTargetInFlight;
    bool _climbStateStarted;
    float _climbStartedAt;
    float _climbDuration;
    float _faceTargetStartedAt;
    float _nextClimbActivateRetryAt;
    Vector3 _climbInputAxis;
    Vector3 _faceTargetPosition;
    State _activeClimbState;
    Transform _activeFollowTarget;

    readonly NavigationWatchdog _navWatchdog = new NavigationWatchdog();
    readonly ActionWatchdog _actionWatchdog = new ActionWatchdog();
    public NavigationCompletionReason LastNavigationCompletionReason { get; private set; }
        = NavigationCompletionReason.None;
    public ActionCompletionReason LastActionCompletionReason { get; private set; }
        = ActionCompletionReason.None;
    public string LastCommandCompletionReason { get; private set; } = "";

    // ═══════════════════════════════════════════════
    //  INIT
    // ═══════════════════════════════════════════════

    public void Init()
    {
        if (animal == null)
            animal = GetComponent<MAnimal>() ?? GetComponentInParent<MAnimal>() ?? GetComponentInChildren<MAnimal>();

        if (aiControl == null)
            aiControl = GetComponent<MAnimalAIControl>()
                     ?? GetComponentInParent<MAnimalAIControl>()
                     ?? GetComponentInChildren<MAnimalAIControl>();

#if UNITY_EDITOR
        if (aiControl == null)
        {
            aiControl = FindFirstObjectByType<MAnimalAIControl>();
            if (aiControl != null)
                Debug.LogWarning($"[MalbersAdapter] MAnimalAIControl found via scene search on '{aiControl.gameObject.name}'. Move the adapter there or assign the field in the Inspector.");
        }
#endif

        if (animal == null)    { Debug.LogError("[MalbersAdapter] No MAnimal found! Place the adapter on the animal root or assign it in the Inspector."); return; }
        if (aiControl == null) { Debug.LogError("[MalbersAdapter] No MAnimalAIControl found! Add MAnimalAIControl manually or use the Malbers _AI prefab variant."); return; }

        if (aiControl.animal == null) aiControl.animal = animal;

        _navWatchdog.Configure(recoveryConfig);
        _actionWatchdog.Configure(actionExecutionConfig);

        var navAgent = aiControl.Agent;
        if (navAgent != null && navAgent.transform == animal.transform)
            Debug.LogError(
                "[MalbersAdapter] NavMeshAgent is on the MAnimal root — this will FREEZE the cat in place. " +
                "Move the NavMeshAgent onto a child GameObject and reassign MAnimalAIControl.Agent.");

        // MAnimalBrain hardcodes `enabled = true`; destroy so it doesn't fight us.
        var malbersBrain = GetComponentInParent<MAnimalBrain>();
        if (malbersBrain != null)
        {
            Debug.Log("[MalbersAdapter] Destroying MAnimalBrain — adapter has full AI control.");
            Destroy(malbersBrain);
        }

        animal.PreInput -= OnPreInput;
        animal.PreInput += OnPreInput;
        aiControl.OnArrived.RemoveListener(OnAiArrived);
        aiControl.OnTargetPositionArrived.RemoveListener(OnAiPositionArrived);
        animal.OnModeStart.RemoveListener(OnAnimalModeStarted);
        animal.OnModeEnd.RemoveListener(OnAnimalModeEnded);
        aiControl.OnArrived.AddListener(OnAiArrived);
        aiControl.OnTargetPositionArrived.AddListener(OnAiPositionArrived);
        animal.OnModeStart.AddListener(OnAnimalModeStarted);
        animal.OnModeEnd.AddListener(OnAnimalModeEnded);
    }

    void OnDisable()
    {
        if (aiControl != null)
        {
            aiControl.OnArrived.RemoveListener(OnAiArrived);
            aiControl.OnTargetPositionArrived.RemoveListener(OnAiPositionArrived);
        }

        if (animal != null)
        {
            animal.PreInput -= OnPreInput;
            animal.OnModeStart.RemoveListener(OnAnimalModeStarted);
            animal.OnModeEnd.RemoveListener(OnAnimalModeEnded);
        }
    }

    void OnAiArrived(Transform _)
    {
        _hasArrived = true;
        NotifyWatchdogArrived();
    }

    void OnAiPositionArrived(Vector3 position)
    {
        if (!_hasActiveNavigationDestination) return;
        if (HorizontalDistance(position, _activeNavigationDestination) <= manualNavArrivalDistance)
        {
            _hasArrived = true;
            NotifyWatchdogArrived();
        }
    }

    void OnPreInput(MAnimal _)
    {
        UpdateSimpleClimb();
        UpdateFaceTarget();
        UpdateManualNavigation();
        TickNavigationWatchdog();
    }

    void Update()
    {
        TickActionWatchdog();
    }

    void NotifyWatchdogArrived()
    {
        if (!_navWatchdog.IsActive) return;

        if (_hasQueuedNavigationDestination)
        {
            Vector3 nextDestination = _queuedNavigationDestination;
            int nextHop = _queuedNavigationHop;
            ClearQueuedNavigationDestination();

            if (logIntentProof)
                Debug.Log($"[MalbersAdapter] Safe detour reached; continuing to final destination {nextDestination}.");

            NavigateTo_realistic(nextDestination, nextHop);
            return;
        }

        _navWatchdog.NotifyArrivedNaturally();
        LastNavigationCompletionReason = _navWatchdog.CompletionReason;
        LastCommandCompletionReason = LastNavigationCompletionReason.ToString();
    }

    void OnAnimalModeStarted(int modeID, int abilityIndex)
    {
        if (modeID != ActionModeId) return;
        _actionWatchdog.NotifyModeStarted(abilityIndex, Time.time);
    }

    void OnAnimalModeEnded(int modeID, int abilityIndex)
    {
        if (modeID != ActionModeId) return;
        if (!_actionWatchdog.NotifyModeEnded(abilityIndex, Time.time)) return;

        _actionInFlight = false;
        LastActionCompletionReason = _actionWatchdog.CompletionReason;
        LastCommandCompletionReason = LastActionCompletionReason.ToString();

        // MAnimalAIControl.OnModeEnd re-enables the agent the moment a mode ends.
        // Only stop if nothing newer was issued; a fresh navigation queued during
        // mode-end is the intended next step and must not be cancelled.
        if (!_hasActiveNavigationDestination && !_usingManualNavigation)
            StopNavigation(true);
    }

    // ═══════════════════════════════════════════════
    //  SINGLE ENTRY POINT
    // ═══════════════════════════════════════════════

    public bool Apply(in MotorCommand cmd)
    {
        if (animal == null || aiControl == null) return false;

        LastNavigationCompletionReason = NavigationCompletionReason.None;
        LastActionCompletionReason = ActionCompletionReason.None;
        LastCommandCompletionReason = "";

        switch (cmd.Kind)
        {
            case MotorCommandKind.Idle:    return ExecuteIdle();
            case MotorCommandKind.Stop:    Stop();                              return true;
            case MotorCommandKind.Wander:  return ExecuteWander();
            case MotorCommandKind.Flee:    return ExecuteFlee(cmd.Destination);
            case MotorCommandKind.GoTo:    return ExecuteGoTo(cmd.Destination);
            case MotorCommandKind.Follow:  return ExecuteFollow(cmd.Target);
            case MotorCommandKind.FaceTarget: return ExecuteFaceTarget(cmd.Destination);
            case MotorCommandKind.Action:  return ExecuteAction(cmd.ActionIntent, cmd.AbilityIndex);
            case MotorCommandKind.Climb: return ExecuteClimb(cmd.Target, cmd.Duration, cmd.InputAxis);
            case MotorCommandKind.Death:   return ExecuteDeath();
        }
        return false;
    }

    // ═══════════════════════════════════════════════
    //  PRIMITIVES
    // ═══════════════════════════════════════════════

    bool ExecuteIdle()
    {
        Stop();
        if (defaultStance != null) animal.Stance = defaultStance;
        animal.Speed_CurrentIndex_Set(walkSpeedIndex);
        animal.Sprint = false;
        return true;
    }

    bool ExecuteWander()
    {
        if (defaultStance != null) animal.Stance = defaultStance;
        animal.Speed_CurrentIndex_Set(trotSpeedIndex);
        animal.Sprint = false;

        Vector3 origin = AnimalPosition;
        Vector3 candidate = Random.insideUnitSphere * wanderRadius + origin;
        candidate.y = origin.y;

        if (NavMesh.SamplePosition(candidate, out NavMeshHit hit, wanderRadius, NavMesh.AllAreas))
            return NavigateTo(hit.position);

        Debug.LogWarning($"[MalbersAdapter] Wander NavMesh.SamplePosition failed near {origin} radius={wanderRadius}. Falling back to raw destination.");
        return NavigateTo(candidate);
    }

    bool ExecuteFlee(Vector3 threatPosition)
    {
        animal.Speed_CurrentIndex_Set(runSpeedIndex);
        animal.Sprint = true;

        Vector3 origin = AnimalPosition;
        Vector3 fleeDir = (threatPosition == Vector3.zero)
            ? -animal.transform.forward
            : (origin - threatPosition).normalized;

        Vector3 fleeTarget = origin + fleeDir * fleeDistance;

        if (NavMesh.SamplePosition(fleeTarget, out NavMeshHit hit, fleeDistance, NavMesh.AllAreas))
            return NavigateTo(hit.position);

        Debug.LogWarning($"[MalbersAdapter] Flee NavMesh.SamplePosition failed near {fleeTarget} radius={fleeDistance}. Falling back to raw destination.");
        return NavigateTo(fleeTarget);
    }

    bool ExecuteGoTo(Vector3 destination)
    {
        if (defaultStance != null) animal.Stance = defaultStance;
        animal.Speed_CurrentIndex_Set(trotSpeedIndex);
        animal.Sprint = false;

        if (teleportGoToImmediately)
        {
            if (logIntentProof)
                Debug.LogWarning($"[MalbersAdapter] go_to teleport mode active; warping directly to {destination}.");

            return TryWarpTo(destination, out _);
        }

        return NavigateTo(destination);
    }

    bool ExecuteFollow(Transform target)
    {
        if (target == null) return false;
        PrepareForMovementCommand();
        if (defaultStance != null) animal.Stance = defaultStance;
        animal.Speed_CurrentIndex_Set(trotSpeedIndex);
        animal.Sprint = false;

        StopManualNavigation(false);
        _activeFollowTarget = target;
        _activeNavigationDestination = target.position;
        _hasActiveNavigationDestination = true;
        _hasArrived = false;
        _navWatchdog.Begin(_activeNavigationDestination, AnimalPosition, Time.time);
        aiControl.SetTarget(target, true);

        if (logIntentProof)
            Debug.Log($"[MalbersAdapter] SetTarget({target.name}). MAnimalAIControl will pathfind.");
        return true;
    }

    bool ExecuteFaceTarget(Vector3 targetPosition)
    {
        CancelSimpleClimb("face_target_started");
        CancelActionExecution();
        ClearLingeringActionMode("before face target");
        StopNavigation(true);

        if (defaultStance != null) animal.Stance = defaultStance;
        animal.Sprint = false;
        animal.StopMoving();
        animal.SetInputAxis(Vector3.zero);

        _faceTargetPosition = targetPosition;
        _faceTargetStartedAt = Time.time;
        _faceTargetInFlight = true;

        if (!UpdateFaceTargetRotation(0f, out float angle))
        {
            CompleteFaceTarget("FaceTargetNoDirection");
            return true;
        }

        if (angle <= faceTargetAngleTolerance)
        {
            CompleteFaceTarget("FaceTargetAlreadyAligned");
            return true;
        }

        LastCommandCompletionReason = "FaceTargetStarted";
        if (logIntentProof)
            Debug.Log($"[MalbersAdapter] FaceTarget started target={targetPosition}.");
        return true;
    }

    bool ExecuteAction(string intent, int abilityIndex)
    {
        int modeId = ActionModeId;
        if (modeId <= 0 || abilityIndex <= 0)
        {
            Debug.LogWarning($"[MalbersAdapter] Action rejected: modeId={modeId} abilityIndex={abilityIndex}");
            return false;
        }

        StopNavigation(true);
        ClearLingeringActionMode("before action");
        _actionWatchdog.Configure(actionExecutionConfig);
        _actionWatchdog.Begin(intent, abilityIndex, Time.time);

        _actionInFlight = true;
        bool activated = animal.Mode_TryActivate(modeId, abilityIndex);
        if (!activated)
        {
            _actionInFlight = false;
            _actionWatchdog.Cancel();
            Debug.LogWarning($"[MalbersAdapter] Malbers refused Action mode={modeId} ability={abilityIndex}.");
        }

        return activated;
    }

    bool ExecuteClimb(Transform climbPoint, float duration, Vector3 inputAxis)
    {
        State climbState = animal.State_Get(StateEnum.Climb);
        if (climbState == null)
        {
            Debug.LogWarning("[MalbersAdapter] Climb command rejected: MAnimal does not have a Climb state.");
            return false;
        }

        StopNavigation(true);
        CancelActionExecution();
        ClearLingeringActionMode("before climb");

        if (snapToClimbPointRotation && climbPoint != null)
            animal.transform.rotation = climbPoint.rotation;

        _activeClimbState = climbState;
        _climbInFlight = true;
        _climbStateStarted = false;
        _climbStartedAt = Time.time;
        _climbDuration = duration > 0f ? duration : defaultClimbSeconds;
        _climbInputAxis = inputAxis == Vector3.zero ? defaultClimbInputAxis : inputAxis;
        if (_climbInputAxis == Vector3.zero)
            _climbInputAxis = Vector3.forward;
        _nextClimbActivateRetryAt = Time.time + 0.25f;

        animal.State_Activate(StateEnum.Climb);
        _climbStateStarted = animal.ActiveState == climbState;

        LastCommandCompletionReason = "ClimbStarted";
        if (logIntentProof)
            Debug.Log($"[MalbersAdapter] Climb command started point={(climbPoint != null ? climbPoint.name : "none")} duration={_climbDuration:F1}s stateStarted={_climbStateStarted}");
        return true;
    }

    bool ExecuteDeath()
    {
        aiControl.SetActive(false);
        animal.Sprint = false;
        if (deathState != null)
        {
            animal.State_Force(deathState);
            return true;
        }
        Debug.LogWarning("[MalbersAdapter] Death requested but no deathState assigned.");
        return false;
    }

    public void Stop()
    {
        CancelSimpleClimb("stopped");
        CancelFaceTarget("stopped");
        CancelActionExecution();
        StopNavigation(true);
    }

    void StopNavigation(bool stopAnimal)
    {
        StopManualNavigation(stopAnimal);
        ClearQueuedNavigationDestination();
        _activeFollowTarget = null;
        _hasActiveNavigationDestination = false;
        _navWatchdog.Cancel();
        if (aiControl != null) aiControl.Stop();
    }

    void CancelActionExecution()
    {
        _actionInFlight = false;
        _actionWatchdog.Cancel();
    }

    void UpdateSimpleClimb()
    {
        if (!_climbInFlight)
            return;

        if (_activeClimbState == null)
        {
            CompleteSimpleClimb("ClimbStateMissing");
            return;
        }

        float elapsed = Time.time - _climbStartedAt;
        if (_climbDuration > 0f && elapsed >= _climbDuration)
        {
            if (animal.ActiveState == _activeClimbState)
                animal.State_AllowExit();

            CompleteSimpleClimb("ClimbDurationComplete");
            return;
        }

        bool isActiveClimbState = animal.ActiveState == _activeClimbState;
        if (isActiveClimbState)
        {
            _climbStateStarted = true;
            animal.SetInputAxis(_climbInputAxis);
            animal.UsingMoveWithDirection = false;
            return;
        }

        if (_climbStateStarted)
        {
            CompleteSimpleClimb("ClimbExited");
            return;
        }

        if (Time.time < _nextClimbActivateRetryAt)
            return;

        _nextClimbActivateRetryAt = Time.time + 0.25f;
        animal.State_Activate(StateEnum.Climb);
    }

    void CompleteSimpleClimb(string reason)
    {
        _climbInFlight = false;
        _climbStateStarted = false;
        _activeClimbState = null;
        LastCommandCompletionReason = reason;
    }

    void CancelSimpleClimb(string reason)
    {
        if (!_climbInFlight)
            return;

        if (_activeClimbState != null && animal != null && animal.ActiveState == _activeClimbState)
            animal.State_AllowExit();

        CompleteSimpleClimb(reason);
    }

    void UpdateFaceTarget()
    {
        if (!_faceTargetInFlight)
            return;

        if (animal == null)
        {
            CompleteFaceTarget("FaceTargetAnimalMissing");
            return;
        }

        animal.StopMoving();
        animal.SetInputAxis(Vector3.zero);

        if (!UpdateFaceTargetRotation(faceTargetTurnSpeedDegrees * Time.deltaTime, out float angle))
        {
            CompleteFaceTarget("FaceTargetNoDirection");
            return;
        }

        if (angle <= faceTargetAngleTolerance)
        {
            CompleteFaceTarget("FaceTargetAligned");
            return;
        }

        if (faceTargetMaxSeconds > 0f && Time.time - _faceTargetStartedAt >= faceTargetMaxSeconds)
            CompleteFaceTarget("FaceTargetTimedOut");
    }

    bool UpdateFaceTargetRotation(float maxDegreesDelta, out float angle)
    {
        angle = 0f;
        Vector3 direction = _faceTargetPosition - animal.transform.position;
        direction.y = 0f;

        if (direction.sqrMagnitude <= 0.0001f)
            return false;

        Quaternion targetRotation = Quaternion.LookRotation(direction.normalized, Vector3.up);
        angle = Quaternion.Angle(animal.transform.rotation, targetRotation);
        animal.transform.rotation = Quaternion.RotateTowards(
            animal.transform.rotation,
            targetRotation,
            Mathf.Max(0f, maxDegreesDelta));
        return true;
    }

    void CompleteFaceTarget(string reason)
    {
        _faceTargetInFlight = false;
        LastCommandCompletionReason = reason;
    }

    void CancelFaceTarget(string reason)
    {
        if (!_faceTargetInFlight)
            return;

        CompleteFaceTarget(reason);
    }

    // ═══════════════════════════════════════════════
    //  NAVIGATION CORE
    // ═══════════════════════════════════════════════
    bool NavigateTo_realistic(Vector3 requestedDestination)
    {
        ClearQueuedNavigationDestination();
        return NavigateTo_realistic(requestedDestination, 0);
    }

    bool NavigateTo_realistic(Vector3 requestedDestination, int detourHop)
    {
        _hasArrived = false;
        _hasActiveNavigationDestination = false;
        _activeFollowTarget = null;
        StopManualNavigation(false);
        PrepareForMovementCommand();

        // First requirement for believable movement: the target must land on
        // the NavMesh before Malbers is asked to walk there.
        if (!TryProjectDestination(requestedDestination, out Vector3 destination, out string reason))
        {
            if (requestedDestination == Vector3.zero)
            {
                Debug.LogWarning($"[MalbersAdapter] Cannot navigate to {requestedDestination}: {reason}");
                return false;
            }

            if (TryUseTeleportBackup(requestedDestination, $"no_navmesh_destination:{reason}"))
                return true;

            Debug.LogWarning(
                $"[MalbersAdapter] No NavMesh destination near {requestedDestination}: {reason}. Waiting for watchdog recovery.");
            return BeginNavigationRecovery(requestedDestination);
        }

        // A complete path still needs a cat-safety pass: Unity knows the route
        // is connected, but it does not know whether the body will hug an edge
        // or attempt a bad drop.
        NavPathSafetyResult routeSafety = EvaluateRouteSafety(destination);
        if (routeSafety.status != NavRouteSafetyStatus.Safe &&
            rejectRiskyNavMeshPaths &&
            routeSafety.status == NavRouteSafetyStatus.Risky &&
            TryFindSafeDetour(destination, routeSafety, detourHop, out Vector3 detour, out string detourReason))
        {
            QueueNavigationDestination(destination, detourHop + 1);
            if (logIntentProof)
                Debug.Log($"[MalbersAdapter] Direct route is risky ({routeSafety.reason}); using safe detour {detour}. {detourReason}");
            destination = detour;
            routeSafety = EvaluateRouteSafety(destination);
        }

        if (routeSafety.status != NavRouteSafetyStatus.Safe &&
            (rejectRiskyNavMeshPaths || routeSafety.status == NavRouteSafetyStatus.Blocked))
        {
            string pathReason = routeSafety.Summary;
            if (TryUseTeleportBackup(destination, $"no_complete_path:{pathReason}"))
                return true;

            Debug.LogWarning(
                $"[MalbersAdapter] No complete walk path. requested={requestedDestination} projected={destination}. reason={pathReason}. Waiting for watchdog recovery.");
            return BeginNavigationRecovery(destination);
        }

        _activeNavigationDestination = destination;
        _hasActiveNavigationDestination = true;
        _navWatchdog.Begin(destination, AnimalPosition, Time.time);

        if (TryNavigateWithMalbersAgent(destination))
            return true;

        if (useManualNavMeshFallback && TryStartManualNavigation(destination))
            return true;

        if (TryUseTeleportBackup(destination, "navigation_start_failed"))
            return true;

        Debug.LogWarning($"[MalbersAdapter] Realistic navigation failed. requested={requestedDestination} projected={destination}. {BuildNavigationDebug()}");
        _hasActiveNavigationDestination = false;
        _navWatchdog.NotifyFailed();
        LastNavigationCompletionReason = _navWatchdog.CompletionReason;
        LastCommandCompletionReason = LastNavigationCompletionReason.ToString();
        return false;
    }

    bool NavigateTo(Vector3 requestedDestination)
    {
        return NavigateTo_realistic(requestedDestination);
    }

    bool BeginNavigationRecovery(Vector3 destination)
    {
        _activeNavigationDestination = destination;
        _hasActiveNavigationDestination = true;
        _navWatchdog.Begin(destination, AnimalPosition, Time.time);
        return true;
    }

    bool TryUseTeleportBackup(Vector3 destination, string reason)
    {
        if (!teleportUnreachableGoToBackup) return false;

        if (TryWarpTo(destination, out string warpReason))
        {
            if (logIntentProof)
                Debug.LogWarning($"[MalbersAdapter] go_to teleport backup used. reason={reason} warpReason={warpReason} destination={destination}");
            return true;
        }

        Debug.LogWarning($"[MalbersAdapter] go_to teleport backup failed. reason={reason} destination={destination}");
        return false;
    }

    bool TryNavigateWithMalbersAgent(Vector3 destination)
    {
        if (!TryEnsureMalbersAgentReady(out string reason))
        {
            if (logIntentProof)
                Debug.LogWarning($"[MalbersAdapter] Malbers NavMeshAgent unavailable: {reason}");
            return false;
        }

        aiControl.SetDestination(destination);

        if (logIntentProof)
            Debug.Log($"[MalbersAdapter] SetDestination({destination}). MAnimalAIControl will pathfind.");

        return true;
    }

    bool TryProjectDestination(Vector3 requestedDestination, out Vector3 destination, out string reason)
    {
        destination = requestedDestination;
        reason = "";

        if (requestedDestination == Vector3.zero)
        {
            reason = "destination is Vector3.zero";
            return false;
        }

        int areaMask = AgentAreaMask();
        if (NavMesh.SamplePosition(requestedDestination, out NavMeshHit hit, navMeshDestinationSampleRadius, areaMask))
        {
            destination = hit.position;
            return true;
        }

        reason = $"no NavMesh within {navMeshDestinationSampleRadius:F1}m";
        return false;
    }

    NavPathSafetyResult EvaluateRouteSafety(Vector3 destination)
    {
        if (_navigationValidationPath == null)
            _navigationValidationPath = new NavMeshPath();

        return NavPathSafety.EvaluateRoute(
            AnimalPosition,
            destination,
            AgentAreaMask(),
            navigationSafety,
            navMeshStartSampleRadius,
            navMeshDestinationSampleRadius,
            _navigationValidationPath);
    }

    bool TryFindSafeDetour(
        Vector3 finalDestination,
        NavPathSafetyResult rejectedRoute,
        int detourHop,
        out Vector3 detour,
        out string reason)
    {
        detour = Vector3.zero;
        reason = "";

        if (!useSafeDetours)
        {
            reason = "safe_detours_disabled";
            return false;
        }

        if (detourHop >= Mathf.Max(0, maxSafeDetourHops))
        {
            reason = "max_safe_detour_hops";
            return false;
        }

        Vector3 start = AnimalPosition;
        Vector3 midpoint = Vector3.Lerp(start, finalDestination, 0.5f);
        Vector3 problem = rejectedRoute.hasProblemPoint ? rejectedRoute.problemPoint : midpoint;
        Vector3[] centers = { problem, midpoint, start };

        int samplesPerRing = Mathf.Max(4, safeDetourSamplesPerRing);
        float searchRadius = Mathf.Max(0.1f, safeDetourSearchRadius);
        float radiusStep = Mathf.Max(0.1f, safeDetourRadiusStep);
        int areaMask = AgentAreaMask();
        float bestScore = float.PositiveInfinity;
        string bestReason = "";
        bool found = false;
        var legAPath = new NavMeshPath();
        var legBPath = new NavMeshPath();

        for (int c = 0; c < centers.Length; c++)
        {
            Vector3 center = centers[c];
            for (float radius = radiusStep; radius <= searchRadius + 0.001f; radius += radiusStep)
            {
                for (int i = 0; i < samplesPerRing; i++)
                {
                    float angle = Mathf.PI * 2f * i / samplesPerRing;
                    Vector3 rawCandidate = center + new Vector3(Mathf.Cos(angle), 0f, Mathf.Sin(angle)) * radius;

                    if (!NavMesh.SamplePosition(rawCandidate, out NavMeshHit hit, navMeshDestinationSampleRadius, areaMask))
                        continue;

                    Vector3 candidate = hit.position;
                    if (HorizontalDistance(start, candidate) <= manualNavCornerDistance * 2f ||
                        HorizontalDistance(finalDestination, candidate) <= manualNavCornerDistance * 2f)
                        continue;

                    NavPathSafetyResult firstLeg = NavPathSafety.EvaluateRoute(
                        start,
                        candidate,
                        areaMask,
                        navigationSafety,
                        navMeshStartSampleRadius,
                        navMeshDestinationSampleRadius,
                        legAPath);

                    if (!firstLeg.IsSafe)
                    {
                        bestReason = $"first_leg_{firstLeg.Summary}";
                        continue;
                    }

                    NavPathSafetyResult secondLeg = NavPathSafety.EvaluateRoute(
                        candidate,
                        finalDestination,
                        areaMask,
                        navigationSafety,
                        navMeshStartSampleRadius,
                        navMeshDestinationSampleRadius,
                        legBPath);

                    if (!secondLeg.IsSafe)
                    {
                        bestReason = $"second_leg_{secondLeg.Summary}";
                        continue;
                    }

                    float score = firstLeg.pathLength + secondLeg.pathLength;
                    if (score >= bestScore)
                        continue;

                    bestScore = score;
                    detour = candidate;
                    reason = $"detour_score:{bestScore:F2}";
                    found = true;
                }
            }
        }

        if (found)
            return true;

        reason = string.IsNullOrWhiteSpace(bestReason) ? "no_safe_detour_candidate" : bestReason;
        return false;
    }

    void QueueNavigationDestination(Vector3 destination, int hop)
    {
        _queuedNavigationDestination = destination;
        _queuedNavigationHop = hop;
        _hasQueuedNavigationDestination = true;
    }

    void ClearQueuedNavigationDestination()
    {
        _hasQueuedNavigationDestination = false;
        _queuedNavigationDestination = Vector3.zero;
        _queuedNavigationHop = 0;
    }

    bool TryEnsureMalbersAgentReady(out string reason)
    {
        reason = "";

        var agent = aiControl != null ? aiControl.Agent : null;
        if (aiControl == null) { reason = "MAnimalAIControl is null"; return false; }
        if (agent == null)     { reason = "NavMeshAgent is null"; return false; }
        if (!aiControl.gameObject.activeInHierarchy) { reason = "MAnimalAIControl GameObject is inactive"; return false; }
        if (!agent.gameObject.activeInHierarchy)     { reason = "NavMeshAgent GameObject is inactive"; return false; }

        if (aiControl.StateIsBlockingAgent)
            TryForceMovementState();

        if (aiControl.StateIsBlockingAgent)
        {
            reason = $"current state blocks the AI agent: {(animal.ActiveStateID != null ? animal.ActiveStateID.name : "unknown")}";
            return false;
        }

        if (!aiControl.enabled) aiControl.SetActive(true);
        if (!agent.enabled)     agent.enabled = true;

        if (agent.isOnNavMesh) return true;

        Vector3 probe = AnimalPosition;
        if (!NavMesh.SamplePosition(probe, out NavMeshHit hit, navMeshStartSampleRadius, agent.areaMask))
        {
            reason = $"agent is off NavMesh and no NavMesh was found near animal position {probe}";
            return false;
        }

        if (agent.Warp(hit.position) && agent.isOnNavMesh) return true;

        reason = $"agent is off NavMesh and Warp({hit.position}) did not place it on NavMesh";
        return false;
    }

    bool TryStartManualNavigation(Vector3 destination)
    {
        if (!TryBuildManualPath(destination, out string reason))
        {
            Debug.LogWarning($"[MalbersAdapter] Manual NavMesh fallback failed: {reason}");
            return false;
        }

        _usingManualNavigation = true;
        _manualNavigationDestination = destination;
        _manualRepathTimer = 0f;

        if (aiControl != null) aiControl.Stop();

        if (logIntentProof)
            Debug.Log($"[MalbersAdapter] using manual NavMesh fallback to {destination}.");
        return true;
    }

    bool TryBuildManualPath(Vector3 destination, out string reason)
    {
        reason = "";

        if (!NavMesh.SamplePosition(AnimalPosition, out NavMeshHit startHit, navMeshStartSampleRadius, AgentAreaMask()))
        {
            reason = $"no NavMesh near animal position {AnimalPosition}";
            return false;
        }

        if (_manualPath == null) _manualPath = new NavMeshPath();

        bool calculated = NavMesh.CalculatePath(startHit.position, destination, AgentAreaMask(), _manualPath);
        if (!calculated || _manualPath.status == NavMeshPathStatus.PathInvalid || _manualPath.corners == null || _manualPath.corners.Length == 0)
        {
            reason = $"CalculatePath failed start={startHit.position} destination={destination} status={_manualPath.status}";
            return false;
        }

        _manualCornerIndex = _manualPath.corners.Length > 1 ? 1 : 0;
        return true;
    }

    void UpdateManualNavigation()
    {
        if (!_usingManualNavigation) return;

        if (HorizontalDistance(AnimalPosition, _manualNavigationDestination) <= manualNavArrivalDistance)
        {
            _hasArrived = true;
            StopManualNavigation(true);
            NotifyWatchdogArrived();
            return;
        }

        _manualRepathTimer += Time.deltaTime;
        if (_manualRepathTimer >= manualNavRepathInterval)
        {
            _manualRepathTimer = 0f;
            TryBuildManualPath(_manualNavigationDestination, out _);
        }

        if (_manualPath == null || _manualPath.corners == null || _manualPath.corners.Length == 0)
        {
            animal.StopMoving();
            return;
        }

        _manualCornerIndex = Mathf.Clamp(_manualCornerIndex, 0, _manualPath.corners.Length - 1);
        Vector3 corner = _manualPath.corners[_manualCornerIndex];
        Vector3 toCorner = corner - AnimalPosition;
        toCorner.y = 0f;

        while (toCorner.sqrMagnitude <= manualNavCornerDistance * manualNavCornerDistance &&
               _manualCornerIndex < _manualPath.corners.Length - 1)
        {
            _manualCornerIndex++;
            corner = _manualPath.corners[_manualCornerIndex];
            toCorner = corner - AnimalPosition;
            toCorner.y = 0f;
        }

        _manualNavigationCorner = corner;

        if (toCorner.sqrMagnitude <= 0.0001f)
        {
            _manualNavigationDirection = Vector3.zero;
            animal.StopMoving();
            return;
        }

        _manualNavigationDirection = toCorner.normalized;
        animal.Move(_manualNavigationDirection);
    }

    void StopManualNavigation(bool stopAnimal)
    {
        _usingManualNavigation = false;
        _manualCornerIndex = 0;
        _manualRepathTimer = 0f;
        _manualNavigationDirection = Vector3.zero;
        _manualNavigationCorner = Vector3.zero;

        if (stopAnimal && animal != null) animal.StopMoving();
    }

    int AgentAreaMask()
    {
        var agent = aiControl != null ? aiControl.Agent : null;
        return agent != null ? agent.areaMask : NavMesh.AllAreas;
    }

    Vector3 AnimalPosition => animal != null ? animal.transform.position : transform.position;

    static float HorizontalDistance(Vector3 a, Vector3 b)
    {
        a.y = 0f;
        b.y = 0f;
        return Vector3.Distance(a, b);
    }

    // ═══════════════════════════════════════════════
    //  DEBUG
    // ═══════════════════════════════════════════════

    public bool HasActiveNavigationDestination => _hasActiveNavigationDestination;
    public Vector3 ActiveNavigationDestination => _activeNavigationDestination;
    public Transform ActiveFollowTarget => _activeFollowTarget;
    public bool IsUsingManualNavigation => _usingManualNavigation;
    public Vector3 ManualNavigationDirection => _manualNavigationDirection;
    public Vector3 ManualNavigationCorner => _manualNavigationCorner;
    public int NavigationAreaMask => AgentAreaMask();

    public string BuildNavigationDebug()
    {
        var agent = aiControl != null ? aiControl.Agent : null;
        string watchdog =
            $"watchdogActive={_navWatchdog.IsActive} repaths={_navWatchdog.RepathAttempts} lastReason={LastNavigationCompletionReason} " +
            $"actionBusy={_actionWatchdog.IsBusy} actionReason={LastActionCompletionReason}";

        if (agent == null) return $"agent=null {watchdog}";

        bool canReadNavState = agent.isActiveAndEnabled && agent.isOnNavMesh;
        return
            $"agentActive={agent.isActiveAndEnabled} onNavMesh={agent.isOnNavMesh} " +
            $"agentPos={agent.transform.position.ToString("F3")} animalPos={AnimalPosition.ToString("F3")} " +
            $"destination={(canReadNavState ? agent.destination.ToString("F3") : "n/a")} " +
            $"pathStatus={(canReadNavState ? agent.pathStatus.ToString() : "n/a")} " +
            $"manualFallback={useManualNavMeshFallback} {watchdog}";
    }

    // ═══════════════════════════════════════════════
    //  RECOVERY (driven by NavigationWatchdog)
    // ═══════════════════════════════════════════════

    void TickNavigationWatchdog()
    {
        if (!_hasActiveNavigationDestination || !_navWatchdog.IsActive) return;

        if (_activeFollowTarget != null)
        {
            _activeNavigationDestination = _activeFollowTarget.position;
            _navWatchdog.UpdateDestination(_activeNavigationDestination, AnimalPosition, Time.time);
        }

        var decision = _navWatchdog.Tick(AnimalPosition, Time.time);
        switch (decision)
        {
            case NavigationRecoveryAction.Continue:
                break;
            case NavigationRecoveryAction.Repath:
                RepathActiveDestination();
                break;
            case NavigationRecoveryAction.Warp:
                WarpToActiveDestination();
                break;
        }
    }

    void RepathActiveDestination()
    {
        if (logIntentProof)
            Debug.Log(
                $"[MalbersAdapter] Watchdog repath ({_navWatchdog.RepathAttempts}/{recoveryConfig.maxRepathAttempts}) → {_activeNavigationDestination}. {BuildNavigationDebug()}");

        if (_usingManualNavigation)
        {
            TryBuildManualPath(_manualNavigationDestination, out _);
            return;
        }

        if (_activeFollowTarget != null)
        {
            aiControl.SetTarget(_activeFollowTarget, true);
            return;
        }

        if (TryEnsureMalbersAgentReady(out _))
            aiControl.SetDestination(_activeNavigationDestination);
    }

    void WarpToActiveDestination(bool preferNavMeshProjection = true)
    {
        Vector3 raw = _activeNavigationDestination;
        Vector3 warpPos = ProjectWarpTarget(raw, preferNavMeshProjection, out bool projected);
        FinalizeWarp(raw, warpPos, projected, "watchdog");
    }

    /// <summary>
    /// Public worker-facing teleport. Used by recovery paths (see ADR-008 follow-up)
    /// when a confirmation miss makes it clear the cat cannot reach the destination
    /// by walking. Always succeeds because raw warp is the final fallback.
    /// </summary>
    public bool TryWarpTo(Vector3 destination, out string reason)
    {
        bool hasAnimal = animal != null;
        var agent = aiControl != null ? aiControl.Agent : null;
        bool canWarpAgent = agent != null && agent.gameObject.activeInHierarchy && agent.enabled;
        if (!hasAnimal && !canWarpAgent)
        {
            reason = "no_movable_body";
            return false;
        }

        Vector3 warpPos = ProjectWarpTarget(destination, true, out bool projected);
        FinalizeWarp(destination, warpPos, projected, "recovery");
        reason = projected ? "WarpedToNavMesh" : "WarpedRaw";
        return true;
    }

    Vector3 ProjectWarpTarget(Vector3 raw, bool preferNavMeshProjection, out bool projected)
    {
        projected = false;
        if (preferNavMeshProjection &&
            NavMesh.SamplePosition(raw, out NavMeshHit hit, recoveryConfig.warpNavMeshSampleRadius, AgentAreaMask()))
        {
            projected = true;
            return hit.position;
        }
        return raw;
    }

    void FinalizeWarp(Vector3 requestedDestination, Vector3 warpPos, bool projected, string source)
    {
        WarpAnimalAndAgent(warpPos);
        RefreshSpatialZonesNow();

        StopManualNavigation(true);
        if (aiControl != null) aiControl.Stop();

        _hasActiveNavigationDestination = false;
        _hasArrived = true;
        _activeFollowTarget = null;

        if (projected) _navWatchdog.NotifyWarpedToNavMesh();
        else           _navWatchdog.NotifyWarpedRaw();
        LastNavigationCompletionReason = _navWatchdog.CompletionReason;
        LastCommandCompletionReason = LastNavigationCompletionReason.ToString();

        Debug.LogWarning(
            $"[MalbersAdapter] {source} warped cat to {(projected ? "NavMesh-projected" : "raw")} destination {warpPos} (requested={requestedDestination}). reason={LastNavigationCompletionReason}");
    }

    void WarpAnimalAndAgent(Vector3 warpPos)
    {
        if (animal != null)
        {
            animal.transform.position = warpPos;
            animal.StopMoving();
        }

        var agent = aiControl != null ? aiControl.Agent : null;
        if (agent != null && agent.gameObject.activeInHierarchy && agent.enabled)
            agent.Warp(warpPos);
    }

    void RefreshSpatialZonesNow()
    {
        ZoneScanner scanner = GetComponent<ZoneScanner>();
        if (scanner == null) scanner = GetComponentInParent<ZoneScanner>();
        if (scanner == null) scanner = GetComponentInChildren<ZoneScanner>();
        scanner?.RefreshNow();
    }

    // ═══════════════════════════════════════════════
    //  ACTION WATCHDOG / COMMAND CLEANUP
    // ═══════════════════════════════════════════════

    void TickActionWatchdog()
    {
        var decision = _actionWatchdog.Tick(Time.time);
        switch (decision)
        {
            case ActionWatchdogDecision.Continue:
                return;
            case ActionWatchdogDecision.FinishCooldown:
                _actionWatchdog.FinishCooldown();
                return;
            case ActionWatchdogDecision.ForceCleanup:
                ForceCompleteTimedOutAction();
                return;
        }
    }

    void ForceCompleteTimedOutAction()
    {
        string intent = _actionWatchdog.Intent;
        int ability = _actionWatchdog.AbilityIndex;

        _actionWatchdog.NotifyTimedOut(Time.time);
        _actionInFlight = false;
        LastActionCompletionReason = _actionWatchdog.CompletionReason;
        LastCommandCompletionReason = LastActionCompletionReason.ToString();

        if (actionExecutionConfig != null && actionExecutionConfig.forceStopOnTimeout)
            ForceStopActionMode();

        StopNavigation(true);
        Debug.LogWarning(
            $"[MalbersAdapter] Action watchdog cleaned up intent={intent} ability={ability} reason={LastActionCompletionReason}");
    }

    void PrepareForMovementCommand()
    {
        ClearLingeringActionMode("before movement");
        TryForceMovementState();
        if (aiControl != null && !aiControl.enabled)
            aiControl.SetActive(true);
    }

    void ClearLingeringActionMode(string context)
    {
        if (actionExecutionConfig != null && !actionExecutionConfig.interruptLingeringModeBeforeNewCommand)
            return;

        if (animal == null) return;
        if (!animal.IsPlayingMode && !animal.IsPreparingMode) return;

        ForceStopActionMode();

        if (logIntentProof)
            Debug.Log($"[MalbersAdapter] Cleared lingering Malbers mode {context}.");
    }

    void ForceStopActionMode()
    {
        if (animal == null) return;

        if (animal.IsPlayingMode)
            animal.Mode_Stop(true);

        if (animal.IsPreparingMode)
            animal.Mode_Interrupt_Forced();
    }

    void TryForceMovementState()
    {
        if (actionExecutionConfig != null && !actionExecutionConfig.forceLocomotionWhenStateBlocksNavigation)
            return;
        if (animal == null || aiControl == null || !aiControl.StateIsBlockingAgent)
            return;

        ForceStopActionMode();
        animal.State_Activate(StateEnum.Locomotion);
        if (aiControl.StateIsBlockingAgent)
            animal.State_Activate(StateEnum.Idle);
    }
}
