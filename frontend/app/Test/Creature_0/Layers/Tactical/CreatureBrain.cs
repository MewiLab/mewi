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
/// Now reads from blackboard (populated by Perception) instead of doing its own sensing.
/// Respects reflexBlocksTactical — when a reflex fires, Brain skips its tick.
///
/// With Malbers: each state calls Malbers API (SetDestination, State_Activate, Mode_Activate).
/// For MVP: states just log and set NavMeshAgent destination.
/// </summary>
[RequireComponent(typeof(NavMeshAgent))]
public class CreatureBrain : MonoBehaviour
{
    [Header("References — set by CreatureController")]
    public CreatureBlackBoard board;
    public CreatureConfig     config;

    NavMeshAgent   _nav;
    CreatureState  _state;
    float          _stateTimer;

    Dictionary<CreatureState, List<FSMEdge>> _graph
        = new Dictionary<CreatureState, List<FSMEdge>>();

    // ── Intent queue (PeriodicMind writes here) ──
    readonly Queue<string> _intentQueue = new Queue<string>();
    readonly object _lock = new object();

    public void Init(CreatureBlackBoard board, CreatureConfig config)
    {
        this.board  = board;
        this.config = config;
        _nav        = GetComponent<NavMeshAgent>();
        InitFSM();
    }

    public void EnqueueIntentQueue(string intent)
    {
        lock (_lock) { _intentQueue.Enqueue(intent); }
    }

    /// <summary>
    /// Called by CreatureController each frame.
    /// Returns early if reflex layer has taken control.
    /// </summary>
    public void Tick()
    {
        // If a reflex is blocking (e.g., flinch), don't run FSM this frame
        if (board.reflexBlocksTactical)
        {
            Debug.Log("[Brain] Reflex override — skipping tactical tick");
            return;
        }

        DrainIntentQueue();
        ScoreDrives();
        RunFSM();
    }

    void DrainIntentQueue()
    {
        lock (_lock)
        {
            while (_intentQueue.Count > 0)
            {
                board.SetCurrentIntent(_intentQueue.Dequeue());
            }
        }
    }

    void ScoreDrives()
    {
        // Simple hunger growth — uses config rate instead of hardcoded
        board.SetCurrentHunger(
            Mathf.Clamp01(board.GetCurrentHunger() + Time.deltaTime * config.hungerGrowthRate)
        );
    }

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
            condition:    () => board.GetCurrentHunger() > 0.5f,
            onTransition: () => Debug.Log("[Brain] Idle→Wander (hungry)")
        );

        AddEdge(
            from: CreatureState.Wander,
            to:   CreatureState.Investigate,
            condition:    () => board.GetCurrentHunger() > config.investigateThreshold,
            onTransition: () => Debug.Log("[Brain] Wander→Investigate")
        );

        AddEdge(
            from: CreatureState.Wander,
            to:   CreatureState.Flee,
            condition:    () => board.mood.fear > config.fleeThreshold,
            onTransition: () => Debug.Log("[Brain] Wander→Flee (fear)")
        );

        // Return edges — how to get back from Flee/Investigate
        AddEdge(
            from: CreatureState.Flee,
            to:   CreatureState.Idle,
            condition:    () => board.mood.fear < 0.3f && _stateTimer > 3f,
            onTransition: () => Debug.Log("[Brain] Flee→Idle (calmed down)")
        );

        AddEdge(
            from: CreatureState.Investigate,
            to:   CreatureState.Idle,
            condition:    () => _stateTimer > 5f,
            onTransition: () => Debug.Log("[Brain] Investigate→Idle (done)")
        );
    }

    void RunFSM()
    {
        // Check if PeriodicMind wants to force a state via intent
        CreatureState desired = IntentToState(board.GetCurrentIntent());
        if (desired != _state)
        {
            TransitionTo(desired);
            return;
        }

        _stateTimer += Time.deltaTime;

        // Evaluate FSM edges
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
        board.LogEvent($"enter {next}");

        // TODO: Hook Malbers state/mode activation here
        // Example:
        // switch (next) {
        //     case CreatureState.Idle:   animal.State_Activate(StateID.Idle); break;
        //     case CreatureState.Wander: animal.SetDestination(PickWanderPoint()); break;
        //     case CreatureState.Flee:   animal.State_Activate(StateID.Run); break;
        // }
    }
}
