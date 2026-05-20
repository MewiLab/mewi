using UnityEngine;

/// <summary>
/// Manual keyboard driver for all CreatureWorker intents through MindIntent.
/// Attach to the same GameObject as CreatureBlackboard (AI Core).
///
/// ── Key Map ──────────────────────────────────────────────
///  Locomotion
///    I  →  idle
///    W  →  wander
///    F  →  flee        (threat simulated 5 m in front)
///    N  →  investigate (uses closestPlayer if assigned)
///
///  Mind action
///    Space  →  flinch
///
///  Scripted actions (one-shot, motor clears on Mode end)
///    E  →  eat
///    R  →  drink
///    T  →  sit
///    L  →  lie
///    Z  →  sleep
///    G  →  groom
///    S  →  smell
///    A  →  alert
///    V  →  vocalize
///
///  Terminal
///    Backspace  →  die
/// ──────────────────────────────────────────────────────────
/// </summary>
public class AnimalControllerTest : MonoBehaviour
{
    [Header("References")]
    public Transform testTarget;          // optional: used as closestPlayer for 'investigate'

    [Header("Flee Sim")]
    [Tooltip("Distance in front of the creature to place the fake threat")]
    public float fakeTheatDistance = 5f;

    CreatureBlackboard _board;

    void Start()
    {
        _board = GetComponent<CreatureBlackboard>();
        if (_board == null)
            Debug.LogError("[MotorTest] No CreatureBlackboard on this GameObject.");

        Debug.Log("[MotorTest] Ready. See key map in AnimalControllerTest header comment.");
    }

    void Update()
    {
        if (_board == null) return;

        // ── Locomotion ──────────────────────────────────────────────
        if (Input.GetKeyDown(KeyCode.I))
            Send("idle");

        if (Input.GetKeyDown(KeyCode.W))
            Send("wander");

        if (Input.GetKeyDown(KeyCode.F))
        {
            // Simulate a threat directly in front of the creature
            Vector3 fakeThreat = transform.position + transform.forward * fakeTheatDistance;
            Debug.Log($"[MotorTest] flee ← fake threat at {fakeThreat}");
            _board.SetMindIntent("flee", fakeThreat);
        }

        if (Input.GetKeyDown(KeyCode.N))
        {
            if (testTarget != null)
                _board.closestPlayer = testTarget;
            Send("investigate");
        }

        // ── Mind action ──────────────────────────────────────────────
        if (Input.GetKeyDown(KeyCode.Space))
        {
            Debug.Log("[MotorTest] mind → flinch");
            _board.SetMindIntent("flinch");
        }

        // ── Scripted actions ─────────────────────────────────────────
        if (Input.GetKeyDown(KeyCode.E))  Send("eat");
        if (Input.GetKeyDown(KeyCode.R))  Send("drink");
        if (Input.GetKeyDown(KeyCode.T))  Send("sit");
        if (Input.GetKeyDown(KeyCode.L))  Send("lie");
        if (Input.GetKeyDown(KeyCode.Z))  Send("sleep");
        if (Input.GetKeyDown(KeyCode.G))  Send("groom");
        if (Input.GetKeyDown(KeyCode.S))  Send("smell");
        if (Input.GetKeyDown(KeyCode.A))  Send("alert");
        if (Input.GetKeyDown(KeyCode.V))  Send("vocalize");

        // ── Terminal ─────────────────────────────────────────────────
        if (Input.GetKeyDown(KeyCode.Backspace))
        {
            Debug.Log("[MotorTest] TERMINAL → die");
            _board.SetMindIntent("die");
        }
    }

    void Send(string intent)
    {
        Debug.Log($"[MotorTest] mind → {intent}");
        _board.SetMindIntent(intent);
    }
}
