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

    // Explicit dependency injection — we wire everything here so
    // initialization order is clear and testable without Unity magic.
    void Awake()
    {
        _board      = GetComponent<CreatureBlackboard>();
        _perception = GetComponent<CreaturePerception>();
        _reflex     = GetComponent<CreatureReflexRunner>();
        _brain      = GetComponent<CreatureBrain>();
        _mind       = GetComponent<PeriodicMind>();
        _motor      = GetComponent<CreatureMotor>();

        if (config == null)
        {
            Debug.LogError("[CreatureController] No CreatureConfig assigned!");
            enabled = false;
            return;
        }

        if (_board == null)
        {
            Debug.LogError("[CreatureController] Missing CreatureBlackboard component!");
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

    void Update()
    {
        _board.ClearFrameFlags();
        _board.ScoreDrives();

        if (_perception != null) _perception.Tick();
        if (_reflex != null)     _reflex.Tick();
        if (_brain != null)      _brain.Tick();
        if (_motor != null)      _motor.Tick();

        _board.UpdateDebugDisplay();
    }

    void OnDisable()
    {
        if (_mind != null) _mind.StopThinking();
    }

    void OnDrawGizmosSelected() { }
}
