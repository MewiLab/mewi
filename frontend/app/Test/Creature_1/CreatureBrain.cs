using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.AI;


internal enum CreatureState { Idle, Wander, Flee, Investigate }

public class FSMEdge
{
    internal CreatureState From;
    internal CreatureState To;
    internal Func<bool>    Condition;
    internal Action        OnTransition;
}

/// <summary>
/// Tactical layer — FSM that selects what the cat is doing for the next few seconds.
///
/// UPGRADE from MVP:
///   1. Writes to board.SetTacticalCurrent() instead of board.SetCurrentIntent().
///      This makes tactical a typed slot that ResolveActiveIntent() arbitrates.
///
///   2. Reads board.MindSuggestion instead of draining an intent queue.
///      Mind suggestions are advisory — the brain evaluates them against the current
///      state's interrupt threshold before adopting. This implements the hysteresis
///      pattern from Mark & Lewis (Game AI Pro Ch.10).
///
///   3. No longer checks reflexBlocksTactical. The brain ALWAYS ticks — it maintains
///      its own FSM state regardless of whether a reflex is suppressing its output.
///      When the reflex expires, ResolveActiveIntent() falls through to the tactical
///      slot, which was never cleared. The cat resumes its behavior seamlessly.
///      (Brooks' subsumption: higher layers suppress, not modify.)
///
///   4. Each state has an interruptThreshold (0-1). Mind suggestions only override
///      the current state if the suggestion's urgency exceeds this threshold.
///      This prevents flip-flop: a wandering cat (low threshold) will accept a
///      "flee" suggestion easily, but a fleeing cat (high threshold) won't
///      downgrade to "wander" until its own FSM edges fire.
///
/// With Malbers: each state calls Malbers API (SetDestination, State_Activate, Mode_Activate).
/// For MVP: states just log and set NavMeshAgent destination.
/// </summary>
[RequireComponent(typeof(NavMeshAgent), typeof(Animator))]
public class CreatureBrain : MonoBehaviour
{
    [Header("References — set by CreatureController")]
    CreatureBlackBoard _board;
    CreatureConfig     _config;
    NavMeshAgent       _nav;
    CreatureState      _state;
    float              _stateTimer;

    Dictionary<CreatureState, List<FSMEdge>> _graph
        = new Dictionary<CreatureState, List<FSMEdge>>();

    // ── Interrupt thresholds per state ──
    // Higher = harder to interrupt via mind suggestion.
    // Reflex ignores this entirely (it uses the slot system, not mind suggestions).
    //
    // Reference: Mark & Lewis, Game AI Pro Ch.10 — hysteresis via threshold prevents
    // oscillation between equally-scored behaviors.
    static readonly Dictionary<CreatureState, float> InterruptThreshold =
        new Dictionary<CreatureState, float>
    {
        { CreatureState.Idle,        0.1f },  // Very easy to interrupt — cat is doing nothing
        { CreatureState.Wander,      0.3f },  // Low commitment — open to suggestions
        { CreatureState.Investigate, 0.5f },  // Mid commitment — cat is engaged
        { CreatureState.Flee,        0.8f },  // High commitment — only override with something more urgent
    };

    // ── Urgency mapping for mind-suggested intents ──
    // How "urgent" is a given intent when suggested by Mind?
    // Must exceed the current state's InterruptThreshold to be adopted.
    static readonly Dictionary<string, float> IntentUrgency =
        new Dictionary<string, float>
    {
        { "idle",        0.0f },
        { "wander",      0.2f },
        { "investigate",  0.4f },
        { "flee",        0.9f },
    };

    public void Init(CreatureBlackBoard board, CreatureConfig config)
    {
        _board  = board;
        _config = config;
        _nav    = GetComponent<NavMeshAgent>();
        InitFSM();

        // Set initial tactical slot
        _board.SetTacticalCurrent("idle");
    }

    /// <summary>
    /// Called by CreatureController each frame.
    ///
    /// CHANGE from MVP: No longer checks reflexBlocksTactical.
    /// The brain always ticks its own FSM to maintain state continuity.
    /// Whether its output is visible depends on ResolveActiveIntent() —
    /// if a reflex is active, the reflex slot wins and the tactical slot
    /// is simply not read. But the FSM state is preserved.
    /// </summary>
    public void Tick()
    {
        ScoreDrives();
        ConsumeMindSuggestion();
        RunFSM();
    }

    /// <summary>
    /// Read the mind suggestion slot and decide whether to adopt it.
    ///
    /// This replaces DrainIntentQueue(). Instead of blindly taking the last
    /// enqueued intent, we compare the suggestion's urgency against the current
    /// state's interrupt threshold.
    ///
    /// Reference: Park et al. 2023 (Generative Agents) — the agent keeps acting
    /// on its cached plan while the LLM computes. When the result arrives, it's
    /// evaluated, not blindly applied.
    /// </summary>
    void ConsumeMindSuggestion()
    {
        var suggestion = _board.MindSuggestion;
        if (!suggestion.HasValue) return;

        string suggestedIntent = suggestion.Value.intent;

        // Look up urgency of the suggested intent
        float urgency = IntentUrgency.TryGetValue(suggestedIntent, out float u) ? u : 0.3f;

        // Look up current state's interrupt threshold
        float threshold = InterruptThreshold.TryGetValue(_state, out float t) ? t : 0.5f;

        if (urgency > threshold)
        {
            // Mind suggestion is urgent enough — adopt it
            CreatureState desired = IntentToState(suggestedIntent);
            if (desired != _state)
            {
                Debug.Log($"[Brain] Adopting mind suggestion: {suggestedIntent} " +
                          $"(urgency {urgency:F1} > threshold {threshold:F1})");
                TransitionTo(desired);
            }
        }
        else
        {
            Debug.Log($"[Brain] Ignoring mind suggestion: {suggestedIntent} " +
                      $"(urgency {urgency:F1} <= threshold {threshold:F1}, state={_state})");
        }

        // Always consume so we don't re-evaluate the same suggestion
        _board.ConsumeMindSuggestion();
    }


    void ScoreDrives()
    {
        // Just a cheap simulation of the external perception between agent and virtual world
        _board.SetCurrentHunger(
            Mathf.Clamp01(_board.hunger + Time.deltaTime * 0.05f)
        );
    }


    // ── FSM ──

    void InitFSM()
    {
        void AddEdge(CreatureState from, CreatureState to,
                     Func<bool> condition, Action onTransition = null)
        {
            if (!_graph.ContainsKey(from))
                _graph[from] = new List<FSMEdge>();

            _graph[from].Add(new FSMEdge
            {
                From         = from,
                To           = to,
                Condition    = condition,
                OnTransition = onTransition
            });
        }

        AddEdge(
            from: CreatureState.Idle,
            to:   CreatureState.Wander,
            condition:    () => _board.health.hunger > _config.hungerThreshold,
            onTransition: () => Debug.Log("[Brain] Idle→Wander (hungry)")
        );

        AddEdge(
            from: CreatureState.Wander,
            to:   CreatureState.Investigate,
            condition:    () => _board.health.hunger > _config.investigateThreshold,
            onTransition: () => Debug.Log("[Brain] Wander→Investigate")
        );

        AddEdge(
            from: CreatureState.Wander,
            to:   CreatureState.Flee,
            condition:    () => _board.mood.fear > _config.fleeThreshold,
            onTransition: () => Debug.Log("[Brain] Wander→Flee (fear)")
        );

        AddEdge(
            from: CreatureState.Investigate,
            to:   CreatureState.Wander,
            condition:    () => _board.mood.fear < 0.3f && _stateTimer > 3f,
            onTransition: () => Debug.Log("[Brain] Investigate→Wander (done)")
        );

        AddEdge(
            from: CreatureState.Flee,
            to:   CreatureState.Idle,
            condition:    () => _stateTimer > 5f,
            onTransition: () => Debug.Log("[Brain] Flee→Idle (done)")
        );
    }

    void RunFSM()
    {
        _stateTimer += Time.deltaTime;

        if (_graph.TryGetValue(_state, out var edges))
        {
            foreach (var edge in edges)
            {
                if (edge.Condition != null && edge.Condition.Invoke())
                {
                    edge.OnTransition?.Invoke();
                    TransitionTo(edge.To);
                    return;
                }
            }
        }
    }

    CreatureState IntentToState(string intent)
    {
        return intent switch
        {
            "flee"        => CreatureState.Flee,
            "investigate" => CreatureState.Investigate,
            "wander"      => CreatureState.Wander,
            _             => CreatureState.Idle,
        };
    }

    void TransitionTo(CreatureState next)
    {
        Debug.Log($"[Brain] {_state} → {next}");
        _state      = next;
        _stateTimer = 0f;

        // Write to the tactical slot — this is the key change.
        // The animation system reads this via ResolveActiveIntent().
        string intentTag = next switch
        {
            CreatureState.Flee        => "flee",
            CreatureState.Investigate => "investigate",
            CreatureState.Wander      => "wander",
            _                         => "idle",
        };
        _board.SetTacticalCurrent(intentTag);
        _board.LogEvent($"tactical: {next}");

        // TODO: Hook Malbers state/mode activation here
    }
}
