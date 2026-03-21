using UnityEngine;

/// <summary>
/// Master orchestrator — initializes layers and ticks them each frame.
///
/// UPGRADE from MVP:
///   1. All layers tick unconditionally. No "if reflex then skip brain" gating.
///      Each layer writes to its own slot on the blackboard. The arbitration happens
///      in ResolveActiveIntent(), not in the tick order. This is the core of
///      Brooks' subsumption: layers run in parallel and suppress by priority.
///
///   2. PeriodicMind no longer receives a CreatureBrain reference.
///      Mind → Blackboard → Brain. Layers communicate only through the board.
///      (Hayes-Roth blackboard architecture, 1985)
///
///   3. Added a resolve step at end of frame. ResolveActiveIntent() + UpdateDebugDisplay()
///      gives us a single place where the animation/movement system can read
///      the authoritative intent. Future: this is where Malbers integration hooks in.
///
/// Frame execution order:
///   ClearFrameFlags()   — wipe per-frame sensor data (NOT intent slots)
///   Perception.Tick()   — scan environment, write sensor data to board
///   Reflex.Tick()       — check for threats, maybe write reflexOverride slot
///   Brain.Tick()        — run FSM, read mindSuggestion, write tacticalCurrent slot
///   [Mind runs on its own coroutine timer — not called here]
///   ResolveAndApply()   — read winning slot, drive animation/movement
///   UpdateDebugDisplay()— sync Inspector strings
/// </summary>
public class CreatureController : MonoBehaviour
{
    [Header("Config")]
    [Tooltip("Create via Assets > Create > Creature > Config")]
    public CreatureConfig config;

    CreatureBlackBoard   _board;
    CreaturePerception   _perception;
    CreatureReflexRunner _reflex;
    CreatureBrain        _brain;
    PeriodicMind         _mind;

    void Awake()
    {
        _board      = GetComponent<CreatureBlackBoard>();
        _perception = GetComponent<CreaturePerception>();
        _reflex     = GetComponent<CreatureReflexRunner>();
        _brain      = GetComponent<CreatureBrain>();
        _mind       = GetComponent<PeriodicMind>();

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

        if (_perception != null) _perception.Init(_board, config);
        if (_reflex != null)     _reflex.Init(_board, config);
        if (_brain != null)      _brain.Init(_board, config);

        // CHANGE: Mind no longer takes brain reference — decoupled via blackboard
        if (_mind != null) _mind.Init(_board, config);
    }

    void Start()
    {
        if (_mind != null) _mind.StartThinking();
    }

    void Update()
    {
        // ── 1. Clear per-frame sensor data (NOT intent slots) ──
        _board.ClearFrameFlags();

        // ── 2. All layers tick unconditionally ──
        // Each writes to its own slot. No layer checks whether another layer
        // "allows" it to run. Suppression is handled by ResolveActiveIntent().
        if (_perception != null) _perception.Tick();
        if (_reflex != null)     _reflex.Tick();
        if (_brain != null)      _brain.Tick();

        // Mind ticks on its own coroutine timer (PeriodicMind.ThinkLoop).
        // It's async relative to the frame loop — that's intentional.
        // Its output (mindSuggestion slot) is read by Brain.ConsumeMindSuggestion().

        // ── 3. Resolve winning intent and apply ──
        ResolveAndApply();

        // ── 4. Debug display ──
        _board.UpdateDebugDisplay();
    }

    /// <summary>
    /// Read the winning intent slot and drive animation/movement.
    ///
    /// This is the single output point — the animation system never reads
    /// individual slots, only the resolved intent.
    ///
    /// Future: this is where Malbers State_Activate / Mode_Activate calls go.
    /// For now, just logs.
    /// </summary>
    void ResolveAndApply()
    {
        IntentSlot active = _board.ResolveActiveIntent();

        // TODO: Drive animation/movement based on active.intent and active.source
        //
        // Example integration points:
        //   active.intent == "flinch"      → animal.Mode_Activate(ModeID.Damage);
        //   active.intent == "flee"        → animal.State_Activate(StateID.Run);
        //                                    animal.SetDestination(awayFromThreat);
        //   active.intent == "investigate" → animal.State_Activate(StateID.Walk);
        //                                    animal.SetDestination(target);
        //   active.intent == "wander"      → animal.State_Activate(StateID.Walk);
        //                                    animal.SetDestination(randomPoint);
        //   active.intent == "idle"        → animal.State_Activate(StateID.Idle);
        //
        // active.source tells you WHO produced the intent:
        //   LayerSource.Reflex   → play flinch/dodge animation with blend priority
        //   LayerSource.Tactical → normal locomotion blend
        //   LayerSource.Mind     → (shouldn't reach here normally — mind is advisory)
        //
        // active.directionHint gives a direction vector for movement/facing.
    }

    void OnDisable()
    {
        if (_mind != null) _mind.StopThinking();
    }

    void OnDrawGizmosSelected()
    {
        // TODO: Visualize intent slots in scene view
        // e.g., color-coded sphere: red=reflex, green=tactical, blue=mind
    }
}
