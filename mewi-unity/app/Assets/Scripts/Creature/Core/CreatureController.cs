using UnityEngine;

public class CreatureController : MonoBehaviour
{
    [Header("config")]
    [Tooltip("Create via Assets > Create > Creature > Config")]
    public CreatureConfig  config;
    CreatureBlackboard     _board;
    CreaturePerception     _perception;
    MindTicker             _mind;
    CreatureWorker         _worker;
    SnapshotManager        _snapshot;
    ZoneScanner            _zoneScanner;
    PresenceTraceEmitter   _traceEmitter;
    readonly CreatureSelfStatus _selfStatus = new CreatureSelfStatus();

    /// <summary>
    /// DI, Initialization order is clear and testable without Unity magic.
    /// </summary>
    void Awake()
    {
        _board       = GetComponent<CreatureBlackboard>();
        _perception  = GetComponent<CreaturePerception>();
        _mind        = GetComponent<MindTicker>();
        _worker      = GetComponent<CreatureWorker>();
        _snapshot    = GetComponent<SnapshotManager>();
        _zoneScanner = GetComponent<ZoneScanner>();
        _traceEmitter = GetComponent<PresenceTraceEmitter>();

        if (_worker == null) _worker = GetComponentInChildren<CreatureWorker>();
        if (_worker == null) _worker = GetComponentInParent<CreatureWorker>();

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

        if (_worker == null)
            Debug.LogWarning("[CreatureController] Missing CreatureWorker; mind plans can queue, but no body commands will be ticked.");

        if (_perception != null)  _perception.Init(_board, config);
        if (_mind != null)        _mind.Init(_board, config);
        if (_worker != null)      _worker.Init(_board);
        if (_snapshot != null)    _snapshot.Init(_board);
        if (_zoneScanner != null) _zoneScanner.Init(_board);
        if (_traceEmitter != null) _traceEmitter.Init(_board);
        _selfStatus.Init(_board, config);
    }

    /// <summary>
    /// PeriodicMind has its own timer
    /// It drives itself via a coroutine (WaitForSecondsRealtime) rather than Update()
    /// </summary>
    void Start()
    {
        if (_mind != null) _mind.StartTicking();
    }

    void Update()
    {
        _selfStatus.Tick(Time.deltaTime);
        if (_zoneScanner != null) _zoneScanner.Tick();
        if (_traceEmitter != null) _traceEmitter.Tick();
        if (_perception != null)  _perception.Tick();
        if (_worker != null)      _worker.Tick();

        _board.UpdateDebugDisplay();
    }

    void OnDisable()
    {
        if (_mind != null) _mind.StopTicking();
    }

    void OnDrawGizmosSelected() { }
}
