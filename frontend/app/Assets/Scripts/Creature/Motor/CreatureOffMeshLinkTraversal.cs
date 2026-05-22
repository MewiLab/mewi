using UnityEngine;
using UnityEngine.AI;
using MalbersAnimations;
using MalbersAnimations.Controller;
using MalbersAnimations.Controller.AI;

/// <summary>
/// Reacts when the cat enters a <see cref="TraversalHintVolume"/> of kind
/// <see cref="TraversalHintKind.Jump"/>. While inside the volume the
/// NavMeshAgent is paused and Malbers is asked to enter its Jump state so the
/// jump animation can carry the cat across the obstacle without the agent
/// fighting the path. On exit the agent resumes.
///
/// This is the "secondary solution" from
/// docs/jump_through_obstacle_proposol.md — triggers act as local hints; the
/// NavMesh path and Malbers state machine remain the primary movement layer.
///
/// Also configures the NavMeshAgent for Malbers compatibility on Awake (Malbers
/// owns transform and animation, so the agent must not auto-traverse links or
/// drive position/rotation).
/// </summary>
[DisallowMultipleComponent]
public class CreatureOffMeshLinkTraversal : MonoBehaviour
{
    [Header("References")]
    public MAnimal          animal;
    public MAnimalAIControl aiControl;
    public NavMeshAgent     agent;

    [Header("Agent Setup")]
    [Tooltip("On Awake, force the NavMeshAgent into Malbers-compatible flags: " +
             "no auto off-mesh traversal, no transform updates from the agent.")]
    public bool configureAgentForMalbers = true;

    [Header("Jump Trigger")]
    [Tooltip("Re-snap (Warp) the agent to the cat's current position when leaving " +
             "a jump volume so pathing resumes from the landing point.")]
    public bool resnapAgentOnExit = true;

    [Header("Debug")]
    public bool logTransitions = true;

    int _activeJumpVolumes;

    void Awake()
    {
        ResolveReferences();
        ConfigureAgent();
    }

    void OnValidate()
    {
        ResolveReferences();
        ConfigureAgent();
    }

    void OnTriggerEnter(Collider other)
    {
        var hint = ResolveJumpHint(other);
        if (hint == null) return;

        _activeJumpVolumes++;
        if (_activeJumpVolumes == 1)
            SuspendForJump(hint);
    }

    void OnTriggerExit(Collider other)
    {
        var hint = ResolveJumpHint(other);
        if (hint == null) return;

        _activeJumpVolumes = Mathf.Max(0, _activeJumpVolumes - 1);
        if (_activeJumpVolumes == 0)
            ResumeAfterJump(hint);
    }

    static TraversalHintVolume ResolveJumpHint(Collider other)
    {
        if (other == null) return null;
        var hint = other.GetComponentInParent<TraversalHintVolume>();
        return (hint != null && hint.kind == TraversalHintKind.Jump) ? hint : null;
    }

    void SuspendForJump(TraversalHintVolume hint)
    {
        if (agent != null && agent.isActiveAndEnabled && agent.isOnNavMesh)
            agent.isStopped = true;

        if (animal != null)
            animal.State_Activate(StateEnum.Jump);

        if (logTransitions)
            Debug.Log($"[CreatureOffMeshLinkTraversal] entered jump hint '{hint.DisplayName}' → agent paused, Jump activated.");
    }

    void ResumeAfterJump(TraversalHintVolume hint)
    {
        if (agent != null && agent.isActiveAndEnabled)
        {
            if (resnapAgentOnExit)
                agent.Warp(transform.position);
            if (agent.isOnNavMesh)
                agent.isStopped = false;
        }

        if (logTransitions)
            Debug.Log($"[CreatureOffMeshLinkTraversal] left jump hint '{hint.DisplayName}' → agent resumed.");
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
        if (!configureAgentForMalbers || agent == null) return;
        agent.autoTraverseOffMeshLink = false;
        agent.updatePosition          = false;
        agent.updateRotation          = false;
    }
}
