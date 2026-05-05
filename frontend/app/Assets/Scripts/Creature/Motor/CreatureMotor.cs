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
    [Tooltip("ModeID asset for the 'Action' mode (drag from Project)")]
    public ModeID actionMode;

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

    // Set when we're holding an action-mode intent so OnModeEnd can clear it.
    bool _inActionIntent;

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

        aiControl.OnArrived.AddListener(OnArrived);
        animal.OnModeEnd.AddListener(OnModeEnded);
    }

    void OnDisable()
    {
        if (aiControl != null)
            aiControl.OnArrived.RemoveListener(OnArrived);

        if (animal != null)
            animal.OnModeEnd.RemoveListener(OnModeEnded);
    }

    void OnArrived(Transform target) => _hasArrived = true;

    /// <summary>
    /// Called by Malbers when any Mode animation finishes.
    /// If we're currently holding an action intent, clear it so the creature
    /// naturally falls back to whatever the Brain/Mind has queued.
    /// </summary>
    void OnModeEnded(int modeID, int abilityIndex)
    {
        if (!_inActionIntent) return;
        if (actionMode == null || modeID != actionMode.ID) return;

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

        // Debug.Log(
        //     $"[Motor:Proof] intent='{_currentIntent}' " +
        //     $"catPos={transform.position} " +
        //     $"destination={aiControl.DestinationPosition} " +
        //     $"{agentInfo}");
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
    //  Every destination/target handed to MAnimalAIControl comes through here.
    //  MAnimalAIControl never invents a destination of its own — it only
    //  pathfinds to whatever WE tell it. That is the proof that the cat is
    //  driven by our intent system, not by Malbers.
    // ═══════════════════════════════════════════════

    void NavigateTo(Vector3 destination)
    {
        aiControl.SetDestination(destination);
        if (logIntentProof)
            Debug.Log($"[Motor:Proof] intent='{_currentIntent}' → MY code called SetDestination({destination}). MAnimalAIControl will now pathfind.");
    }

    void NavigateToTarget(Transform t, bool alwaysFollow = false)
    {
        aiControl.SetTarget(t, alwaysFollow);
        if (logIntentProof)
            Debug.Log($"[Motor:Proof] intent='{_currentIntent}' → MY code called SetTarget({t.name}). MAnimalAIControl will now pathfind.");
    }

    void StopAI()
    {
        aiControl.Stop();
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
        if (actionMode == null || abilityIndex <= 0)
        {
            Debug.LogWarning($"[CreatureMotor] TriggerAction: actionMode not set or abilityIndex = {abilityIndex}");
            return false;
        }

        StopAI();

        bool activated = animal.Mode_TryActivate(actionMode.ID, abilityIndex);
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
                PickWanderTarget();
                return true;

            case "flee":
                SetSpeed(runSpeedIndex);
                animal.Sprint = true;
                SetFleeDestination(intent.DirectionHint);
                return true;

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
                NavigateTo(intent.DirectionHint);
                return true;

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
                _wanderTimer += Time.deltaTime;
                if (_wanderTimer > WanderRetargetTime || _hasArrived)
                    PickWanderTarget();
                break;

            case "flee":
                if (intent.DirectionHint != Vector3.zero)
                    SetFleeDestination(intent.DirectionHint);
                break;

            case "investigate":
                // Malbers handles moving-target tracking (alwaysFollow=true set in Enter).
                // If the player vanished from sight, hand control back to the brain.
                if (_board.closestPlayer == null)
                    _board.SetTacticalCurrent("idle");
                break;

            case "go_to":
                // LLM-sourced one-shot: on arrival, clear Mind so the next tick
                // can issue a fresh intent. Without ClearMindIntent, a stale
                // "go_to" sits dormant behind Tactical.
                if (_hasArrived)
                {
                    Report(intent, "succeeded", "");
                    _board.ClearMindIntent();
                    _board.SetTacticalCurrent("idle");
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

    void PickWanderTarget()
    {
        _wanderTimer = 0f;
        _hasArrived  = false;

        Vector3 randomDir = Random.insideUnitSphere * WanderRadius + transform.position;
        randomDir.y = transform.position.y;

        if (NavMesh.SamplePosition(randomDir, out NavMeshHit hit, WanderRadius, NavMesh.AllAreas))
            NavigateTo(hit.position);
        else
            Debug.LogWarning($"[CreatureMotor] Wander → NavMesh.SamplePosition FAILED near {transform.position} radius={WanderRadius}. Is the NavMesh baked?");
    }

    void SetFleeDestination(Vector3 threatPosition)
    {
        Vector3 fleeDir = (threatPosition == Vector3.zero)
            ? -transform.forward
            : (transform.position - threatPosition).normalized;

        Vector3 fleeTarget = transform.position + fleeDir * FleeDistance;

        if (NavMesh.SamplePosition(fleeTarget, out NavMeshHit hit, FleeDistance, NavMesh.AllAreas))
            NavigateTo(hit.position);
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
