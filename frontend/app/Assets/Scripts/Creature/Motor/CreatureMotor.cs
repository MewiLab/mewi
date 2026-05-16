using UnityEngine;
using UnityEngine.AI;
using MalbersAnimations;
using MalbersAnimations.Controller;
using MalbersAnimations.Controller.AI;

/// <summary>
/// The "body" — reads the resolved intent from the blackboard each frame
/// and translates it into Malbers Animal Controller API calls.
///
/// This is the ONLY script that talks to Malbers. Brain, Reflex, and Mind
/// never touch animation or movement directly.
///
/// ── Intent vocabulary ──
///   Locomotion  : idle | wander | flee | investigate
///   Reflex      : flinch
///   Scripted    : eat | drink | sit | lie | sleep | groom | smell | alert | vocalize
///   Terminal    : die
///
/// ── Malbers Speed ──
///   Speed_CurrentIndex_Set(int) sets speed index within the active SpeedSet.
///   Index starts at 1: Ground set → 1=Walk, 2=Trot, 3=Run.
///   animal.Sprint = true/false toggles sprint.
///
/// ── Malbers Modes ──
///   All scripted actions share the Action ModeID.
///   Ability index matches the slot order in your MAnimal's Action mode list.
///   OnModeEnd fires when the animation finishes; the motor clears the
///   tactical slot so the creature naturally transitions back to wander/idle.
///
/// ── Malbers States ──
///   State_Force(StateID) bypasses conditions and forces the state immediately.
///   Used only for death (irreversible terminal transition).
///
/// ── Malbers AI Control (IAIControl) ──
///   SetDestination(Vector3), SetTarget(Transform), Stop(), SetActive(bool).
///   Arrival is event-based: subscribe to OnArrived.
/// </summary>
public class CreatureMotor : MonoBehaviour
{
    // ─── Set by CreatureController.Init ───
    CreatureBlackboard _board;
    CreatureConfig     _config;
    HttpActionReporter _reporter;

    // ─── Malbers references ───
    [Header("Malbers References")]
    public MAnimal         animal;
    public MAnimalAIControl aiControl;

    // ─── Mode setup ───
    [Header("Mode Setup")]
    [Tooltip("ModeID asset for the 'Action' mode. Optional: Malbers Action mode is usually ID 4.")]
    public ModeID actionMode;
    [Tooltip("Fallback Action mode ID used when no ModeID asset is assigned. Malbers default Action mode is 4.")]
    public int actionModeId = 4;

    // ─── Action ability indices — match your MAnimal Action mode list (1-based) ───
    // Defaults match the Malbers preset. Override in the Inspector if your list differs.
    [Header("Action Ability Indices (match MAnimal Action mode list order)")]
    public int startleAbilityIndex  = 1;   // Stun / startle
    public int scratchAbilityIndex  = 0;   // Scratch (set index in Inspector)
    public int lookAroundAbilityIndex = 0; // Look around (set index in Inspector)
    public int nodHeadAbilityIndex  = 0;   // Nod head (set index in Inspector)
    public int eatAbilityIndex      = 2;   // Eat
    public int drinkAbilityIndex    = 7;   // Drink
    public int sitAbilityIndex      = 8;   // Seat / Sit
    public int lieAbilityIndex      = 11;  // Lie Down
    public int sleepAbilityIndex    = 6;   // Sleep
    public int groomAbilityIndex    = 0;   // Groom (set index in Inspector)
    public int smellAbilityIndex    = 16;  // Smell / Sniff
    public int alertAbilityIndex    = 0;   // Alert (set index in Inspector)
    public int vocalizeAbilityIndex = 20;  // Meow / Howl / Vocalize

    // ─── Stance setup ───
    [Header("Stance Setup")]
    public StanceID defaultStance;
    public StanceID sneakStance;

    // ─── Speed indices matching your Ground MSpeedSet (starts at 1) ───
    [Header("Speed Indices (Ground SpeedSet)")]
    [Tooltip("Walk = 1, Trot = 2, Run = 3 — match your MSpeedSet list order")]
    public int walkSpeedIndex = 1;
    public int trotSpeedIndex = 2;
    public int runSpeedIndex  = 3;

    // ─── State references ───
    [Header("State References")]
    [Tooltip("Drag the Cat Death StateID ScriptableObject here")]
    public StateID deathState;

    // ─── Motor-specific fallbacks ───
    [Header("Motor Defaults")]
    public float wanderRadius       = 10f;
    public float wanderRetargetTime = 5f;
    public float fleeDistance        = 15f;

    // ─── Navigation setup ───
    [Header("Navigation")]
    [Tooltip("How far to search when snapping a requested go_to/wander/flee destination onto the NavMesh.")]
    public float navMeshDestinationSampleRadius = 2f;
    [Tooltip("How far to search around the animal when building a fallback NavMesh path.")]
    public float navMeshStartSampleRadius = 2f;
    [Tooltip("If Malbers' NavMeshAgent is inactive/off NavMesh, drive MAnimal along a NavMeshPath directly.")]
    public bool useManualNavMeshFallback = true;
    public float manualNavArrivalDistance = 0.65f;
    public float manualNavCornerDistance = 0.35f;
    public float manualNavRepathInterval = 0.5f;

    // ─── Debug / proof ───
    [Header("Debug")]
    [Tooltip("Log every destination my intent system issues, plus a 1-second heartbeat proving MAnimalAIControl is only following orders.")]
    public bool logIntentProof = true;

    // ─── Internal ───
    string _currentIntent = "";
    string _currentCommandId = "";
    string _currentRequestId = "";
    float  _wanderTimer;
    bool   _hasArrived;
    float  _proofTimer;
    bool   _hasActiveNavigationDestination;
    bool   _usingManualNavigation;
    Vector3 _activeNavigationDestination;
    Vector3 _manualNavigationDestination;
    Vector3 _manualNavigationCorner;
    Vector3 _manualNavigationDirection;
    NavMeshPath _manualPath;
    int _manualCornerIndex;
    float _manualRepathTimer;

    // Set when we're holding an action-mode intent so OnModeEnd can clear it.
    bool _inActionIntent;

    public int ActionModeId => actionMode != null ? actionMode.ID : actionModeId;
    public bool HasActiveNavigationDestination => _hasActiveNavigationDestination;
    public Vector3 ActiveNavigationDestination => _activeNavigationDestination;
    public bool IsUsingManualNavigation => _usingManualNavigation;
    public Vector3 ManualNavigationDirection => _manualNavigationDirection;
    public Vector3 ManualNavigationCorner => _manualNavigationCorner;

    // ═══════════════════════════════════════════════
    //  INIT / TEARDOWN
    // ═══════════════════════════════════════════════

    public void Init(CreatureBlackboard board, CreatureConfig config)
    {
        _board  = board;
        _config = config;
        _reporter = GetComponent<HttpActionReporter>();

        if (animal == null)
            animal = GetComponent<MAnimal>() ?? GetComponentInParent<MAnimal>() ?? GetComponentInChildren<MAnimal>();

        if (aiControl == null)
            aiControl = GetComponent<MAnimalAIControl>()
                     ?? GetComponentInParent<MAnimalAIControl>()
                     ?? GetComponentInChildren<MAnimalAIControl>();

#if UNITY_EDITOR
        if (aiControl == null)
        {
            // Editor-only broad search so you can identify which GameObject holds it.
            aiControl = FindFirstObjectByType<MAnimalAIControl>();
            if (aiControl != null)
                Debug.LogWarning($"[CreatureMotor] MAnimalAIControl found via scene search on '{aiControl.gameObject.name}'. Move CreatureMotor there or assign the field in the Inspector.");
        }
#endif

        if (animal == null)    { Debug.LogError("[CreatureMotor] No MAnimal found! Place CreatureMotor on the animal root or assign it in the Inspector."); return; }
        if (aiControl == null) { Debug.LogError("[CreatureMotor] No MAnimalAIControl found! Your cat prefab may not have AI set up — use the Malbers _AI prefab variant or add MAnimalAIControl manually."); return; }

        // Wire MAnimalAIControl → MAnimal if not set in Inspector.
        // Without this, its OnEnable throws NullRef trying to subscribe to animal events.
        if (aiControl.animal == null)
            aiControl.animal = animal;

        // Prove the hierarchy is correct: NavMeshAgent must live on a child
        // of the MAnimal GameObject or MAnimalAIControl.ResetAgentPosition
        // will teleport the cat back to origin every frame.
        var navAgent = aiControl.Agent;
        if (navAgent != null && navAgent.transform == animal.transform)
            Debug.LogError(
                "[CreatureMotor] NavMeshAgent is on the MAnimal root — this will FREEZE the cat in place. " +
                "Move the NavMeshAgent onto a child GameObject and reassign MAnimalAIControl.Agent.");

        // MAnimalBrain.StartNewState() hardcodes `enabled = true` on itself, so
        // unchecking it in the Inspector does nothing. Destroy it so it never
        // fights CreatureMotor for control of MAnimalAIControl.
        var malbersBrain = GetComponentInParent<MAnimalBrain>();
        if (malbersBrain != null)
        {
            Debug.Log("[CreatureMotor] Destroying MAnimalBrain — CreatureMotor has full AI control.");
            Destroy(malbersBrain);
        }

        animal.PreInput -= ManualNavigationPreInput;
        animal.PreInput += ManualNavigationPreInput;

        aiControl.OnArrived.AddListener(OnArrived);
        aiControl.OnTargetPositionArrived.AddListener(OnPositionArrived);
        animal.OnModeEnd.AddListener(OnModeEnded);
    }

    void OnDisable()
    {
        if (aiControl != null)
        {
            aiControl.OnArrived.RemoveListener(OnArrived);
            aiControl.OnTargetPositionArrived.RemoveListener(OnPositionArrived);
        }

        if (animal != null)
        {
            animal.PreInput -= ManualNavigationPreInput;
            animal.OnModeEnd.RemoveListener(OnModeEnded);
        }
    }

    void OnArrived(Transform target) => _hasArrived = true;

    void OnPositionArrived(Vector3 position)
    {
        // Malbers can emit position-arrival events while its internal agent is
        // being stopped/reset. Only treat the event as our go_to completion
        // when it matches the current script-owned destination.
        if (!_hasActiveNavigationDestination)
            return;

        if (HorizontalDistance(position, _activeNavigationDestination) <= manualNavArrivalDistance)
            _hasArrived = true;
    }
    void ManualNavigationPreInput(MAnimal currentAnimal) => UpdateManualNavigation();

    /// <summary>
    /// Called by Malbers when any Mode animation finishes.
    /// If we're currently holding an action intent, clear it so the creature
    /// naturally falls back to whatever the Brain/Mind has queued.
    /// </summary>
    void OnModeEnded(int modeID, int abilityIndex)
    {
        if (!_inActionIntent) return;
        if (modeID != ActionModeId) return;

        _inActionIntent = false;

        // MAnimalAIControl.OnModeEnd (registered before ours) re-enables the agent
        // via CalculatePath()+Move() the moment a mode animation finishes.
        // StopAI() here immediately overrides that so the creature doesn't drift.
        StopAI();

        // The Mind slot issued this action; it's done — clear it so a stale
        // "sit"/"eat"/etc. can't resurface if Tactical is ever cleared later.
        ReportCurrent("succeeded", "");
        _board?.ClearMindIntent();
        _board?.SetTacticalCurrent("idle");   // Brain will overwrite on its next tick
    }

    // ─── Config accessors (CreatureConfig → local fallback) ───
    float WanderRadius       => _config != null ? _config.wanderRadius       : wanderRadius;
    float WanderRetargetTime => _config != null ? _config.wanderRetargetTime : wanderRetargetTime;
    float FleeDistance       => _config != null ? _config.fleeDistance        : fleeDistance;

    // ═══════════════════════════════════════════════
    //  TICK (called by CreatureController.Update)
    // ═══════════════════════════════════════════════

    public void Tick()
    {
        if (animal == null || aiControl == null) return;

        HandleGaze();

        IntentMessage intent = _board.ResolveActiveIntent();
        string commandId = intent.CommandId ?? "";

        if (intent.Intent != _currentIntent || commandId != _currentCommandId)
        {
            ExitIntent(_currentIntent);
            bool entered = EnterIntent(intent);
            _currentIntent = intent.Intent;
            _currentCommandId = commandId;
            _currentRequestId = intent.RequestId ?? "";

            if (!entered)
            {
                Report(intent, "failed", "Malbers refused or command is invalid");
                if (intent.Source == LayerSource.Mind)
                    _board.ClearMindIntent();
                _currentIntent = "";
                _currentCommandId = "";
                _currentRequestId = "";
                return;
            }

            Report(intent, "started", "");
            if (intent.Intent == "stop_moving" || intent.Intent == "stop")
                Report(intent, "succeeded", "");
        }

        ExecuteIntent(intent);
        LogProofHeartbeat();
    }

    // ═══════════════════════════════════════════════
    //  PROOF HEARTBEAT
    //  Once per second, dump the full chain so you can see that:
    //    1. Your intent is what's active
    //    2. The destination is the one MY code picked (wander/go_to/follow/etc)
    //    3. The NavMeshAgent is following that destination (not inventing one)
    //    4. The cat's position is actually advancing
    // ═══════════════════════════════════════════════
    void LogProofHeartbeat()
    {
        if (!logIntentProof) return;

        _proofTimer += Time.deltaTime;
        if (_proofTimer < 1f) return;
        _proofTimer = 0f;

        var agent = aiControl.Agent;

        string agentInfo;
        if (agent == null)
            agentInfo = "agent=NULL";
        else if (!agent.isActiveAndEnabled)
            agentInfo = $"agentEnabled=False onNavMesh={agent.isOnNavMesh}";
        else if (!agent.isOnNavMesh)
            agentInfo = "agentEnabled=True onNavMesh=False (cat is off the baked NavMesh)";
        else
            agentInfo =
                $"agentEnabled=True onNavMesh=True " +
                $"hasPath={agent.hasPath} " +
                $"remaining={agent.remainingDistance:F2} " +
                $"desiredVel={agent.desiredVelocity.magnitude:F2}";

        Debug.Log(
            $"[Motor:Proof] intent='{_currentIntent}' " +
            $"catPos={animal.transform.position} " +
            $"destination={aiControl.DestinationPosition} " +
            $"activeNav={(_hasActiveNavigationDestination ? _activeNavigationDestination.ToString("F3") : "none")} " +
            $"manualNav={_usingManualNavigation} " +
            $"manualCorner={_manualNavigationCorner.ToString("F3")} " +
            $"manualDir={_manualNavigationDirection.ToString("F3")} " +
            $"{agentInfo}");
    }

    // ═══════════════════════════════════════════════
    //  SPEED HELPER
    // ═══════════════════════════════════════════════

    void SetSpeed(int targetIndex)
    {
        animal.Speed_CurrentIndex_Set(targetIndex);
    }

    // ═══════════════════════════════════════════════
    //  NAVIGATION HELPERS
    //
    //  Every destination/target comes through here. We first try Malbers'
    //  MAnimalAIControl path, then fall back to a direct NavMeshPath follower
    //  if the NavMeshAgent is inactive/off mesh.
    // ═══════════════════════════════════════════════

    bool NavigateTo(Vector3 requestedDestination)
    {
        _hasArrived = false;
        _hasActiveNavigationDestination = false;
        StopManualNavigation(false);

        if (!TryProjectDestination(requestedDestination, out Vector3 destination, out string reason))
        {
            Debug.LogWarning($"[CreatureMotor] Cannot navigate to {requestedDestination}: {reason}");
            return false;
        }

        _activeNavigationDestination = destination;
        _hasActiveNavigationDestination = true;

        if (TryNavigateWithMalbersAgent(destination))
            return true;

        if (useManualNavMeshFallback && TryStartManualNavigation(destination))
            return true;

        Debug.LogWarning(
            $"[CreatureMotor] Navigation failed. requested={requestedDestination} projected={destination}. " +
            BuildNavigationDebug());
        _hasActiveNavigationDestination = false;
        return false;
    }

    bool TryNavigateWithMalbersAgent(Vector3 destination)
    {
        if (!TryEnsureMalbersAgentReady(out string reason))
        {
            if (logIntentProof)
                Debug.LogWarning($"[Motor:Proof] Malbers NavMeshAgent unavailable for '{_currentIntent}': {reason}");
            return false;
        }

        aiControl.SetDestination(destination);

        if (logIntentProof)
            Debug.Log($"[Motor:Proof] intent='{_currentIntent}' → MY code called SetDestination({destination}). MAnimalAIControl will now pathfind.");

        return true;
    }

    void NavigateToTarget(Transform t, bool alwaysFollow = false)
    {
        StopManualNavigation(false);
        _hasActiveNavigationDestination = false;
        aiControl.SetTarget(t, alwaysFollow);
        if (logIntentProof)
            Debug.Log($"[Motor:Proof] intent='{_currentIntent}' → MY code called SetTarget({t.name}). MAnimalAIControl will now pathfind.");
    }

    void StopAI()
    {
        StopManualNavigation(true);
        _hasActiveNavigationDestination = false;
        aiControl.Stop();
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

    bool TryEnsureMalbersAgentReady(out string reason)
    {
        reason = "";

        if (aiControl == null)
        {
            reason = "MAnimalAIControl is null";
            return false;
        }

        var agent = aiControl.Agent;
        if (agent == null)
        {
            reason = "NavMeshAgent is null";
            return false;
        }

        if (!aiControl.gameObject.activeInHierarchy)
        {
            reason = "MAnimalAIControl GameObject is inactive";
            return false;
        }

        if (!agent.gameObject.activeInHierarchy)
        {
            reason = "NavMeshAgent GameObject is inactive";
            return false;
        }

        if (aiControl.StateIsBlockingAgent)
        {
            reason = $"current state blocks the AI agent: {(animal.ActiveStateID != null ? animal.ActiveStateID.name : "unknown")}";
            return false;
        }

        if (!aiControl.enabled)
            aiControl.SetActive(true);

        if (!agent.enabled)
            agent.enabled = true;

        if (agent.isOnNavMesh)
            return true;

        Vector3 probe = AnimalPosition;
        if (!NavMesh.SamplePosition(probe, out NavMeshHit hit, navMeshStartSampleRadius, agent.areaMask))
        {
            reason = $"agent is off NavMesh and no NavMesh was found near animal position {probe}";
            return false;
        }

        if (agent.Warp(hit.position) && agent.isOnNavMesh)
            return true;

        reason = $"agent is off NavMesh and Warp({hit.position}) did not place it on NavMesh";
        return false;
    }

    bool TryStartManualNavigation(Vector3 destination)
    {
        if (!TryBuildManualPath(destination, out string reason))
        {
            Debug.LogWarning($"[CreatureMotor] Manual NavMesh fallback failed: {reason}");
            return false;
        }

        _usingManualNavigation = true;
        _manualNavigationDestination = destination;
        _manualRepathTimer = 0f;

        // Malbers AIControl cannot be used right now, so keep its agent stopped
        // and feed the MAnimal movement axis ourselves using the same direction
        // pattern MAnimalAIControl.Move() uses.
        if (aiControl != null)
            aiControl.Stop();

        if (logIntentProof)
            Debug.Log($"[Motor:Proof] intent='{_currentIntent}' using CreatureMotor manual NavMesh fallback to {destination}.");

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

        if (_manualPath == null)
            _manualPath = new NavMeshPath();

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
        if (!_usingManualNavigation)
            return;

        if (HorizontalDistance(AnimalPosition, _manualNavigationDestination) <= manualNavArrivalDistance)
        {
            _hasArrived = true;
            StopManualNavigation(true);
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

    void UpdateNavigation()
    {
        if (_usingManualNavigation)
            return;

        if (_hasArrived || !_hasActiveNavigationDestination)
            return;

        var agent = aiControl != null ? aiControl.Agent : null;
        bool agentCanContinue = aiControl != null &&
                                aiControl.isActiveAndEnabled &&
                                agent != null &&
                                agent.isActiveAndEnabled &&
                                agent.isOnNavMesh;

        if (agentCanContinue)
            return;

        if (useManualNavMeshFallback && !TryStartManualNavigation(_activeNavigationDestination))
            _hasActiveNavigationDestination = false;
    }

    bool IsAtActiveNavigationDestination()
    {
        return _hasActiveNavigationDestination &&
               HorizontalDistance(AnimalPosition, _activeNavigationDestination) <= manualNavArrivalDistance;
    }

    void StopManualNavigation(bool stopAnimal)
    {
        _usingManualNavigation = false;
        _manualCornerIndex = 0;
        _manualRepathTimer = 0f;
        _manualNavigationDirection = Vector3.zero;
        _manualNavigationCorner = Vector3.zero;

        if (stopAnimal && animal != null)
            animal.StopMoving();
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

    string BuildNavigationDebug()
    {
        var agent = aiControl != null ? aiControl.Agent : null;
        if (agent == null)
            return "agent=null";

        bool canReadNavState = agent.isActiveAndEnabled && agent.isOnNavMesh;
        return
            $"agentActive={agent.isActiveAndEnabled} onNavMesh={agent.isOnNavMesh} " +
            $"agentPos={agent.transform.position.ToString("F3")} animalPos={AnimalPosition.ToString("F3")} " +
            $"destination={(canReadNavState ? agent.destination.ToString("F3") : "n/a")} " +
            $"pathStatus={(canReadNavState ? agent.pathStatus.ToString() : "n/a")} " +
            $"manualFallback={useManualNavMeshFallback}";
    }

    // ═══════════════════════════════════════════════
    //  ACTION HELPER
    //
    //  All scripted one-shot actions (eat, drink, sleep, …) share this pattern:
    //    1. Stop AI navigation so the creature doesn't slide while animating.
    //    2. Pin the Action ModeID and the ability slot.
    //    3. Fire the input to start the animation.
    //  OnModeEnd (above) automatically clears the intent when the clip finishes.
    // ═══════════════════════════════════════════════

    bool TriggerAction(int abilityIndex)
    {
        int modeId = ActionModeId;
        if (modeId <= 0 || abilityIndex <= 0)
        {
            Debug.LogWarning($"[CreatureMotor] TriggerAction: actionModeId={modeId} abilityIndex={abilityIndex}");
            return false;
        }

        StopAI();

        // Malbers API: Action mode is commonly ID 4, and ability is selected
        // by index inside MAnimal.modes -> Action -> Abilities.
        bool activated = animal.Mode_TryActivate(modeId, abilityIndex);
        if (!activated)
            Debug.LogWarning($"[CreatureMotor] Malbers refused Action mode={modeId} ability={abilityIndex}. Check MAnimal.modes Action ability index/state/stance conditions.");

        _inActionIntent = activated;

        return activated;
    }

    // ═══════════════════════════════════════════════
    //  INTENT LIFECYCLE
    // ═══════════════════════════════════════════════

    /// <summary>Cleanup when LEAVING an intent (like MAnimalBrain Finish_Tasks).</summary>
    void ExitIntent(string oldIntent)
    {
        switch (oldIntent)
        {
            case "flee":
                animal.Sprint = false;
                SetSpeed(walkSpeedIndex);
                if (defaultStance != null) animal.Stance = defaultStance;
                break;

            case "flinch":
                aiControl.SetActive(true);
                break;

            case "investigate":
                if (defaultStance != null) animal.Stance = defaultStance;
                break;

            case "die":
                // Death is terminal — do not exit.
                break;
        }
    }

    /// <summary>Setup when ENTERING an intent (like MAnimalBrain Start_AIState).</summary>
    bool EnterIntent(IntentMessage intent)
    {
        Debug.Log($"[Motor] Intent: {_currentIntent} → {intent.Intent}");
        _hasArrived = false;

        switch (intent.Intent)
        {
            // ── Locomotion ──────────────────────────────────────────────────

            case "idle":
                StopAI();
                if (defaultStance != null) animal.Stance = defaultStance;
                SetSpeed(walkSpeedIndex);
                return true;

            case "wander":
                if (defaultStance != null) animal.Stance = defaultStance;
                SetSpeed(trotSpeedIndex);
                return PickWanderTarget();

            case "flee":
                SetSpeed(runSpeedIndex);
                animal.Sprint = true;
                return SetFleeDestination(intent.DirectionHint);

            case "investigate":
                if (sneakStance != null) animal.Stance = sneakStance;
                SetSpeed(walkSpeedIndex);
                if (_board.closestPlayer != null)
                    NavigateToTarget(_board.closestPlayer, true);   // alwaysFollow → Malbers auto-tracks
                return true;

            // ── LLM-driven navigation (written by AgentMindBridge) ───────────

            case "go_to":
                if (defaultStance != null) animal.Stance = defaultStance;
                SetSpeed(trotSpeedIndex);
                return NavigateTo(intent.DirectionHint);

            case "follow":
                if (defaultStance != null) animal.Stance = defaultStance;
                SetSpeed(trotSpeedIndex);
                if (_board.followTarget != null)
                {
                    NavigateToTarget(_board.followTarget, true);
                    return true;
                }
                else
                {
                    Debug.LogWarning("[CreatureMotor] 'follow' intent fired but followTarget is null on blackboard.");
                    return false;
                }

            case "stop_moving":
            case "stop":
                StopAI();
                _board?.ClearMindIntent();
                return true;

            // ── Reflex ───────────────────────────────────────────────────────

            case "flinch":
                return TriggerAction(startleAbilityIndex);

            case "scratch":
                return TriggerAction(scratchAbilityIndex);

            case "look_around":
                return TriggerAction(lookAroundAbilityIndex);

            case "nod_head":
                return TriggerAction(nodHeadAbilityIndex);

            // ── Scripted actions (one-shot, auto-clear via OnModeEnd) ────────

            case "eat":
                return TriggerAction(eatAbilityIndex);

            case "drink":
                return TriggerAction(drinkAbilityIndex);

            case "sit":
                return TriggerAction(sitAbilityIndex);

            case "lie":
                return TriggerAction(lieAbilityIndex);

            case "sleep":
                return TriggerAction(sleepAbilityIndex);

            case "groom":
                return TriggerAction(groomAbilityIndex);

            case "smell":
                return TriggerAction(smellAbilityIndex);

            case "alert":
                return TriggerAction(alertAbilityIndex);

            case "vocalize":
                return TriggerAction(vocalizeAbilityIndex);

            // ── Terminal ─────────────────────────────────────────────────────

            case "die":
                aiControl.SetActive(false);
                animal.Sprint = false;
                if (deathState != null)
                {
                    animal.State_Force(deathState);
                    return true;
                }
                else
                {
                    Debug.LogWarning("[CreatureMotor] 'die' intent fired but no deathState assigned.");
                    return false;
                }

            default:
                Debug.LogWarning($"[Motor] Unknown intent: {intent.Intent}");
                aiControl.Stop();
                return false;
        }
    }

    /// <summary>Per-frame update while an intent is active (like MAnimalBrain Update_State).</summary>
    void ExecuteIntent(IntentMessage intent)
    {
        switch (intent.Intent)
        {
            case "wander":
                UpdateNavigation();
                _wanderTimer += Time.deltaTime;
                if (_wanderTimer > WanderRetargetTime || _hasArrived)
                    PickWanderTarget();
                break;

            case "flee":
                if (intent.DirectionHint != Vector3.zero)
                    SetFleeDestination(intent.DirectionHint);
                UpdateNavigation();
                break;

            case "investigate":
                // Malbers handles moving-target tracking (alwaysFollow=true set in Enter).
                // If the player vanished from sight, hand control back to the brain.
                if (_board.closestPlayer == null)
                    _board.SetTacticalCurrent("idle");
                break;

            case "go_to":
                UpdateNavigation();

                // LLM-sourced one-shot: on arrival, clear Mind so the next tick
                // can issue a fresh intent. Without ClearMindIntent, a stale
                // "go_to" sits dormant behind Tactical.
                if (_hasArrived && IsAtActiveNavigationDestination())
                {
                    StopManualNavigation(true);
                    _hasActiveNavigationDestination = false;
                    Report(intent, "succeeded", "");
                    _board.ClearMindIntent();
                    _board.SetTacticalCurrent("idle");
                }
                else if (_hasArrived)
                {
                    // Ignore stale arrival events from Malbers internals. A go_to
                    // command should keep running until the animal is actually
                    // near the requested place.
                    _hasArrived = false;
                }
                break;

            case "follow":
                // Target vanished → stop chasing nothing.
                if (_board.followTarget == null)
                {
                    Report(intent, "failed", "follow target disappeared");
                    _board.ClearMindIntent();
                    _board.SetTacticalCurrent("idle");
                }
                break;

            // All action intents are one-shot — nothing to poll per frame.
            // OnModeEnd handles completion (and clears Mind).
        }
    }

    // ═══════════════════════════════════════════════
    //  GAZE (parallel channel — does not block intents)
    // ═══════════════════════════════════════════════

    void HandleGaze()
    {
        if (!_board.hasGazeOverride) return;

        // Hook into your Malbers Look At or Head Track component here.
        // Example:  lookAt.SetTarget(_board.gazeOverrideTarget);
    }

    // ═══════════════════════════════════════════════
    //  MOVEMENT HELPERS
    // ═══════════════════════════════════════════════

    bool PickWanderTarget()
    {
        _wanderTimer = 0f;
        _hasArrived  = false;

        Vector3 randomDir = Random.insideUnitSphere * WanderRadius + AnimalPosition;
        randomDir.y = AnimalPosition.y;

        if (NavMesh.SamplePosition(randomDir, out NavMeshHit hit, WanderRadius, NavMesh.AllAreas))
            return NavigateTo(hit.position);

        Debug.LogWarning($"[CreatureMotor] Wander → NavMesh.SamplePosition FAILED near {AnimalPosition} radius={WanderRadius}. Is the NavMesh baked?");
        return false;
    }

    bool SetFleeDestination(Vector3 threatPosition)
    {
        Vector3 fleeDir = (threatPosition == Vector3.zero)
            ? -animal.transform.forward
            : (AnimalPosition - threatPosition).normalized;

        Vector3 fleeTarget = AnimalPosition + fleeDir * FleeDistance;

        if (NavMesh.SamplePosition(fleeTarget, out NavMeshHit hit, FleeDistance, NavMesh.AllAreas))
            return NavigateTo(hit.position);

        Debug.LogWarning($"[CreatureMotor] Flee → NavMesh.SamplePosition FAILED near {fleeTarget} radius={FleeDistance}. Is the NavMesh baked?");
        return false;
    }

    void ReportCurrent(string status, string reason)
    {
        if (string.IsNullOrEmpty(_currentCommandId)) return;

        Report(new IntentMessage
        {
            Intent = _currentIntent,
            CommandId = _currentCommandId,
            RequestId = _currentRequestId,
            Source = LayerSource.Mind,
        }, status, reason);
    }

    void Report(IntentMessage intent, string status, string reason)
    {
        if (_reporter == null || string.IsNullOrEmpty(intent.CommandId) || _board == null)
            return;

        _reporter.Report(new ActionReport
        {
            agent_id  = _board.CreatureId,
            commandId = intent.CommandId,
            requestId = intent.RequestId ?? "",
            action    = intent.Intent,
            status    = status,
            reason    = reason ?? "",
            time      = Time.time,
        });
    }
}
