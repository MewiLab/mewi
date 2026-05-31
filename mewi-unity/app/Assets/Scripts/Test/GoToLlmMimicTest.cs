using System;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// Scene-side go_to test harness. Attach to a cat, assign target transforms,
/// and it will enqueue go_to intents through CreatureBlackboard like the LLM.
/// </summary>
[DisallowMultipleComponent]
public class GoToLlmMimicTest : MonoBehaviour
{
    [Serializable]
    public class GoToTarget
    {
        public string targetKey;
        public Transform target;
        public bool enabled = true;

        public string ResolveKey()
        {
            if (!string.IsNullOrWhiteSpace(targetKey))
                return targetKey.Trim();
            return target != null ? target.name : "";
        }
    }

    [Header("Creature")]
    [SerializeField] CreatureBlackboard blackboard;
    [SerializeField] CreatureWorker worker;

    [Tooltip("Call CreatureWorker.Init if this test starts before the normal controller path.")]
    [SerializeField] bool initializeWorker = true;

    [Tooltip("Tick the worker from this test. Keep this on for focused movement tests.")]
    [SerializeField] bool tickWorkerFromTest = true;

    [Tooltip("Disable PeriodicMind while this test is running so backend/LLM plans do not compete with it.")]
    [SerializeField] bool disablePeriodicMindWhileRunning = true;

    [Tooltip("Clear any existing LLM/simulated mind plan when the test starts.")]
    [SerializeField] bool clearExistingPlanOnStart = true;

    [Header("Targets")]
    [SerializeField] List<GoToTarget> targets = new List<GoToTarget>();
    [SerializeField] bool rememberAssignedTargets = true;
    [SerializeField] bool randomizeTargets;

    [Header("Loop")]
    [SerializeField] bool runOnStart = true;
    [SerializeField] bool loop = true;
    [SerializeField] float sendIntervalSeconds = 2f;
    [SerializeField] bool waitUntilWorkerIdle = true;
    [SerializeField] int maxSends = -1;

    [Header("Command Ids")]
    [SerializeField] string requestIdPrefix = "goto-test";
    [SerializeField] string commandIdPrefix = "goto-step";

    [Header("Hotkeys")]
    [SerializeField] KeyCode sendNowKey = KeyCode.G;
    [SerializeField] KeyCode toggleRunKey = KeyCode.T;
    [SerializeField] KeyCode clearPlanKey = KeyCode.C;

    [Header("Debug")]
    [SerializeField] bool logDispatch = true;
    [SerializeField] bool isRunning;
    [SerializeField] int nextTargetIndex;
    [SerializeField] int sendsIssued;
    [SerializeField] string lastQueued = "";
    [SerializeField] string lastStatus = "";

    MindTicker _periodicMind;
    CreatureController _controller;
    float _nextSendAt;
    bool _periodicMindWasEnabled;
    bool _periodicMindChanged;

    void Awake()
    {
        ResolveReferences();
    }

    void Start()
    {
        ResolveReferences();
        if (initializeWorker && worker != null && blackboard != null)
            worker.Init(blackboard);

        if (runOnStart)
            StartLoop();
    }

    void OnDisable()
    {
        RestorePeriodicMind();
    }

    void Update()
    {
        HandleHotkeys();

        if (isRunning && disablePeriodicMindWhileRunning)
            DisablePeriodicMind();

        if (tickWorkerFromTest && worker != null)
            worker.Tick();

        blackboard?.UpdateDebugDisplay();

        if (!isRunning) return;
        if (maxSends >= 0 && sendsIssued >= maxSends)
        {
            StopLoop();
            return;
        }

        if (waitUntilWorkerIdle && worker != null && worker.IsBusy)
        {
            lastStatus = "waiting:worker_busy";
            return;
        }

        if (blackboard != null && blackboard.HasMindPlan)
        {
            lastStatus = "waiting:mind_plan_active";
            return;
        }

        if (Time.time < _nextSendAt)
        {
            lastStatus = $"waiting:{_nextSendAt - Time.time:F1}s";
            return;
        }

        if (!SendNextGoTo())
        {
            StopLoop();
            return;
        }

        if (!loop && (maxSends < 0 || sendsIssued >= maxSends))
            StopLoop();
    }

    [ContextMenu("Start GoTo Loop")]
    public void StartLoop()
    {
        ResolveReferences();
        if (blackboard == null)
        {
            Debug.LogWarning("[GoToLlmMimicTest] Missing CreatureBlackboard.");
            return;
        }

        if (disablePeriodicMindWhileRunning)
            DisablePeriodicMind();

        if (clearExistingPlanOnStart)
            blackboard.ClearMindPlan();

        if (worker == null)
            Debug.LogWarning("[GoToLlmMimicTest] No CreatureWorker found; go_to intents will queue but nothing will move.");

        isRunning = true;
        _nextSendAt = Time.time;
        lastStatus = "running";
    }

    [ContextMenu("Stop GoTo Loop")]
    public void StopLoop()
    {
        isRunning = false;
        lastStatus = "stopped";
        RestorePeriodicMind();
    }

    [ContextMenu("Send Next GoTo Now")]
    public void SendNextGoToNow()
    {
        ResolveReferences();
        SendNextGoTo();
    }

    [ContextMenu("Clear Mind Plan")]
    public void ClearMindPlan()
    {
        blackboard?.ClearMindPlan();
        lastStatus = "cleared";
    }

    bool SendNextGoTo()
    {
        if (blackboard == null)
        {
            lastStatus = "missing_blackboard";
            return false;
        }

        if (!TryPickTarget(out GoToTarget slot, out int slotIndex))
        {
            lastStatus = "no_enabled_targets";
            return false;
        }

        string targetKey = slot.ResolveKey();
        Vector3 destination = slot.target != null ? slot.target.position : Vector3.zero;
        if (string.IsNullOrWhiteSpace(targetKey) && destination == Vector3.zero)
        {
            lastStatus = "target_missing_key_and_transform";
            return false;
        }

        if (rememberAssignedTargets && slot.target != null && !string.IsNullOrWhiteSpace(targetKey))
            blackboard.RememberPerceivedTarget(targetKey, slot.target);

        sendsIssued++;
        string requestId = $"{requestIdPrefix}-{sendsIssued:000}";
        string commandId = $"{commandIdPrefix}-{slotIndex:00}-{sendsIssued:000}";
        blackboard.SetMindIntent("go_to", destination, commandId, requestId, targetKey);

        lastQueued = string.IsNullOrWhiteSpace(targetKey)
            ? $"go_to {destination.ToString("F2")}"
            : $"go_to {targetKey}";
        lastStatus = "queued";

        if (logDispatch)
            Debug.Log($"[GoToLlmMimicTest] queued {lastQueued} commandId={commandId} requestId={requestId}");

        _nextSendAt = Time.time + Mathf.Max(0.1f, sendIntervalSeconds);
        return true;
    }

    bool TryPickTarget(out GoToTarget slot, out int slotIndex)
    {
        slot = null;
        slotIndex = -1;
        if (targets == null || targets.Count == 0)
            return false;

        if (randomizeTargets)
        {
            var enabledIndices = new List<int>();
            for (int i = 0; i < targets.Count; i++)
            {
                if (IsUsable(targets[i]))
                    enabledIndices.Add(i);
            }

            if (enabledIndices.Count == 0)
                return false;

            slotIndex = enabledIndices[UnityEngine.Random.Range(0, enabledIndices.Count)];
            slot = targets[slotIndex];
            nextTargetIndex = (slotIndex + 1) % targets.Count;
            return true;
        }

        for (int attempt = 0; attempt < targets.Count; attempt++)
        {
            int index = (nextTargetIndex + attempt) % targets.Count;
            if (!IsUsable(targets[index]))
                continue;

            slotIndex = index;
            slot = targets[index];
            nextTargetIndex = (index + 1) % targets.Count;
            return true;
        }

        return false;
    }

    static bool IsUsable(GoToTarget slot)
    {
        if (slot == null || !slot.enabled) return false;
        if (slot.target != null) return true;
        return !string.IsNullOrWhiteSpace(slot.targetKey);
    }

    void ResolveReferences()
    {
        if (blackboard == null)
            blackboard = GetComponent<CreatureBlackboard>()
                ?? GetComponentInParent<CreatureBlackboard>()
                ?? GetComponentInChildren<CreatureBlackboard>();

        if (worker == null)
            worker = GetComponent<CreatureWorker>()
                ?? GetComponentInParent<CreatureWorker>()
                ?? GetComponentInChildren<CreatureWorker>();

        if (_controller == null)
            _controller = GetComponent<CreatureController>()
                ?? GetComponentInParent<CreatureController>()
                ?? GetComponentInChildren<CreatureController>();

        if (_periodicMind == null)
            _periodicMind = GetComponent<MindTicker>()
                ?? GetComponentInParent<MindTicker>()
                ?? GetComponentInChildren<MindTicker>();
    }

    void DisablePeriodicMind()
    {
        if (_periodicMind == null) return;
        if (_periodicMindChanged)
        {
            _periodicMind.StopTicking();
            _periodicMind.enabled = false;
            return;
        }

        _periodicMindWasEnabled = _periodicMind.enabled;
        _periodicMind.StopTicking();
        _periodicMind.enabled = false;
        _periodicMindChanged = true;
    }

    void RestorePeriodicMind()
    {
        if (_periodicMind == null) return;
        if (!_periodicMindChanged) return;

        _periodicMind.enabled = _periodicMindWasEnabled;
        if (_periodicMindWasEnabled)
            _periodicMind.StartTicking();
        _periodicMindChanged = false;
    }

    void HandleHotkeys()
    {
        if (sendNowKey != KeyCode.None && Input.GetKeyDown(sendNowKey))
            SendNextGoToNow();

        if (toggleRunKey != KeyCode.None && Input.GetKeyDown(toggleRunKey))
        {
            if (isRunning) StopLoop();
            else StartLoop();
        }

        if (clearPlanKey != KeyCode.None && Input.GetKeyDown(clearPlanKey))
            ClearMindPlan();
    }

    void OnDrawGizmosSelected()
    {
        if (targets == null) return;

        Gizmos.color = Color.cyan;
        foreach (var slot in targets)
        {
            if (slot == null || slot.target == null || !slot.enabled)
                continue;

            Gizmos.DrawWireSphere(slot.target.position, 0.25f);
            if (transform != null)
                Gizmos.DrawLine(transform.position, slot.target.position);
        }
    }
}
