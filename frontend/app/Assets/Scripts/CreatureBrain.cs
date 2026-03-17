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

[RequireComponent(typeof(NavMeshAgent), typeof(Animator))]
public class CreatureBrain : MonoBehaviour
{   
    [Header("Reference")]
    public CreatureBlackBoard board;

    [Header("Wander")]
    public float wanderRadius = 1.2f;
    public float waypointReachDist = 0.6f;

    [Header("Drive threasholds")]
    public float fleetThreshold = 0.6f;
    public float InvestigateThreshold = 0.8f;

    NavMeshAgent _nav;
    Animator _anim;
    CreatureState _state;
    float _stateTimer;

    static readonly int SpeedHash = Animator.StringToHash("speed");
    static readonly int FleedHash = Animator.StringToHash("flee");
    
    Dictionary<CreatureState, List<FSMEdge>> _graph 
        = new Dictionary<CreatureState, List<FSMEdge>>();

    void Awake() {
        _nav = GetComponent<NavMeshAgent>();
        _anim = GetComponent<Animator>();
        board = GetComponent<CreatureBlackBoard>();
    }

    void Start()
    {
        InitFSM();
    }

    void Update()
    {   
        Debug.Log($"Current_hunger: {board.GetCurrentHunger()}");
        DrainIntentQueue();
        ScoreDrives();
        RunFSM();
        //SyncAnimator();
    }


    // Why need Intent Queue
    // Drawback: 
    readonly System.Collections.Generic.Queue<string> _intentQueue 
        = new System.Collections.Generic.Queue<string>();
    readonly object _lock = new object();

    public void EnqueueIntentQueue(string intent)
    // PeriodicMind would call the queue to save its intent based on the LLM thinking
    {
        lock (_lock) {
            _intentQueue.Enqueue(intent);
        }
    }

    public void DrainIntentQueue()
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
    // Just a cheap simulation of the external perception between agent and virtual world
    {
        board.SetCurrentHunger(
            Mathf.Clamp01(
                board.GetCurrentHunger() + Time.deltaTime * 0.05f
            )
        );
    }

    void InitFSM()
    {
        void AddEdge(CreatureState from, CreatureState to,
                     Func<bool> condition, Action onTransition = null)
        {
            if (!_graph.ContainsKey(from))
            {
                _graph[from] = new List<FSMEdge>();
            }

            _graph[from].Add(new FSMEdge {
                From         = from,
                To           = to,
                Condition    = condition,
                OnTransition = onTransition
            });
        }

        // Simple simulation                 -> Flee
        //                    Idle -> Wander
        //                                   -> Investigate
        AddEdge(
            from: CreatureState.Idle,
            to:   CreatureState.Wander,
            condition:    () => board.GetCurrentHunger() > 0.5f,
            onTransition: () => {
                //_anim.SetTrigger(FleedHash);
                Debug.Log("Start wandering due to hungry");
            }
        );

        AddEdge(
            from: CreatureState.Wander,
            to:   CreatureState.Investigate,
            condition:    () => board.GetCurrentHunger() > InvestigateThreshold,
            onTransition: () =>
            {
                //_anim.SetTrigger(FleedHash);
                Debug.Log("Investigating...");
            }
        );

        AddEdge(
            from: CreatureState.Wander,
            to:   CreatureState.Flee,
            condition:     () => board.GetCurrentHunger() > fleetThreshold,
            onTransition:  () =>
            {
                //_anim.SetTrigger("Investigating");
                Debug.Log("Flee");
            }
        );
    }

    void RunFSM()
    {
        CreatureState desired = IntentToState(board.GetCurrentIntent());
        if (desired != _state) {
            StateInterruptSwapBy(desired); // _state get swap by 
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
                    StateInterruptSwapBy(edge.To);
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

    void StateInterruptSwapBy(CreatureState next)
    {   
        _state = next;
        _stateTimer = 0f;
        board.LogEvent($"enter {next}");
    }
    
    void SyncAnimator()
    // Just a simple simulated visualization of ..
    {
        _anim.SetFloat(
            SpeedHash,
            _nav.velocity.magnitude / _nav.speed
        );
    }
}