using UnityEngine;

public enum CatNavigationPointKind
{
    Approach,
    Patrol,
    Watch,
    Rest,
    Entry,
    Exit,
    TeleportFallback,
}

/// <summary>
/// Designer-authored cat movement point for an object or zone. Put this on an
/// empty child transform; CatNavigationAnchors will choose among these points
/// instead of sending the cat to the object's raw transform.
/// </summary>
[DisallowMultipleComponent]
public class CatNavigationPoint : MonoBehaviour
{
    [Header("Role")]
    public CatNavigationPointKind kind = CatNavigationPointKind.Approach;
    public int priority;

    [Tooltip("How close the cat should get before this point counts as reached.")]
    public float arrivalRadius = 0.65f;

    [Header("Policy")]
    [Tooltip("Can this point be used as a hidden/safe teleport fallback?")]
    public bool allowTeleport;

    [Tooltip("Skip this point for ordinary go_to selection. Useful for dangerous or cinematic-only points.")]
    public bool avoidForNormalGoTo;

    [Tooltip("Prefer this point only when the cat is already in the same authored zone. Reserved for future scoring.")]
    public bool requireSameZone;

    [Header("After Arrival")]
    public Transform preferredFacingTarget;
    public string animationHint = "";
    public float cooldownSeconds;

    [Header("Debug")]
    public string debugName = "";
    public Color gizmoColor = new Color(0.1f, 0.75f, 1f, 0.85f);

    public string DisplayName => string.IsNullOrWhiteSpace(debugName) ? gameObject.name : debugName;
    public bool IsTeleportFallback => kind == CatNavigationPointKind.TeleportFallback || allowTeleport;

    void OnDrawGizmos()
    {
        Gizmos.color = IsTeleportFallback ? new Color(1f, 0.55f, 0.15f, 0.85f) : gizmoColor;
        Gizmos.DrawWireSphere(transform.position, Mathf.Max(0.1f, arrivalRadius));

        if (preferredFacingTarget != null)
            Gizmos.DrawLine(transform.position, preferredFacingTarget.position);
    }
}
