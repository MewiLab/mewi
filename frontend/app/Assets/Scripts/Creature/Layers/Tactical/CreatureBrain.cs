using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.AI;


internal enum CreatureState { Idle, Wander, Flee, Investigate }

public class FSMEdge
{
    internal CreatureState From;
    internal CreatureState To;
    internal Func<bool>    Condition;     // decision gate
    internal Action        OnTransition;  // callback function when edge fires
}

/// <summary>
/// Tactical layer — FSM that selects what the cat is doing for the next few seconds.
/// Now reads from blackboard (populated by Perception) instead of doing its own sensing.
/// Respects reflexBlocksTactical — when a reflex fires, Brain skips its tick.
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
    NavMeshAgent _nav;
    CreatureState _state;
    float _stateTimer;

    Dictionary<CreatureState, List<FSMEdge>> _graph 
        = new Dictionary<CreatureState, List<FSMEdge>>();

    // Why need Intent Queue
    // Drawback: 
    readonly System.Collections.Generic.Queue<string> _intentQueue 
        = new System.Collections.Generic.Queue<string>();
    readonly object _lock = new object();

    public void Init(CreatureBlackBoard board, CreatureConfig config)
    {   
        _board = board;
        _config = config;
        _nav = GetComponent<NavMeshAgent>();
        InitFSM();
    }


    /// <summary>
    /// Called by CreatureController each frame.
    /// Returns early if reflex layer has taken control.
    /// </summary>
    public void Tick()
    {
        Debug.Log($"Current_hunger: {_board.health.hunger}");
        DrainIntentQueue();
        ScoreDrives();
        RunFSM();
    }

    public void EnqueueIntentQueue(string intent)
    // PeriodicMind would call the queue to save its intent based on the LLM thinking
    {
        lock (_lock) _intentQueue.Enqueue(intent);
    }

    public void DrainIntentQueue()
    {
        lock (_lock)
        {
            while (_intentQueue.Count > 0)
            {
                _board.SetCurrentIntent(_intentQueue.Dequeue());
            }
        }
    }

    void ScoreDrives()
    // Just a cheap simulation of the external perception between agent and virtual world
    {
        _board.SetCurrentHunger(
            Mathf.Clamp01(_board.GetCurrentHunger() + Time.deltaTime * 0.05f)
        );
    }


/// <summary>
/// FSM
/// </summary>
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

        // Simple simulation                 -> Flee -> Idle
        //                    Idle -> Wander                 
        //                                   -> Investigate -> Idle
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
            to  : CreatureState.Wander,
            condition:    () => _board.mood.fear < 0.3f && _stateTimer > 3f,
            onTransition: () => Debug.Log("[Brain] Investigate→Wander (done)")
        );

        AddEdge(
            from: CreatureState.Flee,
            to:   CreatureState.Idle,
            condition:    () => _stateTimer > 5f,
            onTransition: () => Debug.Log("[Brain] Investigate→Idle (done)")
        );
    }

    void RunFSM()
    {
        CreatureState desired = IntentToState(_board.GetCurrentIntent());
        if (desired != _state) {
            TransitionTo(desired); // _state get swap by 
            // For now to let the interruption state be add in new frame 
            // rather than in the mid, which is more easy to debug for now
            return; 
        }
        _stateTimer += Time.deltaTime;
        
        if (_graph.TryGetValue(_state, out var edges)) // the first condition matched, so it is DFA
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
    // Gameplay mapping
    {
        return intent switch
        {
            "flee"           => CreatureState.Flee,
            "investigate"    => CreatureState.Investigate,
            "wander"         => CreatureState.Wander,
            _                => CreatureState.Idle,
        };
    }

    void TransitionTo(CreatureState next)
    {   
        Debug.Log($"[Brain] Transition from {_state} to {next}");
        _state = next;
        _stateTimer = 0f;
        _board.LogEvent($"enter {next}");

        // TODO: Hook Malbers state/mode activation here
        // Example:
        // switch (next) {
        //     case CreatureState.Idle:   animal.State_Activate(StateID.Idle); break;
        //     case CreatureState.Wander: animal.SetDestination(PickWanderPoint()); break;
        //     case CreatureState.Flee:   animal.State_Activate(StateID.Run); break;
        // }
    }
}