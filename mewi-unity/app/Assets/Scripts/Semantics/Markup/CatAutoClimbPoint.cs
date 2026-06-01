using UnityEngine;

/// <summary>
/// Attach this to a bottom climb point. When go_to resolves to this point,
/// CreatureMotorWorker queues a simple Climb command, then optionally queues a go_to
/// to the authored exit point.
/// </summary>
[RequireComponent(typeof(CatNavigationPoint))]
[DisallowMultipleComponent]
public class CatAutoClimbPoint : MonoBehaviour
{
    [Header("Climb")]
    [SerializeField] string climbTargetKey = "";
    [SerializeField] float climbSeconds = 3f;
    [SerializeField] Vector3 climbInputAxis = Vector3.forward;

    [Header("After Climb")]
    [SerializeField] bool enqueueExitGoTo = true;
    [SerializeField] Transform exitPoint;
    [SerializeField] string exitTargetKey = "";

    [Header("Debug")]
    [SerializeField] Color gizmoColor = new Color(0.2f, 1f, 0.35f, 0.9f);

    public float ClimbSeconds => Mathf.Max(0.1f, climbSeconds);
    public Vector3 ClimbInputAxis => climbInputAxis == Vector3.zero ? Vector3.forward : climbInputAxis;

    public bool TryGetClimbTarget(out Transform target, out string key)
    {
        target = transform;
        key = ResolveKey(climbTargetKey, target);
        return !string.IsNullOrWhiteSpace(key);
    }

    public bool TryGetExitTarget(out Transform target, out string key)
    {
        target = exitPoint;
        key = ResolveKey(exitTargetKey, target);
        return enqueueExitGoTo && target != null && !string.IsNullOrWhiteSpace(key);
    }

    void Reset()
    {
        ConfigureDefaults();
    }

    void OnValidate()
    {
        climbSeconds = Mathf.Max(0.1f, climbSeconds);
        if (climbInputAxis == Vector3.zero)
            climbInputAxis = Vector3.forward;
        ConfigureDefaults();
    }

    void ConfigureDefaults()
    {
        CatNavigationPoint point = GetComponent<CatNavigationPoint>();
        if (point != null)
            point.kind = CatNavigationPointKind.Entry;
    }

    static string ResolveKey(string authoredKey, Transform target)
    {
        if (!string.IsNullOrWhiteSpace(authoredKey))
            return authoredKey.Trim();
        return target != null ? target.name : "";
    }

    void OnDrawGizmosSelected()
    {
        Gizmos.color = gizmoColor;
        Gizmos.DrawWireSphere(transform.position, 0.35f);

        if (exitPoint != null)
        {
            Gizmos.DrawWireSphere(exitPoint.position, 0.25f);
            Gizmos.DrawLine(transform.position, exitPoint.position);
        }
    }
}
