using UnityEngine;

/// <summary>
/// Optional bridge from Unity collisions to short-lived FeelingEmitter triggers.
/// </summary>
[RequireComponent(typeof(Collider))]
public class FeelingCollisionRelay : MonoBehaviour
{
    public FeelingEmitter emitter;

    [Header("Impact")]
    public float impactVelocityThreshold = 1.5f;
    public string impactTrigger = "impact";

    [Header("Kick")]
    public float kickVelocityThreshold = 2.5f;
    public string kickTrigger = "kicked";

    [Header("Fall")]
    public Rigidbody body;
    public float fallingVelocityThreshold = 2f;
    public string fallTrigger = "fell";

    bool _wasFalling;

    void Awake()
    {
        if (emitter == null) emitter = GetComponent<FeelingEmitter>() ?? GetComponentInParent<FeelingEmitter>();
        if (body == null) body = GetComponent<Rigidbody>() ?? GetComponentInParent<Rigidbody>();
    }

    void FixedUpdate()
    {
        if (body == null) return;
        _wasFalling = body.linearVelocity.y <= -Mathf.Abs(fallingVelocityThreshold);
    }

    void OnCollisionEnter(Collision collision)
    {
        if (emitter == null || collision == null) return;

        float speed = collision.relativeVelocity.magnitude;
        if (speed >= impactVelocityThreshold)
            emitter.EmitTrigger(impactTrigger);

        if (_wasFalling)
        {
            emitter.EmitTrigger(fallTrigger);
            _wasFalling = false;
        }

        if (speed >= kickVelocityThreshold && IsCreatureOrPlayer(collision.transform))
            emitter.EmitTrigger(kickTrigger);
    }

    static bool IsCreatureOrPlayer(Transform other)
    {
        if (other == null) return false;
        if (other.GetComponentInParent<CreatureBlackboard>() != null) return true;
        Transform root = other.root != null ? other.root : other;
        return root.name.ToLowerInvariant().Contains("player");
    }
}
