using UnityEngine;
using MalbersAnimations.Controller;
using MalbersAnimations.Controller.AI;

/// <summary>
/// CreatureMotor: Layer 5 (Body) 
/// 
/// Translates the resolved intent from the blackboard each tick into 
/// Malbers Animal Controller API calls.
/// </summary>
public class CreatureMotor : MonoBehaviour
{
    // ──────────────────────────────────────────────
    //  REFERENCES
    // ──────────────────────────────────────────────

    [Header("Malbers References")]
    [Tooltip("The MAnimal component on this creature")]
    [SerializeField] private MAnimal animal;

    [Tooltip("The AI Animal Control component (usually on a child object)")]
    [SerializeField] private MAnimalAIControl aiControl;

    private CreatureBlackboard board;
    private CreatureConfig config;

    // ──────────────────────────────────────────────
    //  MODE IDs — Match these to your Malbers Animator
    // ──────────────────────────────────────────────
    [Header("Mode IDs")]
    [SerializeField] private int attackModeID = 1;
    [SerializeField] private int actionModeID = 4;

    [Header("Action Ability Indices")]
    [SerializeField] private int eatAbilityIndex   = 6;
    [SerializeField] private int drinkAbilityIndex = 7;
    [SerializeField] private int sleepAbilityIndex = 8;
    [SerializeField] private int sitAbilityIndex   = 5;
    [SerializeField] private int groomAbilityIndex = 9;
    [SerializeField] private int playAbilityIndex  = 10;

    [Header("Speed Indices (Ground speed set)")]
    [SerializeField] private int walkSpeedIndex = 1;
    [SerializeField] private int trotSpeedIndex = 2;
    [SerializeField] private int runSpeedIndex  = 3;

    [Header("Stance IDs")]
    [SerializeField] private int alertStanceID   = 1;
    [SerializeField] private int sneakStanceID   = 2;
    [SerializeField] private int defaultStanceID = 0;

    [Header("Wander Settings")]
    [SerializeField] private float wanderRadius = 15f;
    [SerializeField] private float wanderInterval = 5f;

    // ──────────────────────────────────────────────
    //  INTERNAL STATE
    // ──────────────────────────────────────────────

    private string lastIntentString = "";
    private float wanderTimer;
    private bool waitingForArrival;
    private bool waitingForModeExit;

    // ──────────────────────────────────────────────
    //  LIFECYCLE & INITIALIZATION
    // ──────────────────────────────────────────────

    /// <summary>
    /// Called explicitly by CreatureController.Awake()
    /// </summary>
    public void Init(CreatureBlackboard blackboard, CreatureConfig creatureConfig)
    {
        board = blackboard;
        config = creatureConfig;

        if (animal == null) animal = GetComponent<MAnimal>();
        if (aiControl == null) aiControl = GetComponentInChildren<MAnimalAIControl>();

        // Subscribe to Malbers AI feedback events
        if (aiControl != null)
        {
            // Subscribe to position and transform arrival events
            aiControl.OnTargetArrived.AddListener(OnTargetArrived);
            aiControl.OnTargetPositionArrived.AddListener(OnPositionArrived);
        }
    }

    private void OnDisable()
    {
        if (aiControl != null)
        {
            aiControl.OnTargetArrived.RemoveListener(OnTargetArrived);
            aiControl.OnTargetPositionArrived.RemoveListener(OnPositionArrived);
        }
    }

    // ──────────────────────────────────────────────
    //  MAIN LOOP: Called by CreatureController.Update()
    // ──────────────────────────────────────────────

    public void Tick()
    {
        if (board == null || animal == null || aiControl == null) return;

        // Resolve the highest priority intent
        var currentIntentMsg = board.ResolveActiveIntent();
        
        // NOTE: Assuming IntentMessage has a string property called 'Intent'
        // If your struct uses a different name (e.g., 'Action', 'Name'), update it here.
        string currentIntentString = currentIntentMsg.Intent; 
        Debug.Log($"[Motor]: receive current intetn {currentIntentString}, lastIntent {lastIntentString} ");
        
        // 1. Detect Intent Change (One-shot triggers)
        if (currentIntentString != lastIntentString)
        {
            OnIntentChanged(lastIntentString, currentIntentString, currentIntentMsg);
            lastIntentString = currentIntentString;
        }

        // 2. Handle Continuous Intents (Updates every frame)
        HandleContinuousIntent(currentIntentString, currentIntentMsg);
    }

    private void OnIntentChanged(string oldIntent, string newIntent, IntentMessage msg)
    {
        ExitIntent(oldIntent);

        waitingForArrival = false;
        waitingForModeExit = false;

        switch (newIntent)
        {
            case "idle":         EnterIdle(); break;
            case "wander":       EnterWander(); break;
            case "flee":         EnterFlee(msg); break;
            case "go_to":        EnterGoTo(msg); break;
            case "investigate":  EnterInvestigate(msg); break;
            case "eat":          EnterEat(msg); break;
            case "drink":        EnterDrink(msg); break;
            case "sleep":        EnterSleep(); break;
            case "sit":          EnterSit(); break;
            case "groom":        EnterGroom(); break;
            case "play":         EnterPlay(msg); break;
            case "attack":       EnterAttack(msg); break;
            case "alert":        EnterAlert(); break;
            case "sneak":        EnterSneak(msg); break;
            case "flinch":       EnterSneak(msg); break;
            case "gaze":        EnterSneak(msg); break;
            default:
                EnterIdle(); 
                break;
        }
    }

    private void HandleContinuousIntent(string currentIntent, IntentMessage msg)
    {
        switch (currentIntent)
        {
            case "wander": UpdateWander(); break;
            case "flee":   UpdateFlee(msg); break;
        }
    }

    private void ExitIntent(string oldIntent)
    {
        switch (oldIntent)
        {
            case "alert":
            case "sneak":
                animal.Stance_Set(defaultStanceID);
                break;
            case "eat":
            case "drink":
            case "sleep":
            case "sit":
            case "groom":
            case "play":
            case "attack":
                animal.Mode_Interrupt();
                break;
        }
    }

    // ──────────────────────────────────────────────
    //  INTENT HANDLERS
    // ──────────────────────────────────────────────

    private void EnterIdle()
    {
        aiControl.Stop();
        animal.Mode_Stop();
        animal.Stance_Set(defaultStanceID);
    }

    private void EnterWander()
    {
        animal.Stance_Set(defaultStanceID);
        SetSpeed(walkSpeedIndex);
        PickNewWanderTarget();
        wanderTimer = wanderInterval;
    }

    private void UpdateWander()
    {
        wanderTimer -= Time.deltaTime;
        if (wanderTimer <= 0f || !waitingForArrival)
        {
            PickNewWanderTarget();
            wanderTimer = wanderInterval;
        }
    }

    private void PickNewWanderTarget()
    {
        Debug.Log("[Motor] PickNewWanderTarget()");
        Vector3 randomDir = Random.insideUnitSphere * wanderRadius;
        randomDir += transform.position;
        
        if (UnityEngine.AI.NavMesh.SamplePosition(randomDir, out var hit, wanderRadius, UnityEngine.AI.NavMesh.AllAreas))
        {
            aiControl.SetDestination(hit.position, true);
            waitingForArrival = true;
        }
    }

    private void EnterFlee(IntentMessage msg)
    {
        SetSpeed(runSpeedIndex);
        animal.SetSprint(true);
        UpdateFleeDestination(msg);
    }

    private void UpdateFlee(IntentMessage msg)
    {
        UpdateFleeDestination(msg);
    }

    private void UpdateFleeDestination(IntentMessage msg)
    {
        // Flee away from the closest player, or away from the directionHint
        Vector3 threatPos = board.closestPlayer != null ? board.closestPlayer.position : msg.DirectionHint;
        Vector3 awayDir = (transform.position - threatPos).normalized;
        Vector3 fleeTarget = transform.position + awayDir * 15f;

        if (UnityEngine.AI.NavMesh.SamplePosition(fleeTarget, out var hit, 15f, UnityEngine.AI.NavMesh.AllAreas))
        {
            aiControl.SetDestination(hit.position, true);
        }
    }

    private void EnterGoTo(IntentMessage msg)
    {
        SetSpeed(trotSpeedIndex);
        aiControl.SetDestination(msg.DirectionHint, true);
        waitingForArrival = true;
    }

    private void EnterInvestigate(IntentMessage msg)
    {
        SetSpeed(walkSpeedIndex);
        animal.Stance_Set(alertStanceID);
        aiControl.SetDestination(msg.DirectionHint, true);
        waitingForArrival = true;
    }

    // --- ACTION INTENTS ---

    private void EnterEat(IntentMessage msg)
    {
        // Check distance to food (directionHint)
        if (Vector3.Distance(transform.position, msg.DirectionHint) > 2f)
        {
            SetSpeed(trotSpeedIndex);
            aiControl.SetDestination(msg.DirectionHint, true);
            waitingForArrival = true;
        }
        else
        {
            aiControl.Stop();
            ActivateActionMode(eatAbilityIndex);
        }
    }

    private void EnterDrink(IntentMessage msg)
    {
        if (Vector3.Distance(transform.position, msg.DirectionHint) > 2f)
        {
            SetSpeed(trotSpeedIndex);
            aiControl.SetDestination(msg.DirectionHint, true);
            waitingForArrival = true;
        }
        else
        {
            aiControl.Stop();
            ActivateActionMode(drinkAbilityIndex);
        }
    }

    private void EnterSleep()
    {
        aiControl.Stop();
        ActivateActionMode(sleepAbilityIndex);
    }

    private void EnterSit()
    {
        aiControl.Stop();
        ActivateActionMode(sitAbilityIndex);
    }

    private void EnterGroom()
    {
        aiControl.Stop();
        ActivateActionMode(groomAbilityIndex);
    }

    private void EnterPlay(IntentMessage msg)
    {
        if (msg.DirectionHint != Vector3.zero && Vector3.Distance(transform.position, msg.DirectionHint) > 3f)
        {
            SetSpeed(runSpeedIndex);
            aiControl.SetDestination(msg.DirectionHint, true);
            waitingForArrival = true;
        }
        else
        {
            aiControl.Stop();
            ActivateActionMode(playAbilityIndex);
        }
    }

    private void EnterAttack(IntentMessage msg)
    {
        Transform target = board.closestPlayer; 
        if (target != null)
        {
            aiControl.SetTarget(target, true);
            SetSpeed(runSpeedIndex);
            animal.Mode_Activate(attackModeID, -99); // -99 usually triggers a random ability in Malbers
            waitingForModeExit = true;
        }
    }

    private void EnterAlert()
    {
        animal.Stance_Set(alertStanceID);
    }

    private void EnterSneak(IntentMessage msg)
    {
        animal.Stance_Set(sneakStanceID);
        SetSpeed(walkSpeedIndex);

        if (msg.DirectionHint != Vector3.zero)
        {
            aiControl.SetDestination(msg.DirectionHint, true);
            waitingForArrival = true;
        }
    }

    // ──────────────────────────────────────────────
    //  MALBERS API HELPERS
    // ──────────────────────────────────────────────

    private void SetSpeed(int speedIndex)
    {
        // For Malbers MAnimal, setting the sprint bool based on the speed index
        animal.SetSprint(speedIndex >= runSpeedIndex);
        
        // Ensure the AI moves. Speed modulation can depend on your specific Malbers version setup.
        // Usually, aiControl naturally requests higher speeds, but you can force it if needed.
    }

    private void ActivateActionMode(int abilityIndex)
    {
        animal.Mode_Activate(actionModeID, abilityIndex);
        waitingForModeExit = true;
    }

    // ──────────────────────────────────────────────
    //  FEEDBACK: Malbers → Blackboard
    // ──────────────────────────────────────────────

    private void OnTargetArrived(Transform target)
    {
        waitingForArrival = false;
        ProcessArrival();
    }

    private void OnPositionArrived(Vector3 position)
    {
        waitingForArrival = false;
        ProcessArrival();
    }

    private void ProcessArrival()
    {
        switch (lastIntentString)
        {
            case "eat":
                aiControl.Stop();
                ActivateActionMode(eatAbilityIndex);
                break;
            case "drink":
                aiControl.Stop();
                ActivateActionMode(drinkAbilityIndex);
                break;
            case "play":
                aiControl.Stop();
                ActivateActionMode(playAbilityIndex);
                break;
            case "investigate":
                board.LogEvent("arrived_at_poi");
                break;
            case "go_to":
                board.LogEvent("arrived_at_target");
                break;
            case "flee":
                board.LogEvent("flee_point_reached");
                break;
        }
    }

    /// <summary>
    /// Called when a Malbers Mode finishes. 
    /// Wire this to the MAnimal -> Modes -> [Action Mode] -> Events -> OnExit UnityEvent in the Inspector!
    /// </summary>
    public void OnActionModeExited()
    {
        waitingForModeExit = false;

        switch (lastIntentString)
        {
            case "eat":    board.LogEvent("eat_complete"); break;
            case "drink":  board.LogEvent("drink_complete"); break;
            case "sleep":  board.LogEvent("sleep_complete"); break;
            case "attack": board.LogEvent("attack_complete"); break;
            case "groom":  board.LogEvent("groom_complete"); break;
            case "play":   board.LogEvent("play_complete"); break;
        }
    }

#if UNITY_EDITOR
    private void OnDrawGizmosSelected()
    {
        Gizmos.color = new Color(0.2f, 0.8f, 0.5f, 0.15f);
        Gizmos.DrawWireSphere(transform.position, wanderRadius);

        if (Application.isPlaying && board != null)
        {
            UnityEditor.Handles.Label(
                transform.position + Vector3.up * 2.5f,
                $"Intent: {lastIntentString}\nWaiting: arrival={waitingForArrival} mode={waitingForModeExit}"
            );
        }
    }
#endif
}