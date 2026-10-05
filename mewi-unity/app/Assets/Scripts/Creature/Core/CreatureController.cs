using UnityEngine;

public class CreatureController : MonoBehaviour
{
    [Header("config")]
    [Tooltip("Create via Assets > Create > Creature > Config")]
    public CreatureConfig  config;
    CreatureBlackboard     _board;
    CreaturePerception     _perception;
    SnapshotTicker         _snapshotTicker;
    AgentMessageDispatcher _dispatcher;
    CreatureIntentWorker   _intentWorker;
    CreatureMotorWorker    _motorWorker;
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
        _snapshotTicker = GetComponent<SnapshotTicker>();
        _dispatcher = GetComponent<AgentMessageDispatcher>();
        _intentWorker = GetComponent<CreatureIntentWorker>();
        _motorWorker  = GetComponent<CreatureMotorWorker>();
        _snapshot    = GetComponent<SnapshotManager>();
        _zoneScanner = GetComponent<ZoneScanner>();
        _traceEmitter = GetComponent<PresenceTraceEmitter>();

        if (_motorWorker == null) _motorWorker = GetComponentInChildren<CreatureMotorWorker>();
        if (_motorWorker == null) _motorWorker = GetComponentInParent<CreatureMotorWorker>();
        if (_dispatcher == null) _dispatcher = gameObject.AddComponent<AgentMessageDispatcher>();
        if (_intentWorker == null) _intentWorker = gameObject.AddComponent<CreatureIntentWorker>();

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

        if (_motorWorker == null)
            Debug.LogWarning("[CreatureController] Missing CreatureMotorWorker; mind plans can queue, but no body commands will be ticked.");

        if (_perception != null)      _perception.Init(_board, config);
        if (_snapshotTicker != null)  _snapshotTicker.Init(_board, config);
        if (_dispatcher != null)      _dispatcher.Init(_board);
        if (_intentWorker != null)    _intentWorker.Init(_board);
        if (_motorWorker != null)     _motorWorker.Init(_board);
        if (_snapshot != null)        _snapshot.Init(_board);
        if (_zoneScanner != null)     _zoneScanner.Init(_board);
        if (_traceEmitter != null) _traceEmitter.Init(_board);
        _selfStatus.Init(_board, config);
    }

    /// <summary>
    /// SnapshotTicker has its own timer
    /// It drives itself via a coroutine (WaitForSecondsRealtime) rather than Update()
    /// </summary>
    void Start()
    {
        if (_snapshotTicker != null) _snapshotTicker.StartTicking();
    }

    void Update()
    {
        _selfStatus.Tick(Time.deltaTime);
        if (_zoneScanner != null) _zoneScanner.Tick();
        if (_traceEmitter != null) _traceEmitter.Tick();
        if (_perception != null)  _perception.Tick();
        if (_intentWorker != null) _intentWorker.Tick();
        if (_motorWorker != null)  _motorWorker.Tick();

        _board.UpdateDebugDisplay();
    }

    void OnDisable()
    {
        if (_snapshotTicker != null) _snapshotTicker.StopTicking();
        if (_intentWorker != null) _intentWorker.StopWorking();
    }

    void OnDrawGizmosSelected() { }
}
