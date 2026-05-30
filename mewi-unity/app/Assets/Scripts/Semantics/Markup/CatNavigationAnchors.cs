using System.Collections.Generic;
using UnityEngine;
using UnityEngine.AI;

/// <summary>
/// Collection of cat-authored navigation points for an interactive object or
/// ZoneVolume. Attach this to the object/zone root and add CatNavigationPoint
/// children for approach, patrol, watch, and teleport fallback locations.
/// </summary>
[DisallowMultipleComponent]
public class CatNavigationAnchors : MonoBehaviour
{
    [Header("Points")]
    [SerializeField] List<CatNavigationPoint> points = new List<CatNavigationPoint>();
    [SerializeField] bool autoDiscoverChildPoints = true;
    [SerializeField] bool includeInactiveChildren;

    [Header("NavMesh")]
    [Tooltip("How far an authored point may be from NavMesh and still count as a usable walking point.")]
    [SerializeField] float navMeshSampleRadius = 1f;

    [Tooltip("Require a complete NavMesh path for normal go_to points.")]
    [SerializeField] bool requireCompletePath = true;

    [Header("Fallback")]
    [Tooltip("If no reachable walking point exists, return a teleport fallback point when one is authored.")]
    [SerializeField] bool useTeleportFallbackWhenUnreachable = true;

    [Header("Scoring")]
    [SerializeField] float priorityWeight = 10f;
    [SerializeField] float approachKindBonus = 5f;
    [SerializeField] float entryKindBonus = 3f;
    [SerializeField] float patrolKindBonus = 1f;

    readonly List<CatNavigationPoint> _scratch = new List<CatNavigationPoint>();
    readonly NavMeshPath _path = new NavMeshPath();

    public IReadOnlyList<CatNavigationPoint> Points
    {
        get
        {
            CollectPoints(_scratch);
            return _scratch;
        }
    }

    public bool TryResolveGoToPosition(
        Vector3 requesterPosition,
        int areaMask,
        out Vector3 position,
        out CatNavigationPoint selectedPoint,
        out string reason)
    {
        position = Vector3.zero;
        selectedPoint = null;
        reason = "";

        CollectPoints(_scratch);
        if (_scratch.Count == 0)
        {
            reason = "no_cat_navigation_points";
            return false;
        }

        if (TryPickReachablePoint(requesterPosition, areaMask, out position, out selectedPoint, out reason))
            return true;

        if (useTeleportFallbackWhenUnreachable &&
            TryPickTeleportFallback(out position, out selectedPoint))
        {
            reason = "teleport_fallback";
            return true;
        }

        return false;
    }

    public bool TryResolveDefaultPosition(out Vector3 position, out CatNavigationPoint selectedPoint)
    {
        position = Vector3.zero;
        selectedPoint = null;

        CollectPoints(_scratch);
        CatNavigationPoint best = null;
        float bestScore = float.NegativeInfinity;

        for (int i = 0; i < _scratch.Count; i++)
        {
            CatNavigationPoint point = _scratch[i];
            if (point == null || point.avoidForNormalGoTo || point.IsTeleportFallback) continue;

            float score = ScoreKind(point.kind) + point.priority * priorityWeight;
            if (score <= bestScore) continue;

            best = point;
            bestScore = score;
        }

        if (best == null)
            return TryPickTeleportFallback(out position, out selectedPoint);

        position = best.transform.position;
        selectedPoint = best;
        return true;
    }

    bool TryPickReachablePoint(
        Vector3 requesterPosition,
        int areaMask,
        out Vector3 position,
        out CatNavigationPoint selectedPoint,
        out string reason)
    {
        position = Vector3.zero;
        selectedPoint = null;
        reason = "";

        bool sampledStart = NavMesh.SamplePosition(
            requesterPosition,
            out NavMeshHit startHit,
            navMeshSampleRadius,
            areaMask);

        if (requireCompletePath && !sampledStart)
        {
            reason = $"no_navmesh_near_requester:{requesterPosition}";
            return false;
        }

        float bestScore = float.NegativeInfinity;
        string lastReject = "";

        for (int i = 0; i < _scratch.Count; i++)
        {
            CatNavigationPoint point = _scratch[i];
            if (point == null || point.avoidForNormalGoTo || point.IsTeleportFallback)
                continue;

            if (!TrySamplePoint(point, areaMask, out Vector3 sampledPosition, out string sampleReason))
            {
                lastReject = $"{point.DisplayName}:{sampleReason}";
                continue;
            }

            float pathLength = Vector3.Distance(requesterPosition, sampledPosition);
            if (requireCompletePath)
            {
                if (!NavMesh.CalculatePath(startHit.position, sampledPosition, areaMask, _path) ||
                    _path.status != NavMeshPathStatus.PathComplete)
                {
                    lastReject = $"{point.DisplayName}:path_{_path.status}";
                    continue;
                }

                pathLength = PathLength(_path, requesterPosition, sampledPosition);
            }

            float score = ScoreKind(point.kind)
                + point.priority * priorityWeight
                - pathLength;

            if (score <= bestScore) continue;

            bestScore = score;
            selectedPoint = point;
            position = sampledPosition;
        }

        if (selectedPoint != null)
            return true;

        reason = string.IsNullOrWhiteSpace(lastReject) ? "no_reachable_points" : lastReject;
        return false;
    }

    bool TryPickTeleportFallback(out Vector3 position, out CatNavigationPoint selectedPoint)
    {
        position = Vector3.zero;
        selectedPoint = null;

        CatNavigationPoint best = null;
        int bestPriority = int.MinValue;

        for (int i = 0; i < _scratch.Count; i++)
        {
            CatNavigationPoint point = _scratch[i];
            if (point == null || !point.IsTeleportFallback)
                continue;

            if (point.priority < bestPriority)
                continue;

            best = point;
            bestPriority = point.priority;
        }

        if (best == null)
            return false;

        selectedPoint = best;
        position = best.transform.position;
        return true;
    }

    bool TrySamplePoint(CatNavigationPoint point, int areaMask, out Vector3 position, out string reason)
    {
        position = point != null ? point.transform.position : Vector3.zero;
        reason = "";
        if (point == null)
        {
            reason = "null_point";
            return false;
        }

        if (NavMesh.SamplePosition(point.transform.position, out NavMeshHit hit, navMeshSampleRadius, areaMask))
        {
            position = hit.position;
            return true;
        }

        reason = $"no_navmesh_within_{navMeshSampleRadius:F1}m";
        return false;
    }

    void CollectPoints(List<CatNavigationPoint> buffer)
    {
        buffer.Clear();

        for (int i = 0; i < points.Count; i++)
        {
            CatNavigationPoint point = points[i];
            if (point != null && !buffer.Contains(point))
                buffer.Add(point);
        }

        if (!autoDiscoverChildPoints) return;

        CatNavigationPoint[] children = GetComponentsInChildren<CatNavigationPoint>(includeInactiveChildren);
        for (int i = 0; i < children.Length; i++)
        {
            CatNavigationPoint point = children[i];
            if (point != null && !buffer.Contains(point))
                buffer.Add(point);
        }
    }

    float ScoreKind(CatNavigationPointKind kind)
    {
        switch (kind)
        {
            case CatNavigationPointKind.Approach: return approachKindBonus;
            case CatNavigationPointKind.Entry: return entryKindBonus;
            case CatNavigationPointKind.Patrol: return patrolKindBonus;
            default: return 0f;
        }
    }

    static float PathLength(NavMeshPath path, Vector3 fallbackStart, Vector3 fallbackEnd)
    {
        if (path == null || path.corners == null || path.corners.Length < 2)
            return Vector3.Distance(fallbackStart, fallbackEnd);

        float total = 0f;
        for (int i = 1; i < path.corners.Length; i++)
            total += Vector3.Distance(path.corners[i - 1], path.corners[i]);
        return total;
    }

    void OnDrawGizmosSelected()
    {
        CollectPoints(_scratch);
        Gizmos.color = Color.cyan;
        for (int i = 0; i < _scratch.Count; i++)
        {
            CatNavigationPoint point = _scratch[i];
            if (point == null) continue;
            Gizmos.DrawLine(transform.position, point.transform.position);
        }
    }
}
