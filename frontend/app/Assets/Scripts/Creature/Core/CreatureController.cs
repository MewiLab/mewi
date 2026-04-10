using UnityEngine;

public class CreatureController : MonoBehaviour
{   
    [Header("config")]
    [Tooltip("Create via Assets > Create > Creature > Config")]
    public CreatureConfig  config;
    CreatureBlackboard     _board;
    CreaturePerception     _perception;
    CreatureReflexRunner   _reflex;
    CreatureBrain          _brain;
    PeriodicMind           _mind;
    CreatureMotor          _motor;

    // We use dependency injections for more explicit initialzation setup
    // Rather then the magic hood under unity monobehavior framework
    // Which help use get to know the order each line is executed
    void Awake()
    {
        _board      = GetComponent<CreatureBlackboard>();
        _perception = GetComponent<CreaturePerception>();
        _reflex     = GetComponent<CreatureReflexRunner>();
        _brain      = GetComponent<CreatureBrain>();
        _mind       = GetComponent<PeriodicMind>();
        _motor      = GetComponent<CreatureMotor>();

            // ─── ADD THIS RIGHT AFTER ALL THE GetComponent CALLS IN CreatureController.Awake() ───
    // (after _motor = GetComponent<CreatureMotor>(); and before the config null check)
    Debug.Log("[CC] GameObject=" + gameObject.name + " Root=" + transform.root.name);
    Debug.Log("[CC] _board="      + (_board      != null));
    Debug.Log("[CC] _perception=" + (_perception != null));
    Debug.Log("[CC] _reflex="     + (_reflex     != null));
    Debug.Log("[CC] _brain="      + (_brain      != null));
    Debug.Log("[CC] _mind="       + (_mind       != null));
    Debug.Log("[CC] _motor="      + (_motor      != null));
 

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
        if (_mind != null)       _mind.Init(_board, config);
        if (_motor != null)      _motor.Init(_board, config);
    }
    void Start()
    {
        if (_mind != null) _mind.StartThinking();
    }

    // Human threshold 100ms feel instantaneous
    // 30 FPS: requires each frame in completed in 33.33 ms (milliseconds).
    // 60 FPS: 16.67 ms.
    // 90 FPS (common for VR): 11.11 ms.
    void Update()
    // TODO: concurrency task
    {
        _board.ClearFrameFlags(); // Clear previous frame perception flag for reflex
        _board.ScoreDrives();

        if (_perception != null) _perception.Tick();
        // if (_reflex != null)     _reflex.Tick();
        // if (_brain != null)      _brain.Tick();
        // if (_motor != null)      _motor.Tick();
        _board.UpdateDebugDisplay();
    }

    void OnDisable()
    {
        if (_mind != null) _mind.StopThinking();
    }

    void OnDrawGizmosSelected()
    {
        
    }
}
