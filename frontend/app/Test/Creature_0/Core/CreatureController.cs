using UnityEngine;

/// <summary>
/// Top-level controller — the ONLY MonoBehaviour you manually add to the cat in Inspector.
/// Owns all layers, initializes them, runs them in the correct order each frame.
///
/// Tick order:
///   1. Blackboard clears frame flags
///   2. Perception  — what can the cat sense?
///   3. Reflex      — instant reactions (may block tactical)
///   4. Tactical    — FSM behavior selection (skipped if reflex blocks)
///   5. Mind        — runs on its own coroutine timer (not in Update)
///
/// All layer components should be on the same GameObject.
/// CreatureController finds them via GetComponent and calls Init().
/// </summary>
public class CreatureController : MonoBehaviour
{
    [Header("Config")]
    [Tooltip("Create via Assets > Create > Creature > Config")]
    public CreatureConfig config;

    // Layer references — found automatically
    CreatureBlackBoard    _board;
    CreaturePerception    _perception;
    CreatureReflexRunner  _reflex;
    CreatureBrain         _brain;
    PeriodicMind          _mind;

    void Awake()
    {
        // Find all layer components on this GameObject
        _board      = GetComponent<CreatureBlackBoard>();
        _perception = GetComponent<CreaturePerception>();
        _reflex     = GetComponent<CreatureReflexRunner>();
        _brain      = GetComponent<CreatureBrain>();
        _mind       = GetComponent<PeriodicMind>();

        // Validate
        if (config == null)
        {
            Debug.LogError("[CreatureController] No CreatureConfig assigned! " +
                           "Create one via Assets > Create > Creature > Config");
            enabled = false;
            return;
        }

        if (_board == null)
        {
            Debug.LogError("[CreatureController] Missing CreatureBlackBoard component!");
            enabled = false;
            return;
        }

        // Initialize each layer with shared references
        // Each layer only knows about the blackboard and config — never about other layers
        // (except Brain, which Mind needs to enqueue intents)

        if (_perception != null) _perception.Init(_board, config);
        if (_reflex != null)     _reflex.Init(_board, config);
        if (_brain != null)      _brain.Init(_board, config);
        if (_mind != null)       _mind.Init(_board, config, _brain);
    }

    void Start()
    {
        // Start the slow-thinking coroutine
        if (_mind != null) _mind.StartThinking();
    }

    void Update()
    {
        // ── Frame start: clear transient flags ──
        _board.ClearFrameFlags();

        // ── 1. Perception: gather what's happening ──
        if (_perception != null) _perception.Tick();

        // ── 2. Reflex: instant reactions, may set reflexBlocksTactical ──
        if (_reflex != null) _reflex.Tick();

        // ── 3. Tactical: FSM decision (respects reflex override internally) ──
        if (_brain != null) _brain.Tick();

        // Mind runs on its own coroutine — not ticked here.
        // Animation layer (Malbers) runs on its own Update — not ticked here.
    }

    void OnDisable()
    {
        if (_mind != null) _mind.StopThinking();
    }

    // ─────────────────────────────────────────────
    // Debug
    // ─────────────────────────────────────────────

    void OnDrawGizmosSelected()
    {
        if (config == null) return;

        // Personal space
        Gizmos.color = new Color(1f, 1f, 0f, 0.15f);
        Gizmos.DrawWireSphere(transform.position, config.personalSpaceRadius);

        // Sight range
        Gizmos.color = new Color(0f, 1f, 0f, 0.1f);
        Gizmos.DrawWireSphere(transform.position, config.sightRange);

        // Flinch distance
        Gizmos.color = new Color(1f, 0f, 0f, 0.2f);
        Gizmos.DrawWireSphere(transform.position, config.flinchDistance);

        // Gaze target
        if (_board != null && _board.hasGazeOverride)
        {
            Gizmos.color = Color.cyan;
            Gizmos.DrawLine(transform.position + Vector3.up * 0.5f, _board.gazeOverrideTarget);
        }
    }
}
