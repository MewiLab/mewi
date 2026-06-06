/*
    One responsibility: send periodic Unity snapshots to the backend.
*/
using System;
using System.Collections.Generic;
using UnityEngine;

public class SnapshotTicker : MonoBehaviour
{
    /// <summary>A periodic job: run <see cref="run"/> every <see cref="interval"/>
    /// realtime seconds. The body owns its own gating; the ticker only times it.</summary>
    sealed class TickTask
    {
        public string name;
        public float  interval;
        public float  nextAt;
        public Action run;
    }

    CreatureBlackboard _board;
    CreatureConfig     _config;
    [SerializeField] AgentNetworkHub _hub;
    [SerializeField] SnapshotManager     _snapshotManager;
    [SerializeField] CreatureMotorWorker _motorWorker;

    [Header("Debug")]
    [SerializeField] bool logTicks = true;

    readonly List<TickTask> _tasks = new List<TickTask>();
    bool _running;
    int  _tickCounter;
    PlanExecutionReport _pendingReport;

    public void Init(CreatureBlackboard board, CreatureConfig config)
    {
        _board  = board;
        _config = config;
        if (_hub == null)             _hub             = AgentNetworkHub.Resolve();
        if (_snapshotManager == null) _snapshotManager = GetComponent<SnapshotManager>();
        if (_motorWorker == null)     _motorWorker     = GetComponentInChildren<CreatureMotorWorker>();
        if (_motorWorker == null)     _motorWorker     = GetComponentInParent<CreatureMotorWorker>();

        if (_hub == null)
            Debug.LogError("[SnapshotTicker] needs one AgentNetworkHub in the scene.");
        if (_snapshotManager == null)
            Debug.LogError("[SnapshotTicker] needs a SnapshotManager on the same GameObject.");
        if (_motorWorker == null)
            Debug.LogWarning("[SnapshotTicker] no CreatureMotorWorker found; reports won't be flushed.");

        _hub?.RegisterCreature(_board != null ? _board.CreatureId : "");
    }

    /// <summary>Register a periodic job. <paramref name="interval"/> is realtime seconds.</summary>
    public void Every(string name, float interval, Action run)
    {
        if (run == null || interval <= 0f) return;
        _tasks.Add(new TickTask
        {
            name     = name,
            interval = interval,
            nextAt   = Time.unscaledTime + interval,
            run      = run,
        });
    }

    public void StartTicking()
    {
        if (_running) return;
        if (_config == null)
        {
            Debug.LogError("[SnapshotTicker] StartTicking failed: Init was not called or CreatureConfig is missing.");
            return;
        }

        _tasks.Clear();
        Every("snapshot", _config.mindTickInterval, SendSnapshot);
        // Future domains register here, e.g. Every("journal", 30f, SyncJournal);

        _running = true;
        if (logTicks)
            Debug.Log($"[SnapshotTicker] start; {_tasks.Count} job(s), snapshot every {_config.mindTickInterval:F1}s");
    }

    public void StopTicking() => _running = false;

    void Update()
    {
        if (!_running) return;

        float now = Time.unscaledTime;
        for (int i = 0; i < _tasks.Count; i++)
        {
            TickTask task = _tasks[i];
            if (now < task.nextAt) continue;
            task.nextAt = now + task.interval;
            task.run();
        }
    }

    // ───────────────────────── snapshot domain ─────────────────────────
    // Owns its own gating (skip while a request is in flight). The ticker above
    // is unaware of any of this.

    void SendSnapshot()
    {
        if (_hub == null) _hub = AgentNetworkHub.Resolve();
        if (_hub == null || _snapshotManager == null) return;

        // Collect what the cat did since the last send.
        _motorWorker?.FlushReport();
        while (_board.TryPopPlanExecutionReport(out var report))
            _pendingReport = PlanExecutionReport.Merge(_pendingReport, report);

        // Backend still chewing on the last snapshot; the cat keeps moving meanwhile.
        if (_hub.IsRequestInFlight(_board.CreatureId)) return;

        // Build fresh at the moment of sending — the freshest possible snapshot.
        string requestId = $"t{_tickCounter++:X8}";
        SnapshotPayload payload = _snapshotManager.BuildPayload(requestId);
        if (logTicks)
            Debug.Log($"[SnapshotTicker] send {requestId} report={(_pendingReport != null ? _pendingReport.status : "none")}");
        if (_hub.SendTick(_board.CreatureId, payload, _pendingReport))
            _pendingReport = null;
    }
}
