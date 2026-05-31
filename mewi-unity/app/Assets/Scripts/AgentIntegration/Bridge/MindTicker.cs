/*
    One responsibility: fire periodic jobs per cat
*/
using System;
using System.Collections.Generic;
using UnityEngine;

[RequireComponent(typeof(AgentNetworkManager))]
public class MindTicker : MonoBehaviour
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
    [SerializeField] AgentNetworkManager _bridge;
    [SerializeField] SnapshotManager     _snapshotManager;
    [SerializeField] CreatureWorker      _worker;

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
        if (_bridge == null)          _bridge          = GetComponent<AgentNetworkManager>();
        if (_snapshotManager == null) _snapshotManager = GetComponent<SnapshotManager>();
        if (_worker == null)          _worker          = GetComponentInChildren<CreatureWorker>();
        if (_worker == null)          _worker          = GetComponentInParent<CreatureWorker>();

        if (_bridge == null)
            Debug.LogError("[MindTicker] needs an AgentNetworkManager on the same GameObject.");
        if (_snapshotManager == null)
            Debug.LogError("[MindTicker] needs a SnapshotManager on the same GameObject.");
        if (_worker == null)
            Debug.LogWarning("[MindTicker] no CreatureWorker found; reports won't be flushed.");
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
            Debug.LogError("[MindTicker] StartTicking failed: Init was not called or CreatureConfig is missing.");
            return;
        }

        _board.EnableDirectiveMode();           // hand body control to the worker+FSM

        _tasks.Clear();
        Every("snapshot", _config.mindTickInterval, SendSnapshot);
        // Future domains register here, e.g. Every("journal", 30f, SyncJournal);

        _running = true;
        if (logTicks)
            Debug.Log($"[MindTicker] start; {_tasks.Count} job(s), snapshot every {_config.mindTickInterval:F1}s");
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
        if (_bridge == null || _snapshotManager == null) return;

        // Collect what the cat did since the last send.
        _worker?.FlushReport();
        if (_board.TryPopPlanExecutionReport(out var report))
            _pendingReport = report;

        // Backend still chewing on the last snapshot; the cat keeps moving meanwhile.
        if (_bridge.RequestInFlight) return;

        // Build fresh at the moment of sending — the freshest possible snapshot.
        string requestId = $"t{_tickCounter++:X8}";
        SnapshotPayload payload = _snapshotManager.BuildPayload(requestId);
        if (logTicks)
            Debug.Log($"[MindTicker] send {requestId} report={(_pendingReport != null ? _pendingReport.status : "none")}");
        if (_bridge.SendTick(_board.CreatureId, payload, _pendingReport))
            _pendingReport = null;
    }
}
