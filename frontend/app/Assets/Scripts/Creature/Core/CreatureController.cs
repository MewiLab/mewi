using UnityEngine;

public class CreatureController : MonoBehaviour
{
    [Header("config")]
    [Tooltip("Create via Assets > Create > Creature > Config")]
    public CreatureConfig  config;
    CreatureBlackboard     _board;
    CreaturePerception     _perception;
    PeriodicMind           _mind;
    CreatureWorker         _worker;
    CreatureAgent          _agent;
    SnapshotManager        _snapshot;
    SmartZoneTracker       _zoneTracker;
    ZoneScanner            _zoneScanner;


    /// <summary>
    /// DI, Initialization order is clear and testable without Unity magic.
    /// </summary>
    void Awake()
    {
        _board       = GetComponent<CreatureBlackboard>();
        _perception  = GetComponent<CreaturePerception>();
        _mind        = GetComponent<PeriodicMind>();
        _worker      = GetComponent<CreatureWorker>();
        _agent       = GetComponent<CreatureAgent>();
        _snapshot    = GetComponent<SnapshotManager>();
        _zoneTracker = GetComponent<SmartZoneTracker>();
        _zoneScanner = GetComponent<ZoneScanner>();

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

        if (_perception != null)  _perception.Init(_board, config);
        if (_mind != null)        _mind.Init(_board, config);
        if (_worker != null)      _worker.Init(_board);
        if (_agent != null)       _agent.Init(_board);
        if (_snapshot != null)    _snapshot.Init(_board);
        if (_zoneTracker != null) _zoneTracker.Init(_board);
        if (_zoneScanner != null) _zoneScanner.Init(_board);
    }

    /// <summary>
    /// PeriodicMind has its own timer
    /// It drives itself via a coroutine (WaitForSecondsRealtime) rather than Update()
    /// </summary>
    void Start()
    {
        if (_mind != null) _mind.StartThinking();
    }

    void Update()
    {
        _board.ScoreDrives();

        if (_perception != null)  _perception.Tick();
        if (_zoneScanner != null) _zoneScanner.Tick();
        if (_worker != null)      _worker.Tick();

        _board.UpdateDebugDisplay();
    }

    void OnDisable()
    {
        if (_mind != null) _mind.StopThinking();
    }

    void OnDrawGizmosSelected() { }
}
