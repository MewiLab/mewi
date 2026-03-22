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
    CreatureBlackBoard _board;

    void Start()
    {
        _board = GetComponent<CreatureBlackBoard>();
        Invoke(nameof(TestHungerCycle),    1f);
        Invoke(nameof(TestReflexOverride), 4f);
        Invoke(nameof(TestMindFallback),   7f);
    }

    void TestHungerCycle()
    {
        Debug.Log("=== TEST: Hunger cycle ===");
        // Force hunger above threshold — brain should transition Idle→Wander
        _board.health.hunger = config.hungerThreshold + 0.1f;
        Debug.Log($"Set hunger to {_board.health.hunger}, expect wander");
        
        // Next frame, check resolved intent
        Invoke(nameof(CheckIntent), 0.1f);
    }

    void TestReflexOverride()
    {
        Debug.Log("=== TEST: Reflex override ===");
        // Tactical should be wander, but reflex should win
        _board.SetReflexIntent("flinch", 1f);
        var resolved = _board.ResolveActiveIntent();
        Debug.Log($"Resolved: {resolved} (expect [Reflex] flinch)");
        
        // Wait for expiry
        Invoke(nameof(CheckReflexExpired), 1.2f);
    }

    void CheckReflexExpired()
    {
        var resolved = _board.ResolveActiveIntent();
        Debug.Log($"After expiry: {resolved} (expect tactical, not flinch)");
    }

    void TestMindFallback()
    {
        Debug.Log("=== TEST: Mind fallback ===");
        _board.ClearTacticalIntent();
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