using UnityEngine;
using UnityEngine.AI;

/// <summary>
/// Drop on a GameObject with all creature components + a NavMeshAgent.
/// Bake a flat NavMesh plane so the agent doesn't complain.
/// Runs through scenarios automatically and logs results.
/// </summary>
public class CreatureMVPTest : MonoBehaviour
{
    public CreatureConfig config;
    CreatureBlackboard _board;

    void Start()
    {
        _board = GetComponent<CreatureBlackboard>();
        Invoke(nameof(TestMindDrivenWander),   1f);
        Invoke(nameof(TestMindIntent),         4f);
    }

    void TestMindDrivenWander()
    {
        Debug.Log("=== TEST: Mind-driven wander ===");
        _board.SetMindIntent("wander");
        Debug.Log("Set MindIntent to wander");

        Invoke(nameof(CheckIntent), 0.1f);
    }

    void TestMindIntent()
    {
        Debug.Log("=== TEST: Mind intent ===");
        _board.SetMindIntent("investigate");
        var resolved = _board.ResolveActiveIntent();
        Debug.Log($"Resolved: {resolved} (expect [Mind] investigate)");
    }

    void CheckIntent()
    {
        var resolved = _board.ResolveActiveIntent();
        Debug.Log($"Resolved intent: {resolved}");
    }
}
