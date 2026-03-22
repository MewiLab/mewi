using UnityEngine;
using UnityEngine.AI;

/// <summary>
/// Animation Layer — the "body" that translates brain decisions into animation.
/// 
/// This is the 4th layer in the procedural MVP stack:
///   Mind (slow) → Brain/Tactical FSM → Reflex → AnimatorDriver (this)
///
/// It reads from:
///   - NavMeshAgent velocity → Speed, Direction params
///   - CreatureBlackBoard.currentIntent → State param
///   - Blackboard flags → ActionId, AttackId, combat layer weight
///
/// It writes to:
///   - Animator parameters only. Never makes decisions.
///
/// Attach to the same GameObject as CreatureBrain, NavMeshAgent, Animator.
/// </summary>
[RequireComponent(typeof(Animator), typeof(NavMeshAgent))]
public class CreatureAnimatorDriver : MonoBehaviour
{
    // ─────────────────────────────────────────────
    // REFERENCES
    // ─────────────────────────────────────────────

    Animator       _anim;
    NavMeshAgent   _nav;
    CreatureBlackBoard _board;

    // ─────────────────────────────────────────────
    // CONFIG
    // ─────────────────────────────────────────────

    [Header("Locomotion")]
    [Tooltip("Cat's max possible speed — maps to Speed=1.0 in blend tree")]
    [SerializeField] float maxSpeed = 8f;

    [Tooltip("How quickly the animator blends to the target speed (lower = snappier)")]
    [SerializeField] float speedDamp = 0.1f;

    [Tooltip("How quickly the animator blends to the target direction")]
    [SerializeField] float directionDamp = 0.1f;

    [Tooltip("Below this NavAgent speed, force Speed param to 0 (prevents micro-sliding)")]
    [SerializeField] float idleDeadzone = 0.05f;

    [Header("Combat")]
    [Tooltip("How fast combat layer weight transitions (0→1 or 1→0)")]
    [SerializeField] float combatLayerBlendSpeed = 8f;

    // ─────────────────────────────────────────────
    // ANIMATOR PARAM HASHES (cached for performance)
    // ─────────────────────────────────────────────

    static readonly int H_State     = Animator.StringToHash("State");
    static readonly int H_Speed     = Animator.StringToHash("Speed");
    static readonly int H_Direction = Animator.StringToHash("Direction");
    static readonly int H_ActionId  = Animator.StringToHash("ActionId");
    static readonly int H_AttackId  = Animator.StringToHash("AttackId");

    // ─────────────────────────────────────────────
    // INTERNAL STATE
    // ─────────────────────────────────────────────

    float _targetCombatWeight = 0f;
    int   _combatLayerIndex   = -1;

    // ─────────────────────────────────────────────
    // LIFECYCLE
    // ─────────────────────────────────────────────

    public void Init(CreatureBlackBoard board)
    {
        _board = board;
        _anim  = GetComponent<Animator>();
        _nav   = GetComponent<NavMeshAgent>();

        // Find the combat layer index by name
        for (int i = 0; i < _anim.layerCount; i++)
        {
            if (_anim.GetLayerName(i) == "Combat Layer")
            {
                _combatLayerIndex = i;
                break;
            }
        }

        // Make sure root motion is OFF — NavAgent drives movement
        _anim.applyRootMotion = false;
    }

    /// <summary>
    /// Called every frame AFTER Brain.Tick().
    /// Reads blackboard + NavAgent state, writes to Animator.
    /// </summary>
    public void Tick()
    {
        if (_board == null || _anim == null) return;
        IntentMessage intent = _board.ResolveActiveIntent();
        UpdateLocomotion();
        UpdateState(intent.intent);
        UpdateCombatLayer();
    }

    // ─────────────────────────────────────────────
    // LOCOMOTION — Speed & Direction from NavAgent
    // ─────────────────────────────────────────────

    void UpdateLocomotion()
    {
        float rawSpeed = _nav.velocity.magnitude;

        // Dead zone: if barely moving, snap to 0 (prevents idle-walk blend jitter)
        float targetSpeed = rawSpeed < idleDeadzone ? 0f : rawSpeed / maxSpeed;

        // Direction: signed angle between cat's forward and velocity
        float targetDir = 0f;
        if (rawSpeed > idleDeadzone)
        {
            Vector3 localVel = transform.InverseTransformDirection(_nav.velocity);
            targetDir = Mathf.Atan2(localVel.x, localVel.z) / Mathf.PI; // -1 to +1
        }

        // Damped write — smooth blend, no popping
        _anim.SetFloat(H_Speed, targetSpeed, speedDamp, Time.deltaTime);
        _anim.SetFloat(H_Direction, targetDir, directionDamp, Time.deltaTime);
    }

    // ─────────────────────────────────────────────
    // STATE — map blackboard intent to Animator State int
    // ─────────────────────────────────────────────

    void UpdateState(string intent)
    {
        int animState = IntentToAnimState(intent);
        _anim.SetInteger(H_State, animState);
    }


    int IntentToAnimState(string intent)
    {
        return intent switch
        {
            // Locomotion intents — all map to State 1 (blend tree handles speed)
            "wander"      => 1,
            "flee"        => 1,  // same state, just faster — NavAgent speed drives the gait
            "investigate" => 1,  // walking toward something

            // Action intents — map to State 2, also need ActionId set
            "eat"         => 2,
            "drink"       => 2,
            "dig"         => 2,
            "pickup"      => 2,

            // Idle — default
            "idle"        => 0,
            _             => 0,
        };
    }

    // ─────────────────────────────────────────────
    // ACTIONS — set ActionId for one-shot clips
    // ─────────────────────────────────────────────

    /// <summary>
    /// Call from Brain when entering an action state.
    /// Sets ActionId BEFORE setting State=2 (avoids Empty_Fallback race).
    /// </summary>
    public void PlayAction(int actionId)
    {
        _anim.SetInteger(H_ActionId, actionId);
        _anim.SetInteger(H_State, 2);
    }

    /// <summary>
    /// Call from AnimationEvent or StateMachineBehaviour when action clip finishes.
    /// Resets ActionId to 0 and returns to idle.
    /// </summary>
    public void OnActionComplete()
    {
        _anim.SetInteger(H_ActionId, 0);
        _anim.SetInteger(H_State, 0); // back to idle, Brain will override next frame if needed
    }

    // ─────────────────────────────────────────────
    // COMBAT — layer weight + AttackId
    // ─────────────────────────────────────────────

    /// <summary>
    /// Call from Brain when entering/exiting combat.
    /// </summary>
    public void SetCombatActive(bool active)
    {
        _targetCombatWeight = active ? 1f : 0f;
    }

    /// <summary>
    /// Call from Brain to trigger a specific attack.
    /// AttackId 0 = no attack (stay in combat idle).
    /// </summary>
    public void PlayAttack(int attackId)
    {
        _anim.SetInteger(H_AttackId, attackId);
    }

    /// <summary>
    /// Call from AnimationEvent when attack clip finishes.
    /// Resets AttackId to 0 so Any State stops re-triggering.
    /// </summary>
    public void OnAttackComplete()
    {
        _anim.SetInteger(H_AttackId, 0);
    }

    void UpdateCombatLayer()
    {
        if (_combatLayerIndex < 0) return;

        float current = _anim.GetLayerWeight(_combatLayerIndex);
        float next = Mathf.MoveTowards(current, _targetCombatWeight, 
                                        combatLayerBlendSpeed * Time.deltaTime);
        _anim.SetLayerWeight(_combatLayerIndex, next);
    }

    // ─────────────────────────────────────────────
    // PUBLIC HELPERS — for other systems to query
    // ─────────────────────────────────────────────

    /// <summary>Is the cat currently in a one-shot action animation?</summary>
    public bool IsPlayingAction => _anim.GetInteger(H_State) == 2;

    /// <summary>Is combat layer active?</summary>
    public bool IsInCombat => _targetCombatWeight > 0.5f;
}