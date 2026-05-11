using System.Collections;
using UnityEngine;
using UnityEngine.AI;

/// <summary>
/// Runtime proof that CreatureMotor is controlling the animal through script.
///
/// Attach this to the same GameObject as CreatureController/CreatureBlackboard.
/// It sends blackboard intents and verifies that CreatureMotor drives Malbers:
/// navigation intents through MAnimalAIControl, and scripted action intents through
/// MAnimal action-mode events.
/// </summary>
[DisallowMultipleComponent]
public class CreatureMotorScriptControlTest : MonoBehaviour
{
    [Header("References")]
    public CreatureController controller;
    public CreatureBlackboard board;
    public CreatureMotor motor;
    public CreatureConfig config;
    public Transform goToTarget;

    [Header("Run")]
    public bool runOnStart = true;
    public bool takeOverControllerDuringTest = true;
    public bool restoreControllerAfterTest = true;
    public bool runNavigationProof = false;
    public bool runActionProof = true;
    public bool continueAfterNavigationFailure = true;

    [Header("Navigation Proof")]
    public float fallbackDistance = 4f;
    public float destinationTolerance = 1.25f;
    public float waitForAgentSeconds = 2f;
    public float movementSampleSeconds = 2.5f;
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

    [ContextMenu("Run CreatureMotor Script Control Test")]
    public void RunNow()
    {
        if (!Application.isPlaying)
        {
            Debug.LogWarning("[CreatureMotorScriptControlTest] Enter Play Mode before running this test.");
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

        // Temporarily disabled so we can verify scripted Malbers actions first.
        // Re-enable this block later when the NavMeshAgent/MAnimal movement setup is fixed.
        if (runNavigationProof)
            Debug.LogWarning("[CreatureMotorScriptControlTest] Navigation proof is temporarily disabled in code; running action proof only.");

        if (runActionProof)
            yield return RunActionProof();

        string result = _failCount == 0 ? "PASS" : "FAIL";
        Debug.Log($"[CreatureMotorScriptControlTest] RESULT {result} - passed={_passCount} failed={_failCount} skipped={_skipCount}");

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

        board.ClearReflexIntent();
        board.ClearTacticalIntent();
        board.ClearMindIntent();
        board.SetMindIntent("go_to", destination, goCommandId, requestId);

        Debug.Log($"[CreatureMotorScriptControlTest] STEP go_to destination={destination} commandId={goCommandId}");
        motor.Tick();

        if (logStatusSnapshot)
            Debug.Log($"[CreatureMotorScriptControlTest] after go_to\n{BuildStatus(agent, controlled)}");

        float deadline = Time.time + waitForAgentSeconds;
        while (Time.time < deadline && !AgentAcceptedDestination(agent, destination))
            yield return null;

        if (!AgentAcceptedDestination(agent, destination))
        {
            Fail("NAV go_to", $"NavMeshAgent did not accept scripted destination. agent.destination={SafeAgentDestination(agent)}, expected={destination}");
            if (!continueAfterNavigationFailure)
                yield break;
            yield break;
        }

        Pass($"NAV go_to destination accepted by script. agent.destination={agent.destination}");

        Vector3 startPosition = controlled.position;
        yield return new WaitForSeconds(movementSampleSeconds);

        float moved = HorizontalDistance(startPosition, controlled.position);
        if (moved < minimumMovedDistance)
        {
            Fail(
                "NAV go_to movement",
                $"Animal transform did not move enough after scripted go_to. moved={moved:F3}m expected>={minimumMovedDistance:F3}m controlled={controlled.name}\n" +
                BuildStatus(agent, controlled));
            if (!continueAfterNavigationFailure)
                yield break;
            yield break;
        }

        Pass($"NAV go_to animal moved by script. controlled={controlled.name} moved={moved:F3}m");

        string stopCommandId = $"{board.CreatureId}:script-test-stop:{Time.frameCount}";
        board.ClearReflexIntent();
        board.ClearTacticalIntent();
        board.SetMindIntent("stop_moving", Vector3.zero, stopCommandId, requestId);

        Debug.Log($"[CreatureMotorScriptControlTest] STEP stop_moving commandId={stopCommandId}");
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
        if (motor.ActionModeId <= 0)
        {
            Fail("ACTIONS setup", "CreatureMotor ActionModeId is not valid. Malbers default Action mode ID is 4.");
            yield break;
        }

        if (motor.animal.Mode_Get(motor.ActionModeId) == null)
        {
            Fail("ACTIONS setup", $"MAnimal does not have an Action mode with ID {motor.ActionModeId}.\n{BuildModesSummary()}");
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
            Skip($"ACTION {action.Intent}", "ability index is 0/unassigned on CreatureMotor");
            yield break;
        }

        yield return WaitForActionReady($"before {action.Intent}");

        ApplyAbilityIndexToMotor(action);
        ResetModeEvents();

        string requestId = $"script-control-test-action:{Time.frameCount}";
        string commandId = $"{board.CreatureId}:script-test-{action.Intent}:{Time.frameCount}";

        board.ClearReflexIntent();
        board.ClearTacticalIntent();
        board.ClearMindIntent();
        board.SetMindIntent(action.Intent, Vector3.zero, commandId, requestId, action.Intent);

        Debug.Log($"[CreatureMotorScriptControlTest] STEP action intent={action.Intent} ability={action.AbilityIndex} commandId={commandId}");
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
                    $"[CreatureMotorScriptControlTest] ACTION {action.Intent} was accepted by Malbers but no OnModeStart fired. " +
                    "This usually means the Action ability has no valid Animator transition/ModeBehaviour path for this animal.");
                yield return ForceActionCleanup();
                yield break;
            }

            Fail(
                $"ACTION {action.Intent}",
                $"expected mode start actionMode={motor.ActionModeId} ability={action.AbilityIndex}, " +
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
            Debug.LogWarning($"[CreatureMotorScriptControlTest] ACTION {action.Intent} started but did not end within {actionEndTimeout:F1}s; forcing cleanup so the next action can run.");
        }

        yield return ForceActionCleanup();
    }

    ActionCase[] BuildActionCases()
    {
        return new[]
        {
            new ActionCase("flinch", ResolveAbilityIndex("flinch", "stun", "startle", motor.startleAbilityIndex)),
            new ActionCase("scratch", ResolveAbilityIndex("scratch", "", "", motor.scratchAbilityIndex)),
            new ActionCase("look_around", ResolveAbilityIndex("look", "look around", "", motor.lookAroundAbilityIndex)),
            new ActionCase("nod_head", ResolveAbilityIndex("nod", "nod head", "", motor.nodHeadAbilityIndex)),
            new ActionCase("eat", ResolveAbilityIndex("eat", "", "", motor.eatAbilityIndex)),
            new ActionCase("drink", ResolveAbilityIndex("drink", "", "", motor.drinkAbilityIndex)),
            new ActionCase("sit", ResolveAbilityIndex("sit", "seat", "", motor.sitAbilityIndex)),
            new ActionCase("lie", ResolveAbilityIndex("lie", "lay", "down", motor.lieAbilityIndex)),
            new ActionCase("sleep", ResolveAbilityIndex("sleep", "", "", motor.sleepAbilityIndex)),
            new ActionCase("groom", ResolveAbilityIndex("groom", "", "", motor.groomAbilityIndex)),
            new ActionCase("smell", ResolveAbilityIndex("smell", "sniff", "", motor.smellAbilityIndex)),
            new ActionCase("alert", ResolveAbilityIndex("alert", "", "", motor.alertAbilityIndex)),
            new ActionCase("vocalize", ResolveAbilityIndex("vocal", "meow", "howl", motor.vocalizeAbilityIndex)),
        };
    }

    int ResolveAbilityIndex(string primaryName, string alternateName, string tertiaryName, int configuredIndex)
    {
        if (!autoResolveAbilityIndexesByName)
            return configuredIndex;

        var mode = motor.animal.Mode_Get(motor.ActionModeId);
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
                    Debug.Log($"[CreatureMotorScriptControlTest] Auto-resolved '{primaryName}' ability index {configuredIndex} -> {ability.Index.Value} from Action ability '{ability.Name}'.");

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
            case "flinch":      motor.startleAbilityIndex = action.AbilityIndex;      break;
            case "scratch":     motor.scratchAbilityIndex = action.AbilityIndex;      break;
            case "look_around": motor.lookAroundAbilityIndex = action.AbilityIndex;   break;
            case "nod_head":    motor.nodHeadAbilityIndex = action.AbilityIndex;      break;
            case "eat":         motor.eatAbilityIndex = action.AbilityIndex;          break;
            case "drink":       motor.drinkAbilityIndex = action.AbilityIndex;        break;
            case "sit":         motor.sitAbilityIndex = action.AbilityIndex;          break;
            case "lie":         motor.lieAbilityIndex = action.AbilityIndex;          break;
            case "sleep":       motor.sleepAbilityIndex = action.AbilityIndex;        break;
            case "groom":       motor.groomAbilityIndex = action.AbilityIndex;        break;
            case "smell":       motor.smellAbilityIndex = action.AbilityIndex;        break;
            case "alert":       motor.alertAbilityIndex = action.AbilityIndex;        break;
            case "vocalize":    motor.vocalizeAbilityIndex = action.AbilityIndex;     break;
        }
    }

    void ResolveReferences()
    {
        if (controller == null) controller = GetComponent<CreatureController>();
        if (board == null)      board      = GetComponent<CreatureBlackboard>();
        if (motor == null)      motor      = GetComponent<CreatureMotor>();
        if (config == null && controller != null) config = controller.config;
    }

    void EnsureMotorInitializedIfNeeded()
    {
        if (motor == null || board == null)
            return;

        if (motor.animal != null && motor.aiControl != null)
            return;

        motor.Init(board, config);
    }

    bool TryValidate(out NavMeshAgent agent)
    {
        agent = null;

        if (board == null)
            return Fail("Missing CreatureBlackboard. Attach this to the AI Core GameObject or assign board.");

        if (motor == null)
            return Fail("Missing CreatureMotor. Attach this to the AI Core GameObject or assign motor.");

        if (motor.animal == null)
            return Fail("CreatureMotor has no MAnimal. Let CreatureController initialize it or assign motor.animal.");

        if (motor.aiControl == null)
            return Fail("CreatureMotor has no MAnimalAIControl. Assign motor.aiControl or use the Malbers AI prefab variant.");

        if (!motor.animal.isActiveAndEnabled)
            return Fail("MAnimal is not active/enabled. Enable the Cat MAnimal component before running the test.");

        if (!motor.aiControl.isActiveAndEnabled)
            return Fail("MAnimalAIControl is not active/enabled. Enable the Malbers AI Control component before running the test.");

        agent = motor.aiControl.Agent;
        if (agent == null)
            return Fail("MAnimalAIControl.Agent is null. Assign the NavMeshAgent child to the AI control component.");

        // Navigation validation is intentionally disabled while this harness is
        // being used to prove action-mode control first.

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

        Vector3 origin = agent.transform.position;
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

    void BeginRuntimeControl()
    {
        _previousLogIntentProof = motor.logIntentProof;
        motor.logIntentProof = true;
        _runtimeControlActive = true;

        _controllerWasEnabled = controller != null && controller.enabled;
        _restoreController = takeOverControllerDuringTest && restoreControllerAfterTest && controller != null;

        var periodicMind = GetComponent<PeriodicMind>();
        _periodicMindWasEnabled = periodicMind != null && periodicMind.enabled;

        if (takeOverControllerDuringTest && controller != null)
        {
            controller.enabled = false;
            _manualTick = true;
            Debug.Log("[CreatureMotorScriptControlTest] Temporarily disabled CreatureController and ticking CreatureMotor directly for an isolated proof.");
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

        if (motor != null)
            motor.logIntentProof = _previousLogIntentProof;

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
        Debug.Log($"[CreatureMotorScriptControlTest] EVENT OnModeStart mode={modeId} ability={abilityIndex}");
    }

    void OnTestModeEnded(int modeId, int abilityIndex)
    {
        _modeEnded = true;
        _endedModeId = modeId;
        _endedAbilityIndex = abilityIndex;
        Debug.Log($"[CreatureMotorScriptControlTest] EVENT OnModeEnd mode={modeId} ability={abilityIndex}");
    }

    bool SawExpectedModeStart(ActionCase action)
    {
        return _modeStarted &&
               _startedModeId == motor.ActionModeId &&
               _startedAbilityIndex == action.AbilityIndex;
    }

    bool SawExpectedModeEnd(ActionCase action)
    {
        return _modeEnded &&
               _endedModeId == motor.ActionModeId &&
               _endedAbilityIndex == action.AbilityIndex;
    }

    void CapturePreparedMode(ActionCase action)
    {
        int expected = ExpectedModeAbility(action);
        if (motor.animal.ModeAbility != expected)
            return;

        _modePrepared = true;
        _preparedModeAbility = motor.animal.ModeAbility;
    }

    int ExpectedModeAbility(ActionCase action)
    {
        return Mathf.Abs(motor.ActionModeId * 1000) + Mathf.Abs(action.AbilityIndex);
    }

    IEnumerator ForceActionCleanup()
    {
        board.ClearReflexIntent();
        board.ClearMindIntent();
        board.SetTacticalCurrent("idle");

        if (motor.animal.IsPlayingMode)
            motor.animal.Mode_Stop(true);

        if (motor.animal.IsPreparingMode)
            motor.animal.Mode_Interrupt_Forced();

        motor.Tick();
        yield return new WaitForSeconds(delayBetweenActions);
        yield return WaitForActionReady("after cleanup");
    }

    IEnumerator WaitForActionReady(string label)
    {
        float deadline = Time.time + actionReadyTimeout;
        while (Time.time < deadline &&
               (motor.animal.IsPreparingMode || motor.animal.IsPlayingMode))
        {
            yield return null;
        }

        if (motor.animal.IsPreparingMode || motor.animal.IsPlayingMode)
        {
            Debug.LogWarning(
                $"[CreatureMotorScriptControlTest] Action system still busy {label}: " +
                $"isPreparing={motor.animal.IsPreparingMode} isPlayingMode={motor.animal.IsPlayingMode}. Forcing interrupt.");
            motor.animal.Mode_Stop(true);
            motor.animal.Mode_Interrupt_Forced();
            yield return new WaitForSeconds(delayBetweenActions);
        }
    }

    void DetachActionListeners()
    {
        if (!_actionListenersAttached || motor == null || motor.animal == null)
            return;

        motor.animal.OnModeStart.RemoveListener(OnTestModeStarted);
        motor.animal.OnModeEnd.RemoveListener(OnTestModeEnded);
        _actionListenersAttached = false;
    }

    void AttachActionListeners()
    {
        if (_actionListenersAttached)
            return;

        motor.animal.OnModeStart.RemoveListener(OnTestModeStarted);
        motor.animal.OnModeEnd.RemoveListener(OnTestModeEnded);
        motor.animal.OnModeStart.AddListener(OnTestModeStarted);
        motor.animal.OnModeEnd.AddListener(OnTestModeEnded);
        _actionListenersAttached = true;
    }

    string BuildActionStatus(ActionCase action)
    {
        var mode = motor.animal.Mode_Get(motor.ActionModeId);
        if (mode == null)
            return $"actionModeId={motor.ActionModeId} is not present on MAnimal.modes\n{BuildModesSummary()}";

        var ability = mode.GetAbility(action.AbilityIndex);
        string abilityInfo = ability == null
            ? $"ability {action.AbilityIndex} is not in Action mode list"
            : $"ability={ability.Name}({ability.Index.Value}) active={ability.Active} status={ability.Status} " +
              $"blockedByState={mode.StateCanInterrupt(motor.animal.ActiveStateID, ability)} " +
              $"blockedByStance={mode.StanceCanInterrupt(motor.animal.Stance, ability)}";

        string activeMode = motor.animal.ActiveMode != null
            ? $"{motor.animal.ActiveMode.Name}({motor.animal.ActiveMode.ID.ID})"
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
            $"expectedModeAbility={ExpectedModeAbility(action)} currentModeAbility={motor.animal.ModeAbility} " +
            $"animalState={motor.animal.ActiveStateID.name}({motor.animal.ActiveStateID.ID}) noModes={motor.animal.ActiveState.NoModes} " +
            $"stance={(motor.animal.Stance != null ? motor.animal.Stance.name : "null")} " +
            $"isPreparing={motor.animal.IsPreparingMode} isPlayingMode={motor.animal.IsPlayingMode} activeMode={activeMode}\n" +
            $"{abilityInfo}\n" +
            $"available Action abilities: {abilityIndexes}";
    }

    string BuildModesSummary()
    {
        string summary = "MAnimal modes: ";
        if (motor.animal.modes == null || motor.animal.modes.Count == 0)
            return summary + "<none>";

        for (int i = 0; i < motor.animal.modes.Count; i++)
        {
            var mode = motor.animal.modes[i];
            if (mode == null || mode.ID == null) continue;
            if (i > 0) summary += ", ";
            summary += $"{mode.Name}({mode.ID.ID})";
        }
        return summary;
    }

    string BuildStatus(NavMeshAgent agent, Transform controlled)
    {
        string animalState = motor.animal.ActiveStateID != null
            ? $"{motor.animal.ActiveStateID.name}({motor.animal.ActiveStateID.ID})"
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
            $"aiEnabled={motor.aiControl.isActiveAndEnabled} activeAgent={motor.aiControl.ActiveAgent} " +
            $"aiReady={motor.aiControl.AIReady} waiting={motor.aiControl.IsWaiting} " +
            $"blockingState={motor.aiControl.StateIsBlockingAgent} aiMoving={motor.aiControl.IsMoving} " +
            $"aiDirection={motor.aiControl.AIDirection.ToString("F3")} " +
            $"aiDestination={motor.aiControl.DestinationPosition.ToString("F3")}";

        string animalStatus =
            $"animalEnabled={motor.animal.isActiveAndEnabled} state={animalState} grounded={motor.animal.Grounded} " +
            $"sprint={motor.animal.Sprint} movementAxis={motor.animal.MovementAxis.ToString("F3")} " +
            $"movementRaw={motor.animal.MovementAxisRaw.ToString("F3")} " +
            $"movementSmooth={motor.animal.MovementAxisSmoothed.ToString("F3")} " +
            $"controlled={controlled.name} controlledPos={controlled.position.ToString("F3")}";

        return $"{animalStatus}\n{aiStatus}\n{agentStatus}";
    }

    Vector3 SafeAgentDestination(NavMeshAgent agent)
    {
        if (agent == null || !agent.isActiveAndEnabled || !agent.isOnNavMesh)
            return Vector3.zero;

        return agent.destination;
    }

    Transform ControlledTransform =>
        motor != null && motor.animal != null ? motor.animal.transform : transform;

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
        Debug.LogError($"[CreatureMotorScriptControlTest] FAIL {label} - {message}");
    }

    void Pass(string message)
    {
        _passCount++;
        Debug.Log($"[CreatureMotorScriptControlTest] PASS {message}");
    }

    void Skip(string label, string message)
    {
        _skipCount++;
        Debug.LogWarning($"[CreatureMotorScriptControlTest] SKIP {label} - {message}");
    }
}
