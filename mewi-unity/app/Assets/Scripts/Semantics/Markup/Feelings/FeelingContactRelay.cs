using UnityEngine;

/// <summary>
/// Optional trigger-volume bridge for contact-only feelings such as texture,
/// temperature, taste, comfort, and danger.
/// </summary>
[RequireComponent(typeof(Collider))]
public class FeelingContactRelay : MonoBehaviour
{
    public FeelingEmitter emitter;
    public bool requireCreatureBlackboard = true;

    void Awake()
    {
        if (emitter == null) emitter = GetComponent<FeelingEmitter>() ?? GetComponentInParent<FeelingEmitter>();

        Collider c = GetComponent<Collider>();
        if (c != null && !c.isTrigger)
            c.isTrigger = true;
    }

    void OnTriggerEnter(Collider other)
    {
        if (emitter == null || other == null) return;
        if (requireCreatureBlackboard && other.GetComponentInParent<CreatureBlackboard>() == null) return;
        emitter.MarkContact(other.transform, true);
        emitter.EmitTrigger("contact");
    }

    void OnTriggerExit(Collider other)
    {
        if (emitter == null || other == null) return;
        if (requireCreatureBlackboard && other.GetComponentInParent<CreatureBlackboard>() == null) return;
        emitter.MarkContact(other.transform, false);
    }
}
