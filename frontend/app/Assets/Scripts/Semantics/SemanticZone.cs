using UnityEngine;

/// <summary>
/// Attach to a dedicated child GameObject on any scene object (house, lantern, food, etc.)
/// that should be perceived as a single semantic unit by the cat.
///
/// Setup per object:
///   1. Add a child GameObject named e.g. "Semantic" to BP_House_2.
///   2. Add a Box/Sphere Collider sized to the object's footprint — set isTrigger = true.
///   3. Add this component and fill in category ("house") and optionally label.
///   4. Assign the child to the "Semantic" layer (create it in Project Settings → Tags & Layers).
///
/// CreaturePerception scans the Semantic layer separately; the cat perceives the
/// parent object as a whole rather than its individual mesh children.
/// </summary>
[RequireComponent(typeof(Collider))]
public class SemanticZone : MonoBehaviour
{
    [Tooltip("Semantic class understood by the AI agent — e.g. house, shelter, lantern, food")]
    public string category = "unknown";

    [Tooltip("Human-readable name sent to the agent. Defaults to parent GameObject name if empty.")]
    public string label;

    void Awake()
    {
        GetComponent<Collider>().isTrigger = true;

        if (string.IsNullOrEmpty(label))
            label = transform.parent != null ? transform.parent.name : gameObject.name;
    }
}
