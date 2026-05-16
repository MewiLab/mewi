using UnityEngine;
using UnityEngine.AI;
using MalbersAnimations.Controller;
using MalbersAnimations.Controller.AI;

[DisallowMultipleComponent]
public class CreatureOffMeshLinkTraversal : MonoBehaviour
{
    [Header("References")]
    public MAnimal          animal;
    public MAnimalAIControl aiControl;
    public NavMeshAgent     agent;

    [Header("Setup")]
    [Tooltip("Malbers MAnimalAIControl handles Off-Mesh traversal through animation, so Unity's agent should not auto-traverse links.")]
    public bool configureAgentForMalbers = true;

    [Header("Debug")]
    public bool logStartup = true;
    public bool logTraversal = true;
    public bool logNavigationDiagnostics = false;
    public float diagnosticIntervalSeconds = 1f;
    [Tooltip("0 disables this safety valve. If set, a stuck Off-Mesh Link is forcibly completed after this many seconds.")]
    public float stuckTimeoutSeconds = 0f;

    bool _wasInOffMeshLink;
    float _timeInLink;
    float _diagnosticTimer;

    void Awake()
    {
        ResolveReferences();
        ConfigureAgent();
        LogStartup();
    }

    void Update()
    {
        if (agent == null && aiControl == null)
            ResolveReferences();

        LogDiagnostics();

        bool inOffMeshLink = IsInOffMeshLink();

        if (inOffMeshLink)
        {
            if (!_wasInOffMeshLink)
                BeginOffMeshLink();

            _timeInLink += Time.deltaTime;

            if (stuckTimeoutSeconds > 0f && _timeInLink >= stuckTimeoutSeconds)
            {
                Debug.LogWarning($"[CreatureOffMeshLinkTraversal] Off-Mesh Link timed out after {_timeInLink:F1}s. Forcing completion.");
                CompleteOffMeshLink();
            }

            return;
        }

        if (_wasInOffMeshLink)
            EndOffMeshLink();
    }

    void OnValidate()
    {
        ResolveReferences();
        ConfigureAgent();
    }

    void LogStartup()
    {
        if (!logStartup)
            return;

        string agentStatus = agent == null
            ? "agent=null"
            : $"agent={agent.name} active={agent.isActiveAndEnabled} autoTraverse={agent.autoTraverseOffMeshLink} updatePosition={agent.updatePosition}";

        string aiStatus = aiControl == null
            ? "aiControl=null"
            : $"aiControl={aiControl.name} active={aiControl.isActiveAndEnabled}";

        string animalStatus = animal == null
            ? "animal=null"
            : $"animal={animal.name} state={AnimalStateName}";

        Debug.Log($"[CreatureOffMeshLinkTraversal] active on '{gameObject.name}'. {animalStatus} {aiStatus} {agentStatus}");
    }

    void ResolveReferences()
    {
        if (animal == null)
            animal = GetComponent<MAnimal>() ?? GetComponentInParent<MAnimal>() ?? GetComponentInChildren<MAnimal>();

        if (aiControl == null)
            aiControl = GetComponent<MAnimalAIControl>() ?? GetComponentInParent<MAnimalAIControl>() ?? GetComponentInChildren<MAnimalAIControl>();

        if (agent == null && aiControl != null)
            agent = aiControl.Agent;

        if (agent == null)
            agent = GetComponentInChildren<NavMeshAgent>();
    }

    void ConfigureAgent()
    {
        if (!configureAgentForMalbers || agent == null)
            return;

        agent.autoTraverseOffMeshLink = false;
        agent.updatePosition = false;
        agent.updateRotation = false;
    }

    bool IsInOffMeshLink()
    {
        if (aiControl != null && aiControl.InOffMeshLink)
            return true;

        return AgentIsCurrentlyOnOffMeshLink();
    }

    bool AgentIsCurrentlyOnOffMeshLink()
    {
        return agent != null &&
               agent.isActiveAndEnabled &&
               agent.isOnNavMesh &&
               agent.isOnOffMeshLink;
    }

    void BeginOffMeshLink()
    {
        _wasInOffMeshLink = true;
        _timeInLink = 0f;

        if (!logTraversal)
            return;

        if (AgentIsCurrentlyOnOffMeshLink())
        {
            var data = agent.currentOffMeshLinkData;
            Debug.Log(
                $"[CreatureOffMeshLinkTraversal] entered Off-Mesh Link type={data.linkType} " +
                $"start={data.startPos.ToString("F3")} end={data.endPos.ToString("F3")} " +
                $"animalState={AnimalStateName}. Malbers will handle the animation/state.");
        }
        else
        {
            Debug.Log($"[CreatureOffMeshLinkTraversal] entered Malbers Off-Mesh Link traversal. animalState={AnimalStateName}");
        }
    }

    void EndOffMeshLink()
    {
        if (logTraversal)
            Debug.Log($"[CreatureOffMeshLinkTraversal] completed Off-Mesh Link in {_timeInLink:F2}s.");

        _wasInOffMeshLink = false;
        _timeInLink = 0f;
    }

    void CompleteOffMeshLink()
    {
        if (aiControl != null)
            aiControl.CompleteOffMeshLink();
        else if (AgentIsCurrentlyOnOffMeshLink())
            agent.CompleteOffMeshLink();

        EndOffMeshLink();
    }

    void LogDiagnostics()
    {
        if (!logNavigationDiagnostics)
            return;

        _diagnosticTimer += Time.deltaTime;
        if (_diagnosticTimer < Mathf.Max(0.1f, diagnosticIntervalSeconds))
            return;

        _diagnosticTimer = 0f;

        if (agent == null)
        {
            Debug.LogWarning("[CreatureOffMeshLinkTraversal] diagnostics: NavMeshAgent is null.");
            return;
        }

        bool canReadAgent = agent.isActiveAndEnabled && agent.isOnNavMesh;
        string agentStatus =
            $"agentActive={agent.isActiveAndEnabled} " +
            $"onNavMesh={agent.isOnNavMesh} " +
            $"hasPath={(canReadAgent ? agent.hasPath.ToString() : "n/a")} " +
            $"pathStatus={(canReadAgent ? agent.pathStatus.ToString() : "n/a")} " +
            $"isOnOffMeshLink={(canReadAgent ? agent.isOnOffMeshLink.ToString() : "n/a")} " +
            $"areaMask={agent.areaMask} " +
            $"autoTraverse={agent.autoTraverseOffMeshLink}";

        string aiStatus = aiControl == null
            ? "aiControl=null"
            : $"aiInOffMesh={aiControl.InOffMeshLink} activeAgent={aiControl.ActiveAgent} aiDestination={aiControl.DestinationPosition.ToString("F3")}";

        Debug.Log($"[CreatureOffMeshLinkTraversal] diagnostics: {agentStatus} {aiStatus} animalState={AnimalStateName}");
    }

    string AnimalStateName
    {
        get
        {
            if (animal == null || animal.ActiveStateID == null)
                return "null";

            return $"{animal.ActiveStateID.name}({animal.ActiveStateID.ID})";
        }
    }
}
