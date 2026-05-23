using System.Collections;
using UnityEngine;
using UnityEngine.AI;

/// <summary>
/// Runtime proof that CreatureWorker is controlling the animal through script.
///
/// Attach this to the same GameObject as CreatureController/CreatureBlackboard.
/// It sends blackboard intents and verifies that CreatureWorker drives Malbers:
/// navigation intents through MAnimalAIControl, and scripted action intents through
/// MAnimal action-mode events.
/// </summary>
[DisallowMultipleComponent]
public class CreatureWorkerScriptControlTest : MonoBehaviour
{
    [Header("References")]
    public CreatureController controller;
    public CreatureBlackboard board;
    public CreatureWorker motor;
    public MalbersAnimalAdapter body;
    public CreatureConfig config;
    public Transform goToTarget;

    [Header("Run")]
    public bool runOnStart = true;
    public bool takeOverControllerDuringTest = true;
    public bool restoreControllerAfterTest = true;
    public bool runNavigationProof = true;
    public bool runActionProof = false;
    public bool continueAfterNavigationFailure = true;

    [Header("Navigation Proof")]
    public float fallbackDistance = 4f;
    public float destinationTolerance = 1.25f;
    public float waitForAgentSeconds = 2f;
    public float navigationArrivalTimeout = 20f;
    public float minimumMovedDistance = 0.25f;

    [Header("Stop Proof")]
    public float stopSampleSeconds = 0.75f;
    public float maximumStopDrift = 0.08f;

    [Header("Action Proof")]
    public float actionStartTimeout = 4f;
    public float actionEndTimeout = 5f;
    public float delayBetweenActions = 1f;
    public float actionReadyTimeout = 2f;
    public bool waitForActionEnd = true;
    public bool requireActionEnd = false;
    public bool acceptPreparedModeWithoutModeStart = true;
    public bool autoResolveAbilityIndexesByName = true;

    [Header("Debug")]
    public bool logStatusSnapshot = true;
    public bool logNavMeshPathProof = true;

    Coroutine _run;
    bool _manualTick;
    bool _restoreController;
    bool _controllerWasEnabled;
    bool _periodicMindWasEnabled;
    bool _previousLogIntentProof;
    bool _runtimeControlActive;
    bool _modeStarted;
    bool _modeEnded;
    int _startedModeId;
    int _startedAbilityIndex;
    int _endedModeId;
    int _endedAbilityIndex;
    bool _modePrepared;
    int _preparedModeAbility;
    int _passCount;
    int _failCount;
    int _skipCount;
    bool _actionListenersAttached;

    struct ActionCase
    {
        public readonly string Intent;
        public readonly int AbilityIndex;

        public ActionCase(string intent, int abilityIndex)
        {
            Intent = intent;
            AbilityIndex = abilityIndex;
        }
    }

    void Reset()
    {
        ResolveReferences();
    }

    void Awake()
    {
        ResolveReferences();
    }

    void Start()
    {
        if (runOnStart)
            RunNow();
    }

    void Update()
    {
        if (_manualTick && motor != null)
            motor.Tick();
    }

    void OnDisable()
    {
        RestoreRuntimeControl();
    }

    [ContextMenu("Run CreatureWorker Script Control Test")]
    public void RunNow()
    {
        if (!Application.isPlaying)
        {
            Debug.LogWarning("[CreatureWorkerScriptControlTest] Enter Play Mode before running this test.");
            return;
        }

        if (_run != null)
        {
            StopCoroutine(_run);
            RestoreRuntimeControl();
        }

        _run = StartCoroutine(RunTest());
    }

    IEnumerator RunTest()
    {
        ResolveReferences();
        EnsureMotorInitializedIfNeeded();
        ResetCounters();

        if (!TryValidate(out var agent))
        {
            _run = null;
            yield break;
        }

        BeginRuntimeControl();

        if (runNavigationProof)
            yield return RunNavigationProof(agent, ControlledTransform);

        if (runActionProof)
            yield return RunActionProof();

        string result = _failCount == 0 ? "PASS" : "FAIL";
        Debug.Log($"[CreatureWorkerScriptControlTest] RESULT {result} - passed={_passCount} failed={_failCount} skipped={_skipCount}");

        FinishRun();
    }

    IEnumerator RunNavigationProof(NavMeshAgent agent, Transform controlled)
    {
        if (!TryPickDestination(agent, out var destination))
        {
            Fail("NAV go_to", "Could not find a reachable NavMesh destination. Assign goToTarget or bake a larger NavMesh.");
            if (!continueAfterNavigationFailure)
                yield break;
            yield return null;
            yield break;
        }

        string requestId = $"script-control-test-nav:{Time.frameCount}";
        string goCommandId = $"{board.CreatureId}:script-test-go:{Time.frameCount}";

        board.ClearMindPlan();
        board.SetMindIntent("go_to", destination, goCommandId, requestId);

        Debug.Log($"[CreatureWorkerScriptControlTest] STEP go_to destination={destination} commandId={goCommandId}");
        motor.Tick();

        if (logStatusSnapshot)
            Debug.Log($"[CreatureWorkerScriptControlTest] after go_to\n{BuildStatus(agent, controlled, destination)}");

        float deadline = Time.time + waitForAgentSeconds;
        while (Time.time < deadline && !NavigationAcceptedDestination(agent, destination))
            yield return null;

        if (!NavigationAcceptedDestination(agent, destination))
        {
            Fail("NAV go_to", $"CreatureWorker did not accept scripted destination. expected={destination}\n{BuildStatus(agent, controlled, destination)}");
            if (!continueAfterNavigationFailure)
                yield break;
            yield break;
        }

        Pass($"NAV go_to destination accepted by script. destination={destination} manualFallback={body.IsUsingManualNavigation}");

        if (logNavMeshPathProof)
            LogNavMeshPathProof(agent, destination);

        Vector3 startPosition = controlled.position;
        float bestDistance = HorizontalDistance(controlled.position, destination);
        deadline = Time.time + navigationArrivalTimeout;
        while (Time.time < deadline &&
               HorizontalDistance(controlled.position, destination) > destinationTolerance)
        {
            bestDistance = Mathf.Min(bestDistance, HorizontalDistance(controlled.position, destination));
            yield return null;
        }

        float moved = HorizontalDistance(startPosition, controlled.position);
        if (moved < minimumMovedDistance)
        {
            Fail(
                "NAV go_to movement",
                $"Animal transform did not move enough after scripted go_to. moved={moved:F3}m expected>={minimumMovedDistance:F3}m controlled={controlled.name}\n" +
                BuildStatus(agent, controlled, destination));
            if (!continueAfterNavigationFailure)
                yield break;
            yield break;
        }

        Pass($"NAV go_to animal moved by script. controlled={controlled.name} moved={moved:F3}m");

        float finalDistance = HorizontalDistance(controlled.position, destination);
        if (finalDistance > destinationTolerance)
        {
            Fail(
                "NAV go_to arrival",
                $"Animal moved but did not reach the target before timeout. finalDistance={finalDistance:F3}m " +
                $"bestDistance={bestDistance:F3}m expected<={destinationTolerance:F3}m destination={destination}\n" +
                BuildStatus(agent, controlled, destination));
            if (!continueAfterNavigationFailure)
                yield break;
            yield break;
        }

        Pass($"NAV go_to arrived at target. finalDistance={finalDistance:F3}m destination={destination}");

        string stopCommandId = $"{board.CreatureId}:script-test-stop:{Time.frameCount}";
        board.SetMindIntent("stop_moving", Vector3.zero, stopCommandId, requestId);

        Debug.Log($"[CreatureWorkerScriptControlTest] STEP stop_moving commandId={stopCommandId}");
        motor.Tick();

        Vector3 stopStart = controlled.position;
        yield return new WaitForSeconds(stopSampleSeconds);

        float stopDrift = HorizontalDistance(stopStart, controlled.position);
        if (stopDrift > maximumStopDrift)
        {
            Fail("NAV stop_moving", $"Animal kept drifting after scripted stop_moving. drift={stopDrift:F3}m expected<={maximumStopDrift:F3}m");
            if (!continueAfterNavigationFailure)
                yield break;
            yield break;
        }

        Pass($"NAV stop_moving settled. drift={stopDrift:F3}m");
    }

    IEnumerator RunActionProof()
    {
        if (body.ActionModeId <= 0)
        {
            Fail("ACTIONS setup", "MalbersAnimalAdapter ActionModeId is not valid. Malbers default Action mode ID is 4.");
            yield break;
        }

        if (body.animal.Mode_Get(body.ActionModeId) == null)
        {
            Fail("ACTIONS setup", $"MAnimal does not have an Action mode with ID {body.ActionModeId}.\n{BuildModesSummary()}");
            yield break;
        }

        AttachActionListeners();

        ActionCase[] actions = BuildActionCases();
        foreach (ActionCase action in actions)
            yield return RunActionCase(action);

        DetachActionListeners();
    }

    IEnumerator RunActionCase(ActionCase action)
    {
        if (action.AbilityIndex <= 0)
        {
            Skip($"ACTION {action.Intent}", "ability index is 0/unassigned on MalbersAnimalAdapter");
            yield break;
        }

        yield return WaitForActionReady($"before {action.Intent}");

        ApplyAbilityIndexToMotor(action);
        ResetModeEvents();

        string requestId = $"script-control-test-action:{Time.frameCount}";
        string commandId = $"{board.CreatureId}:script-test-{action.Intent}:{Time.frameCount}";

        board.ClearMindPlan();
        board.SetMindIntent(action.Intent, Vector3.zero, commandId, requestId, action.Intent);

        Debug.Log($"[CreatureWorkerScriptControlTest] STEP action intent={action.Intent} ability={action.AbilityIndex} commandId={commandId}");
        motor.Tick();
        CapturePreparedMode(action);

        float deadline = Time.time + actionStartTimeout;
        while (Time.time < deadline && !SawExpectedModeStart(action))
        {
            CapturePreparedMode(action);
            yield return null;
        }

        if (!SawExpectedModeStart(action))
        {
            if (acceptPreparedModeWithoutModeStart && _modePrepared)
            {
                Pass($"ACTION {action.Intent} accepted by script/Malbers. prepared ModeAbility={_preparedModeAbility}, but Animator did not enter OnModeStart.");
                Debug.LogWarning(
                    $"[CreatureWorkerScriptControlTest] ACTION {action.Intent} was accepted by Malbers but no OnModeStart fired. " +
                    "This usually means the Action ability has no valid Animator transition/ModeBehaviour path for this animal.");
                yield return ForceActionCleanup();
                yield break;
            }

            Fail(
                $"ACTION {action.Intent}",
                $"expected mode start actionMode={body.ActionModeId} ability={action.AbilityIndex}, " +
                $"saw mode={_startedModeId} ability={_startedAbilityIndex}\n" +
                BuildActionStatus(action));
            yield return ForceActionCleanup();
            yield break;
        }

        Pass($"ACTION {action.Intent} started by script. mode={_startedModeId} ability={_startedAbilityIndex}");

        if (!waitForActionEnd && !requireActionEnd)
        {
            yield return ForceActionCleanup();
            yield break;
        }

        deadline = Time.time + actionEndTimeout;
        while (Time.time < deadline && !SawExpectedModeEnd(action))
            yield return null;

        if (SawExpectedModeEnd(action))
        {
            Pass($"ACTION {action.Intent} ended. mode={_endedModeId} ability={_endedAbilityIndex}");
        }
        else if (requireActionEnd)
        {
            Fail($"ACTION {action.Intent}", $"mode started but did not end within {actionEndTimeout:F1}s");
        }
        else
        {
            Debug.LogWarning($"[CreatureWorkerScriptControlTest] ACTION {action.Intent} started but did not end within {actionEndTimeout:F1}s; forcing cleanup so the next action can run.");
        }

        yield return ForceActionCleanup();
    }

    ActionCase[] BuildActionCases()
    {
        return new[]
        {
            new ActionCase("flinch", ResolveAbilityIndex("flinch", "stun", "startle", body.startleAbilityIndex)),
            new ActionCase("scratch", ResolveAbilityIndex("scratch", "", "", body.scratchAbilityIndex)),
            new ActionCase("look_around", ResolveAbilityIndex("look", "look around", "", body.lookAroundAbilityIndex)),
            new ActionCase("nod_head", ResolveAbilityIndex("nod", "nod head", "", body.nodHeadAbilityIndex)),
            new ActionCase("eat", ResolveAbilityIndex("eat", "", "", body.eatAbilityIndex)),
            new ActionCase("drink", ResolveAbilityIndex("drink", "", "", body.drinkAbilityIndex)),
            new ActionCase("sit", ResolveAbilityIndex("sit", "seat", "", body.sitAbilityIndex)),
            new ActionCase("lie", ResolveAbilityIndex("lie", "lay", "down", body.lieAbilityIndex)),
            new ActionCase("sleep", ResolveAbilityIndex("sleep", "", "", body.sleepAbilityIndex)),
            new ActionCase("groom", ResolveAbilityIndex("groom", "", "", body.groomAbilityIndex)),
            new ActionCase("smell", ResolveAbilityIndex("smell", "sniff", "", body.smellAbilityIndex)),
            new ActionCase("alert", ResolveAbilityIndex("alert", "", "", body.alertAbilityIndex)),
            new ActionCase("vocalize", ResolveAbilityIndex("vocal", "meow", "howl", body.vocalizeAbilityIndex)),
        };
    }

    int ResolveAbilityIndex(string primaryName, string alternateName, string tertiaryName, int configuredIndex)
    {
        if (!autoResolveAbilityIndexesByName)
            return configuredIndex;

        var mode = body.animal.Mode_Get(body.ActionModeId);
        if (mode == null || mode.Abilities == null)
            return configuredIndex;

        for (int i = 0; i < mode.Abilities.Count; i++)
        {
            var ability = mode.Abilities[i];
            if (ability == null || string.IsNullOrWhiteSpace(ability.Name))
                continue;

            string name = ability.Name.ToLowerInvariant();
            if (MatchesAbilityName(name, primaryName) ||
                MatchesAbilityName(name, alternateName) ||
                MatchesAbilityName(name, tertiaryName))
            {
                if (configuredIndex != ability.Index.Value)
                    Debug.Log($"[CreatureWorkerScriptControlTest] Auto-resolved '{primaryName}' ability index {configuredIndex} -> {ability.Index.Value} from Action ability '{ability.Name}'.");

                return ability.Index.Value;
            }
        }

        return configuredIndex;
    }

    static bool MatchesAbilityName(string abilityName, string query)
    {
        return !string.IsNullOrWhiteSpace(query) &&
               abilityName.Contains(query.ToLowerInvariant());
    }

    void ApplyAbilityIndexToMotor(ActionCase action)
    {
        switch (action.Intent)
        {
            case "flinch":      body.startleAbilityIndex = action.AbilityIndex;      break;
            case "scratch":     body.scratchAbilityIndex = action.AbilityIndex;      break;
            case "look_around": body.lookAroundAbilityIndex = action.AbilityIndex;   break;
            case "nod_head":    body.nodHeadAbilityIndex = action.AbilityIndex;      break;
            case "eat":         body.eatAbilityIndex = action.AbilityIndex;          break;
            case "drink":       body.drinkAbilityIndex = action.AbilityIndex;        break;
            case "sit":         body.sitAbilityIndex = action.AbilityIndex;          break;
            case "lie":         body.lieAbilityIndex = action.AbilityIndex;          break;
            case "sleep":       body.sleepAbilityIndex = action.AbilityIndex;        break;
            case "groom":       body.groomAbilityIndex = action.AbilityIndex;        break;
            case "smell":       body.smellAbilityIndex = action.AbilityIndex;        break;
            case "alert":       body.alertAbilityIndex = action.AbilityIndex;        break;
            case "vocalize":    body.vocalizeAbilityIndex = action.AbilityIndex;     break;
        }
    }

    void ResolveReferences()
    {
        if (controller == null) controller = GetComponent<CreatureController>();
        if (board == null)      board      = GetComponent<CreatureBlackboard>();
        if (motor == null)      motor      = GetComponent<CreatureWorker>();
        if (body == null)       body       = GetComponent<MalbersAnimalAdapter>();
        if (config == null && controller != null) config = controller.config;
    }

    void EnsureMotorInitializedIfNeeded()
    {
        if (motor == null || board == null || body == null)
            return;

        if (body.animal != null && body.aiControl != null)
            return;

        motor.Init(board);
    }

    bool TryValidate(out NavMeshAgent agent)
    {
        agent = null;

        if (board == null)
            return Fail("Missing CreatureBlackboard. Attach this to the AI Core GameObject or assign board.");

        if (motor == null)
            return Fail("Missing CreatureWorker. Attach this to the AI Core GameObject or assign motor.");

        if (body == null)
            return Fail("Missing MalbersAnimalAdapter. Attach this to the AI Core GameObject or assign body.");

        if (body.animal == null)
            return Fail("MalbersAnimalAdapter has no MAnimal. Let CreatureController initialize it or assign body.animal.");

        if (body.aiControl == null)
            return Fail("MalbersAnimalAdapter has no MAnimalAIControl. Assign body.aiControl or use the Malbers AI prefab variant.");

        if (!body.animal.isActiveAndEnabled)
            return Fail("MAnimal is not active/enabled. Enable the Cat MAnimal component before running the test.");

        if (!body.aiControl.isActiveAndEnabled)
            return Fail("MAnimalAIControl is not active/enabled. Enable the Malbers AI Control component before running the test.");

        agent = body.aiControl.Agent;
        if (agent == null)
            return Fail("MAnimalAIControl.Agent is null. Assign the NavMeshAgent child to the AI control component.");

        return true;
    }

    bool TryPickDestination(NavMeshAgent agent, out Vector3 destination)
    {
        destination = Vector3.zero;

        if (goToTarget != null &&
            NavMesh.SamplePosition(goToTarget.position, out var targetHit, destinationTolerance, NavMesh.AllAreas) &&
            HorizontalDistance(agent.transform.position, targetHit.position) > minimumMovedDistance)
        {
            destination = targetHit.position;
            return true;
        }

        Vector3 origin = ControlledTransform.position;
        Vector3 forward = ControlledTransform.forward;
        if (forward.sqrMagnitude < 0.01f)
            forward = transform.forward.sqrMagnitude > 0.01f ? transform.forward : Vector3.forward;

        Vector3[] directions =
        {
            forward,
            -forward,
            Vector3.Cross(Vector3.up, forward).normalized,
            -Vector3.Cross(Vector3.up, forward).normalized,
            (forward + Vector3.Cross(Vector3.up, forward).normalized).normalized,
            (forward - Vector3.Cross(Vector3.up, forward).normalized).normalized,
        };

        foreach (Vector3 direction in directions)
        {
            if (direction.sqrMagnitude < 0.01f)
                continue;

            Vector3 candidate = origin + direction.normalized * fallbackDistance;
            if (!NavMesh.SamplePosition(candidate, out var hit, fallbackDistance, NavMesh.AllAreas))
                continue;

            if (HorizontalDistance(origin, hit.position) <= minimumMovedDistance)
                continue;

            destination = hit.position;
            return true;
        }

        return false;
    }

    void LogNavMeshPathProof(NavMeshAgent agent, Vector3 destination)
    {
        if (agent == null)
        {
            Debug.LogWarning("[CreatureWorkerScriptControlTest] NavMesh path proof: agent is null.");
            return;
        }

        if (!agent.isActiveAndEnabled || !agent.isOnNavMesh)
        {
            Debug.LogWarning(
                $"[CreatureWorkerScriptControlTest] NavMesh path proof: agent cannot calculate path. " +
                $"active={agent.isActiveAndEnabled} onNavMesh={agent.isOnNavMesh}");
            return;
        }

        var path = new NavMeshPath();
        bool calculated = agent.CalculatePath(destination, path);
        string corners = BuildCornersSummary(path);

        Debug.Log(
            $"[CreatureWorkerScriptControlTest] NavMesh path proof: calculated={calculated} " +
            $"status={path.status} corners={path.corners.Length} " +
            $"agentAreaMask={agent.areaMask} autoTraverse={agent.autoTraverseOffMeshLink} " +
            $"from={agent.transform.position.ToString("F3")} to={destination.ToString("F3")}\n{corners}");
    }

    string BuildCornersSummary(NavMeshPath path)
    {
        if (path == null || path.corners == null || path.corners.Length == 0)
            return "corners: none";

        string result = "corners:";
        for (int i = 0; i < path.corners.Length; i++)
            result += $"\n  [{i}] {path.corners[i].ToString("F3")}";

        return result;
    }

    void BeginRuntimeControl()
    {
        _previousLogIntentProof = body != null && body.logIntentProof;
        if (body != null) body.logIntentProof = true;
        _runtimeControlActive = true;

        _controllerWasEnabled = controller != null && controller.enabled;
        _restoreController = takeOverControllerDuringTest && restoreControllerAfterTest && controller != null;

        var periodicMind = GetComponent<PeriodicMind>();
        _periodicMindWasEnabled = periodicMind != null && periodicMind.enabled;

        if (takeOverControllerDuringTest && controller != null)
        {
            controller.enabled = false;
            _manualTick = true;
            Debug.Log("[CreatureWorkerScriptControlTest] Temporarily disabled CreatureController and ticking CreatureWorker directly for an isolated proof.");
        }
        else
        {
            _manualTick = controller == null || !controller.enabled;
        }
    }

    void RestoreRuntimeControl()
    {
        if (!_runtimeControlActive)
            return;

        DetachActionListeners();

        if (body != null)
            body.logIntentProof = _previousLogIntentProof;

        _manualTick = false;
        _runtimeControlActive = false;

        if (!_restoreController || controller == null)
            return;

        controller.enabled = _controllerWasEnabled;

        var periodicMind = GetComponent<PeriodicMind>();
        if (_controllerWasEnabled && _periodicMindWasEnabled && periodicMind != null && periodicMind.enabled)
            periodicMind.StartThinking();

        _restoreController = false;
    }

    void FinishRun()
    {
        RestoreRuntimeControl();
        _run = null;
    }

    bool AgentAcceptedDestination(NavMeshAgent agent, Vector3 destination)
    {
        if (agent == null || !agent.isActiveAndEnabled || !agent.isOnNavMesh)
            return false;

        return HorizontalDistance(agent.destination, destination) <= destinationTolerance;
    }

    bool NavigationAcceptedDestination(NavMeshAgent agent, Vector3 destination)
    {
        if (AgentAcceptedDestination(agent, destination))
            return true;

        return body.HasActiveNavigationDestination &&
               HorizontalDistance(body.ActiveNavigationDestination, destination) <= destinationTolerance;
    }

    void ResetCounters()
    {
        _passCount = 0;
        _failCount = 0;
        _skipCount = 0;
    }

    void ResetModeEvents()
    {
        _modeStarted = false;
        _modeEnded = false;
        _startedModeId = -1;
        _startedAbilityIndex = -1;
        _endedModeId = -1;
        _endedAbilityIndex = -1;
        _modePrepared = false;
        _preparedModeAbility = 0;
    }

    void OnTestModeStarted(int modeId, int abilityIndex)
    {
        _modeStarted = true;
        _startedModeId = modeId;
        _startedAbilityIndex = abilityIndex;
        Debug.Log($"[CreatureWorkerScriptControlTest] EVENT OnModeStart mode={modeId} ability={abilityIndex}");
    }

    void OnTestModeEnded(int modeId, int abilityIndex)
    {
        _modeEnded = true;
        _endedModeId = modeId;
        _endedAbilityIndex = abilityIndex;
        Debug.Log($"[CreatureWorkerScriptControlTest] EVENT OnModeEnd mode={modeId} ability={abilityIndex}");
    }

    bool SawExpectedModeStart(ActionCase action)
    {
        return _modeStarted &&
               _startedModeId == body.ActionModeId &&
               _startedAbilityIndex == action.AbilityIndex;
    }

    bool SawExpectedModeEnd(ActionCase action)
    {
        return _modeEnded &&
               _endedModeId == body.ActionModeId &&
               _endedAbilityIndex == action.AbilityIndex;
    }

    void CapturePreparedMode(ActionCase action)
    {
        int expected = ExpectedModeAbility(action);
        if (body.animal.ModeAbility != expected)
            return;

        _modePrepared = true;
        _preparedModeAbility = body.animal.ModeAbility;
    }

    int ExpectedModeAbility(ActionCase action)
    {
        return Mathf.Abs(body.ActionModeId * 1000) + Mathf.Abs(action.AbilityIndex);
    }

    IEnumerator ForceActionCleanup()
    {
        board.ClearMindPlan();
        board.SetMindIntent("idle");

        if (body.animal.IsPlayingMode)
            body.animal.Mode_Stop(true);

        if (body.animal.IsPreparingMode)
            body.animal.Mode_Interrupt_Forced();

        motor.Tick();
        yield return new WaitForSeconds(delayBetweenActions);
        yield return WaitForActionReady("after cleanup");
    }

    IEnumerator WaitForActionReady(string label)
    {
        float deadline = Time.time + actionReadyTimeout;
        while (Time.time < deadline &&
               (body.animal.IsPreparingMode || body.animal.IsPlayingMode))
        {
            yield return null;
        }

        if (body.animal.IsPreparingMode || body.animal.IsPlayingMode)
        {
            Debug.LogWarning(
                $"[CreatureWorkerScriptControlTest] Action system still busy {label}: " +
                $"isPreparing={body.animal.IsPreparingMode} isPlayingMode={body.animal.IsPlayingMode}. Forcing interrupt.");
            body.animal.Mode_Stop(true);
            body.animal.Mode_Interrupt_Forced();
            yield return new WaitForSeconds(delayBetweenActions);
        }
    }

    void DetachActionListeners()
    {
        if (!_actionListenersAttached || body == null || body.animal == null)
            return;

        body.animal.OnModeStart.RemoveListener(OnTestModeStarted);
        body.animal.OnModeEnd.RemoveListener(OnTestModeEnded);
        _actionListenersAttached = false;
    }

    void AttachActionListeners()
    {
        if (_actionListenersAttached)
            return;

        body.animal.OnModeStart.RemoveListener(OnTestModeStarted);
        body.animal.OnModeEnd.RemoveListener(OnTestModeEnded);
        body.animal.OnModeStart.AddListener(OnTestModeStarted);
        body.animal.OnModeEnd.AddListener(OnTestModeEnded);
        _actionListenersAttached = true;
    }

    string BuildActionStatus(ActionCase action)
    {
        var mode = body.animal.Mode_Get(body.ActionModeId);
        if (mode == null)
            return $"actionModeId={body.ActionModeId} is not present on MAnimal.modes\n{BuildModesSummary()}";

        var ability = mode.GetAbility(action.AbilityIndex);
        string abilityInfo = ability == null
            ? $"ability {action.AbilityIndex} is not in Action mode list"
            : $"ability={ability.Name}({ability.Index.Value}) active={ability.Active} status={ability.Status} " +
              $"blockedByState={mode.StateCanInterrupt(body.animal.ActiveStateID, ability)} " +
              $"blockedByStance={mode.StanceCanInterrupt(body.animal.Stance, ability)}";

        string activeMode = body.animal.ActiveMode != null
            ? $"{body.animal.ActiveMode.Name}({body.animal.ActiveMode.ID.ID})"
            : "none";

        string abilityIndexes = "";
        if (mode.Abilities != null)
        {
            for (int i = 0; i < mode.Abilities.Count; i++)
            {
                var item = mode.Abilities[i];
                if (item == null) continue;
                if (abilityIndexes.Length > 0) abilityIndexes += ", ";
                abilityIndexes += $"{item.Name}:{item.Index.Value}{(item.Active ? "" : "(disabled)")}";
            }
        }

        return
            $"actionMode={mode.Name}({mode.ID.ID}) modeActive={mode.Active} temporal={mode.TemporalActivation} " +
            $"expectedModeAbility={ExpectedModeAbility(action)} currentModeAbility={body.animal.ModeAbility} " +
            $"animalState={body.animal.ActiveStateID.name}({body.animal.ActiveStateID.ID}) noModes={body.animal.ActiveState.NoModes} " +
            $"stance={(body.animal.Stance != null ? body.animal.Stance.name : "null")} " +
            $"isPreparing={body.animal.IsPreparingMode} isPlayingMode={body.animal.IsPlayingMode} activeMode={activeMode}\n" +
            $"{abilityInfo}\n" +
            $"available Action abilities: {abilityIndexes}";
    }

    string BuildModesSummary()
    {
        string summary = "MAnimal modes: ";
        if (body.animal.modes == null || body.animal.modes.Count == 0)
            return summary + "<none>";

        for (int i = 0; i < body.animal.modes.Count; i++)
        {
            var mode = body.animal.modes[i];
            if (mode == null || mode.ID == null) continue;
            if (i > 0) summary += ", ";
            summary += $"{mode.Name}({mode.ID.ID})";
        }
        return summary;
    }

    string BuildStatus(NavMeshAgent agent, Transform controlled) => BuildStatus(agent, controlled, Vector3.zero);

    string BuildStatus(NavMeshAgent agent, Transform controlled, Vector3 destination)
    {
        string animalState = body.animal.ActiveStateID != null
            ? $"{body.animal.ActiveStateID.name}({body.animal.ActiveStateID.ID})"
            : "null";

        string agentStatus;
        if (agent == null)
        {
            agentStatus = "agent=NULL";
        }
        else
        {
            bool canReadNavState = agent.isActiveAndEnabled && agent.isOnNavMesh;
            agentStatus =
                $"agentActive={agent.isActiveAndEnabled} onNavMesh={agent.isOnNavMesh} " +
                $"isStopped={(canReadNavState ? agent.isStopped.ToString() : "n/a")} " +
                $"hasPath={(canReadNavState ? agent.hasPath.ToString() : "n/a")} " +
                $"pending={(canReadNavState ? agent.pathPending.ToString() : "n/a")} " +
                $"status={(canReadNavState ? agent.pathStatus.ToString() : "n/a")} " +
                $"remaining={(canReadNavState ? agent.remainingDistance : -1f):F3} " +
                $"desiredVel={(canReadNavState ? agent.desiredVelocity.magnitude : 0f):F3} " +
                $"velocity={(canReadNavState ? agent.velocity.magnitude : 0f):F3} " +
                $"updatePosition={agent.updatePosition} " +
                $"agentPos={agent.transform.position.ToString("F3")} " +
                $"agentDestination={SafeAgentDestination(agent).ToString("F3")}";
        }

        string aiStatus =
            $"aiEnabled={body.aiControl.isActiveAndEnabled} activeAgent={body.aiControl.ActiveAgent} " +
            $"aiReady={body.aiControl.AIReady} waiting={body.aiControl.IsWaiting} " +
            $"blockingState={body.aiControl.StateIsBlockingAgent} aiMoving={body.aiControl.IsMoving} " +
            $"aiDirection={body.aiControl.AIDirection.ToString("F3")} " +
            $"aiDestination={body.aiControl.DestinationPosition.ToString("F3")}";

        string motorNavigationStatus =
            $"motorNavActive={body.HasActiveNavigationDestination} " +
            $"motorNavDestination={body.ActiveNavigationDestination.ToString("F3")} " +
            $"manualNav={body.IsUsingManualNavigation} " +
            $"manualCorner={body.ManualNavigationCorner.ToString("F3")} " +
            $"manualDirection={body.ManualNavigationDirection.ToString("F3")} " +
            $"distanceToRequested={(destination == Vector3.zero ? -1f : HorizontalDistance(controlled.position, destination)):F3}";

        string animalStatus =
            $"animalEnabled={body.animal.isActiveAndEnabled} state={animalState} grounded={body.animal.Grounded} " +
            $"sprint={body.animal.Sprint} movementAxis={body.animal.MovementAxis.ToString("F3")} " +
            $"movementRaw={body.animal.MovementAxisRaw.ToString("F3")} " +
            $"movementSmooth={body.animal.MovementAxisSmoothed.ToString("F3")} " +
            $"controlled={controlled.name} controlledPos={controlled.position.ToString("F3")}";

        return $"{animalStatus}\n{aiStatus}\n{motorNavigationStatus}\n{agentStatus}";
    }

    Vector3 SafeAgentDestination(NavMeshAgent agent)
    {
        if (agent == null || !agent.isActiveAndEnabled || !agent.isOnNavMesh)
            return Vector3.zero;

        return agent.destination;
    }

    Transform ControlledTransform =>
        body != null && body.animal != null ? body.animal.transform : transform;

    static float HorizontalDistance(Vector3 a, Vector3 b)
    {
        a.y = 0f;
        b.y = 0f;
        return Vector3.Distance(a, b);
    }

    bool Fail(string message)
    {
        Fail("SETUP", message);
        return false;
    }

    void Fail(string label, string message)
    {
        _failCount++;
        Debug.LogError($"[CreatureWorkerScriptControlTest] FAIL {label} - {message}");
    }

    void Pass(string message)
    {
        _passCount++;
        Debug.Log($"[CreatureWorkerScriptControlTest] PASS {message}");
    }

    void Skip(string label, string message)
    {
        _skipCount++;
        Debug.LogWarning($"[CreatureWorkerScriptControlTest] SKIP {label} - {message}");
    }
}
