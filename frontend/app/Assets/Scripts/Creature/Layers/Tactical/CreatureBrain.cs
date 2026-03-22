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
public class CreatureBrain : MonoBehaviour
{   
    [Header("References — set by CreatureController")]
    CreatureBlackBoard _board;
    CreatureConfig     _config;
    CreatureState _state;
    float _stateTimer;

    Dictionary<CreatureState, List<FSMEdge>> _graph 
        = new Dictionary<CreatureState, List<FSMEdge>>();


    public void Init(CreatureBlackBoard board, CreatureConfig config)
    {   
        _board = board;
        _config = config;
        InitFSM();
    }

    public void Tick()
    {
        RunFSM();
    }

// --- FSM ----
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
            to:   CreatureState.Flee,
            condition:    () => _board.mood.fear > _config.fleeThreshold,
            onTransition: () => Debug.Log("[Brain] Wander→Flee (fear)")
        );

        AddEdge(
            from: CreatureState.Wander,
            to:   CreatureState.Investigate,
            condition:    () => _board.health.hunger > _config.investigateThreshold,
            onTransition: () => Debug.Log("[Brain] Wander→Investigate")
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
            onTransition: () => Debug.Log("[Brain] Flee→Idle (done)")
        );

        AddEdge(
            from: CreatureState.Wander, 
            to:   CreatureState.Idle,
            condition: () => _board.health.hunger < _config.hungerThreshold * 0.5f && _stateTimer > 3f,
            onTransition: () => Debug.Log("[Brain] Wander→Idle (satisfied)")
        );
    }

    void RunFSM()
    {
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
    
    // No _animDriver reference. Brain doesn't know Body exists.  
    void TransitionTo(CreatureState next)
    {
        _state = next;
        _stateTimer = 0f;

        switch (next)
        {
            case CreatureState.Idle:
                _board.SetTacticalCurrent("idle");
                break;

            case CreatureState.Wander:
                _board.SetTacticalCurrent("wander");
                break;

            case CreatureState.Flee:
                _board.SetTacticalCurrent("flee");
                break;
            case CreatureState.Investigate:
                _board.SetTacticalCurrent("investigate");
                break;
        }
    }
}