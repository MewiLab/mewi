using UnityEngine;

public class AnimalControllerTest : MonoBehaviour
{
    [Header("References")]
    private CreatureBlackboard _board;
    public Transform testTarget;

    void Start()
    {
        _board = GetComponent<CreatureBlackboard>();
    }

    void Update()
    {
        // Press 'T' to test moving to a specific target
        if (Input.GetKeyDown(KeyCode.Z))
        {
            Debug.Log("[Tester] Sending 'go_to' intent to Blackboard...");
            // We pass the target's position as the DirectionHint
            _board.SetTacticalCurrent("go_to", testTarget.position);
        }

        // Press 'W' to test the random wander logic
        if (Input.GetKeyDown(KeyCode.X))
        {
            Debug.Log("[Tester] Sending 'wander' intent to Blackboard...");
            _board.SetTacticalCurrent("wander");
        }
        
        // Press 'S' to test stopping
        if (Input.GetKeyDown(KeyCode.C))
        {
            Debug.Log("[Tester] Sending 'idle' intent to Blackboard...");
            _board.SetTacticalCurrent("idle");
        }
    }
}