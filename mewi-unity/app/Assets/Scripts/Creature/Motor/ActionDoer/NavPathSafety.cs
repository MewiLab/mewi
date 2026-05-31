using UnityEngine;
using UnityEngine.AI;

public enum NavRouteSafetyStatus
{
    Safe,
    Risky,
    Blocked,
}

[System.Serializable]
public class NavigationSafetyConfig
{
    [Tooltip("Enable extra route checks after NavMesh.CalculatePath says a path is complete.")]
    public bool enabled = true;

    [Tooltip("Distance between safety samples along the calculated path.")]
    public float pathSampleSpacing = 0.75f;

    [Tooltip("How close a path sample may be to a NavMesh edge before the route is considered risky.")]
    public float minNavMeshEdgeDistance = 0.25f;

    [Tooltip("Radius used to re-project path samples onto the NavMesh before edge checks.")]
    public float pathSampleNavMeshRadius = 0.35f;

    [Tooltip("Use Physics raycasts to check for missing ground, drops, and steep surfaces. Set Ground Mask to world/terrain layers before enabling in production scenes.")]
    public bool checkGroundProbes = false;

    [Tooltip("Layers treated as physical walking ground for route safety probes.")]
    public LayerMask groundMask = -1;

    [Tooltip("Height above each path sample where ground probes begin.")]
    public float groundProbeHeight = 0.75f;

    [Tooltip("How far below each path sample a ground probe may look.")]
    public float groundProbeDepth = 1.5f;

    [Tooltip("Maximum allowed drop from NavMesh sample height to physical ground.")]
    public float maxDropMeters = 0.65f;

    [Tooltip("Maximum physical ground slope accepted by ground probes.")]
    public float maxGroundSlopeDegrees = 50f;

    [Tooltip("Also probe left, right, and forward around the cat footprint.")]
    public bool checkFootprintGround = false;

    [Tooltip("Horizontal offset used by footprint ground probes.")]
    public float footprintProbeOffset = 0.28f;
}

public struct NavPathSafetyResult
{
    public NavRouteSafetyStatus status;
    public string reason;
    public float pathLength;
    public int cornerCount;
    public Vector3 problemPoint;
    public bool hasProblemPoint;

    public bool IsSafe => status == NavRouteSafetyStatus.Safe;
    public bool IsBlocked => status == NavRouteSafetyStatus.Blocked;
    public bool IsRisky => status == NavRouteSafetyStatus.Risky;

    public string Summary
    {
        get
        {
            string label = NavPathSafety.StatusToWireString(status);
            return string.IsNullOrWhiteSpace(reason) ? label : $"{label}:{reason}";
        }
    }
}

public static class NavPathSafety
{
    static readonly NavigationSafetyConfig FallbackConfig = new NavigationSafetyConfig();

    public static NavPathSafetyResult EvaluateRoute(
        Vector3 from,
        Vector3 to,
        int areaMask,
        NavigationSafetyConfig config,
        float startSampleRadius,
        float destinationSampleRadius,
        NavMeshPath reusablePath = null)
    {
        if (config == null)
            config = FallbackConfig;

        if (!NavMesh.SamplePosition(from, out NavMeshHit startHit, Mathf.Max(0.01f, startSampleRadius), areaMask))
            return Blocked("no_navmesh_near_start", 0f, 0, from);

        if (!NavMesh.SamplePosition(to, out NavMeshHit endHit, Mathf.Max(0.01f, destinationSampleRadius), areaMask))
            return Blocked("no_navmesh_near_destination", 0f, 0, to);

        NavMeshPath path = reusablePath ?? new NavMeshPath();
        if (!NavMesh.CalculatePath(startHit.position, endHit.position, areaMask, path))
            return Blocked("calculate_path_failed", 0f, 0, to);

        int cornerCount = path.corners != null ? path.corners.Length : 0;
        float pathLength = PathLength(path, startHit.position, endHit.position);

        if (path.status != NavMeshPathStatus.PathComplete)
            return Blocked($"path_{path.status}", pathLength, cornerCount, to);

        if (!config.enabled)
            return Safe(pathLength, cornerCount);

        if (!TryCheckPathSamples(path, areaMask, config, out string riskReason, out Vector3 riskPoint))
            return Risky(riskReason, pathLength, cornerCount, riskPoint);

        return Safe(pathLength, cornerCount);
    }

    public static string StatusToWireString(NavRouteSafetyStatus status)
    {
        switch (status)
        {
            case NavRouteSafetyStatus.Safe: return "safe";
            case NavRouteSafetyStatus.Risky: return "risky";
            case NavRouteSafetyStatus.Blocked: return "blocked";
            default: return "unknown";
        }
    }

    static bool TryCheckPathSamples(
        NavMeshPath path,
        int areaMask,
        NavigationSafetyConfig config,
        out string reason,
        out Vector3 problemPoint)
    {
        reason = "";
        problemPoint = Vector3.zero;

        if (path == null || path.corners == null || path.corners.Length == 0)
        {
            reason = "empty_path";
            return false;
        }

        if (path.corners.Length == 1)
            return TryCheckSample(path.corners[0], Vector3.forward, areaMask, config, out reason, out problemPoint);

        float spacing = Mathf.Max(0.1f, config.pathSampleSpacing);
        for (int i = 1; i < path.corners.Length; i++)
        {
            Vector3 a = path.corners[i - 1];
            Vector3 b = path.corners[i];
            Vector3 segment = b - a;
            float length = segment.magnitude;
            if (length <= 0.001f)
                continue;

            Vector3 direction = segment / length;
            int steps = Mathf.Max(1, Mathf.CeilToInt(length / spacing));
            for (int step = 0; step <= steps; step++)
            {
                float t = step / (float)steps;
                Vector3 sample = Vector3.Lerp(a, b, t);
                if (!TryCheckSample(sample, direction, areaMask, config, out reason, out problemPoint))
                    return false;
            }
        }

        return true;
    }

    static bool TryCheckSample(
        Vector3 sample,
        Vector3 direction,
        int areaMask,
        NavigationSafetyConfig config,
        out string reason,
        out Vector3 problemPoint)
    {
        reason = "";
        problemPoint = sample;

        float navSampleRadius = Mathf.Max(0.01f, config.pathSampleNavMeshRadius);
        if (!NavMesh.SamplePosition(sample, out NavMeshHit navHit, navSampleRadius, areaMask))
        {
            reason = "sample_off_navmesh";
            return false;
        }

        if (config.minNavMeshEdgeDistance > 0f &&
            NavMesh.FindClosestEdge(navHit.position, out NavMeshHit edgeHit, areaMask) &&
            edgeHit.distance < config.minNavMeshEdgeDistance)
        {
            reason = $"near_navmesh_edge:{edgeHit.distance:F2}m";
            problemPoint = navHit.position;
            return false;
        }

        if (!config.checkGroundProbes)
            return true;

        if (!TryProbeGround(navHit.position, "center", config, out reason))
        {
            problemPoint = navHit.position;
            return false;
        }

        if (!config.checkFootprintGround)
            return true;

        Vector3 flatDirection = direction;
        flatDirection.y = 0f;
        if (flatDirection.sqrMagnitude <= 0.0001f)
            flatDirection = Vector3.forward;
        flatDirection.Normalize();

        Vector3 side = Vector3.Cross(Vector3.up, flatDirection).normalized;
        float offset = Mathf.Max(0.01f, config.footprintProbeOffset);

        if (!TryProbeGround(navHit.position + side * offset, "left", config, out reason) ||
            !TryProbeGround(navHit.position - side * offset, "right", config, out reason) ||
            !TryProbeGround(navHit.position + flatDirection * offset, "front", config, out reason))
        {
            problemPoint = navHit.position;
            return false;
        }

        return true;
    }

    static bool TryProbeGround(
        Vector3 point,
        string label,
        NavigationSafetyConfig config,
        out string reason)
    {
        reason = "";

        float height = Mathf.Max(0.01f, config.groundProbeHeight);
        float depth = Mathf.Max(0.01f, config.groundProbeDepth);
        Vector3 origin = point + Vector3.up * height;
        float maxDistance = height + depth;

        if (!Physics.Raycast(
                origin,
                Vector3.down,
                out RaycastHit hit,
                maxDistance,
                config.groundMask,
                QueryTriggerInteraction.Ignore))
        {
            reason = $"{label}_missing_ground";
            return false;
        }

        float drop = point.y - hit.point.y;
        if (drop > config.maxDropMeters)
        {
            reason = $"{label}_drop:{drop:F2}m";
            return false;
        }

        float slope = Vector3.Angle(hit.normal, Vector3.up);
        if (slope > config.maxGroundSlopeDegrees)
        {
            reason = $"{label}_steep_slope:{slope:F0}deg";
            return false;
        }

        return true;
    }

    static NavPathSafetyResult Safe(float pathLength, int cornerCount)
    {
        return new NavPathSafetyResult
        {
            status = NavRouteSafetyStatus.Safe,
            reason = "",
            pathLength = pathLength,
            cornerCount = cornerCount,
        };
    }

    static NavPathSafetyResult Risky(string reason, float pathLength, int cornerCount, Vector3 point)
    {
        return new NavPathSafetyResult
        {
            status = NavRouteSafetyStatus.Risky,
            reason = reason,
            pathLength = pathLength,
            cornerCount = cornerCount,
            problemPoint = point,
            hasProblemPoint = true,
        };
    }

    static NavPathSafetyResult Blocked(string reason, float pathLength, int cornerCount, Vector3 point)
    {
        return new NavPathSafetyResult
        {
            status = NavRouteSafetyStatus.Blocked,
            reason = reason,
            pathLength = pathLength,
            cornerCount = cornerCount,
            problemPoint = point,
            hasProblemPoint = true,
        };
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
}
