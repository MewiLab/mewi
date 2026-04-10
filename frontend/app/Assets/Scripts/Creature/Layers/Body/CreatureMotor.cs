using UnityEngine;
using UnityEngine.AI;
using MalbersAnimations;
using MalbersAnimations.Controller;
using MalbersAnimations.Controller.AI;
using MalbersAnimations.Scriptables;

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

    // ─── Internal ───
    string _currentIntent = "";
    float  _wanderTimer;
    bool   _hasArrived;

    // Set when we're holding an action-mode intent so OnModeEnd can clear it.
    bool _inActionIntent;

    // ═══════════════════════════════════════════════
    //  INIT / TEARDOWN
    // ═══════════════════════════════════════════════

    public void Init(CreatureBlackboard board, CreatureConfig config)
    {
        _board  = board;
        _config = config;

        if (animal == null)    animal    = GetComponentInParent<MAnimal>();
        if (aiControl == null) aiControl = GetComponentInChildren<MAnimalAIControl>();

        if (animal == null)    { Debug.LogError("[CreatureMotor] No MAnimal found!");    return; }
        if (aiControl == null) { Debug.LogError("[CreatureMotor] No MAnimalAIControl found!"); return; }

        // Wire MAnimalAIControl → MAnimal if not set in Inspector.
        // Without this, its OnEnable throws NullRef trying to subscribe to animal events.
        if (aiControl.animal == null)
            aiControl.animal = animal;

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

        if (intent.Intent != _currentIntent)
        {
            ExitIntent(_currentIntent);
            EnterIntent(intent);
            _currentIntent = intent.Intent;
        }

        ExecuteIntent(intent);
    }

    // ═══════════════════════════════════════════════
    //  SPEED HELPER
    // ═══════════════════════════════════════════════

    void SetSpeed(int targetIndex)
    {
        animal.Speed_CurrentIndex_Set(targetIndex);
    }

    // ═══════════════════════════════════════════════
    //  STOP HELPER
    //
    //  Calls Stop() to zero the agent and disable it.
    //  We drive exclusively via SetDestination() so there is no persistent
    //  target Transform to chase — no ClearTarget() needed.
    // ═══════════════════════════════════════════════

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

    void TriggerAction(int abilityIndex)
    {
        if (actionMode == null || abilityIndex <= 0)
        {
            Debug.LogWarning($"[CreatureMotor] TriggerAction: actionMode not set or abilityIndex = {abilityIndex}");
            return;
        }

        StopAI();
        _inActionIntent = true;

        animal.Mode_Pin(actionMode);
        animal.Mode_Pin_Ability(abilityIndex);
        animal.Mode_Pin_Input(true);
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
    void EnterIntent(IntentMessage intent)
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
                break;

            case "wander":
                if (defaultStance != null) animal.Stance = defaultStance;
                SetSpeed(trotSpeedIndex);
                PickWanderTarget();
                break;

            case "flee":
                SetSpeed(runSpeedIndex);
                animal.Sprint = true;
                SetFleeDestination(intent.DirectionHint);
                break;

            case "investigate":
                if (sneakStance != null) animal.Stance = sneakStance;
                SetSpeed(walkSpeedIndex);
                if (_board.closestPlayer != null)
                    aiControl.SetTarget(_board.closestPlayer);
                break;

            // ── Reflex ───────────────────────────────────────────────────────

            case "flinch":
                aiControl.Stop();
                TriggerAction(startleAbilityIndex);
                break;

            // ── Scripted actions (one-shot, auto-clear via OnModeEnd) ────────

            case "eat":
                TriggerAction(eatAbilityIndex);
                break;

            case "drink":
                TriggerAction(drinkAbilityIndex);
                break;

            case "sit":
                TriggerAction(sitAbilityIndex);
                break;

            case "lie":
                TriggerAction(lieAbilityIndex);
                break;

            case "sleep":
                TriggerAction(sleepAbilityIndex);
                break;

            case "groom":
                TriggerAction(groomAbilityIndex);
                break;

            case "smell":
                TriggerAction(smellAbilityIndex);
                break;

            case "alert":
                aiControl.Stop();
                TriggerAction(alertAbilityIndex);
                break;

            case "vocalize":
                aiControl.Stop();
                TriggerAction(vocalizeAbilityIndex);
                break;

            // ── Terminal ─────────────────────────────────────────────────────

            case "die":
                aiControl.SetActive(false);
                animal.Sprint = false;
                if (deathState != null)
                    animal.State_Force(deathState);
                else
                    Debug.LogWarning("[CreatureMotor] 'die' intent fired but no deathState assigned.");
                break;

            default:
                Debug.LogWarning($"[Motor] Unknown intent: {intent.Intent}");
                aiControl.Stop();
                break;
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
                if (_board.closestPlayer != null)
                    aiControl.SetTarget(_board.closestPlayer);
                break;

            // All action intents are one-shot — nothing to poll per frame.
            // OnModeEnd handles completion.
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
            aiControl.SetDestination(hit.position);
    }

    void SetFleeDestination(Vector3 threatPosition)
    {
        Vector3 fleeDir = (threatPosition == Vector3.zero)
            ? -transform.forward
            : (transform.position - threatPosition).normalized;

        Vector3 fleeTarget = transform.position + fleeDir * FleeDistance;

        if (NavMesh.SamplePosition(fleeTarget, out NavMeshHit hit, FleeDistance, NavMesh.AllAreas))
            aiControl.SetDestination(hit.position);
    }
}
