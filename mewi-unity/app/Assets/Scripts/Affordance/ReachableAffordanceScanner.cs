using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.AI;

/// <summary>
/// Thin reachability builder for snapshot affordances.
/// It checks NavMesh reachability and builds records; it never executes actions.
/// </summary>
public static class ReachableAffordanceScanner
{
    public static int ScanPlaces(
        Transform actor,
        IEnumerable<ZoneVolume> zones,
        HashSet<string> excludedZoneIds,
        List<ReachableAffordance> reachable,
        int maxResults,
        float searchRadius,
        bool requireCompletePath,
        NavigationSafetyConfig navigationSafety,
        float startSampleRadius = 3f,
        float destinationSampleRadius = 6f)
    {
        if (reachable == null)
            return 0;

        reachable.Clear();
        if (actor == null || zones == null || maxResults <= 0)
            return 0;

        int areaMask = ResolveAreaMask(actor);
        float radiusSqr = searchRadius * searchRadius;
        NavigationSafetyConfig safety = navigationSafety ?? new NavigationSafetyConfig();
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var path = new NavMeshPath();

        foreach (ZoneVolume zone in zones)
        {
            if (!TryBuildPlace(
                    actor,
                    zone,
                    excludedZoneIds,
                    seen,
                    areaMask,
                    radiusSqr,
                    searchRadius,
                    requireCompletePath,
                    safety,
                    startSampleRadius,
                    destinationSampleRadius,
                    path,
                    out ReachableAffordance affordance))
            {
                continue;
            }

            reachable.Add(affordance);
        }

        reachable.Sort(Compare);

        if (reachable.Count > maxResults)
            reachable.RemoveRange(maxResults, reachable.Count - maxResults);

        return reachable.Count;
    }

    static bool TryBuildPlace(
        Transform actor,
        ZoneVolume zone,
        HashSet<string> excludedZoneIds,
        HashSet<string> seen,
        int areaMask,
        float radiusSqr,
        float searchRadius,
        bool requireCompletePath,
        NavigationSafetyConfig safety,
        float startSampleRadius,
        float destinationSampleRadius,
        NavMeshPath path,
        out ReachableAffordance affordance)
    {
        affordance = null;
        if (zone == null)
            return false;

        string zoneId = zone.EffectiveZoneId;
        if (string.IsNullOrWhiteSpace(zoneId))
            return false;
        if (excludedZoneIds != null && excludedZoneIds.Contains(zoneId))
            return false;
        if (seen != null && !seen.Add(zoneId))
            return false;

        Vector3 position = ZoneVolumeUtility.CenterOrTransform(zone);
        float sqrDistance = (position - actor.position).sqrMagnitude;
        if (searchRadius > 0f && sqrDistance > radiusSqr)
            return false;

        NavPathSafetyResult route = NavPathSafety.EvaluateRoute(
            actor.position,
            position,
            areaMask,
            safety,
            startSampleRadius,
            destinationSampleRadius,
            path);

        if (route.IsBlocked)
        {
            if (requireCompletePath)
                return false;

            route.status = NavRouteSafetyStatus.Risky;
            route.reason = "nearby_but_no_complete_path";
        }

        float distance = Mathf.Sqrt(sqrDistance);
        float pathLength = route.pathLength > 0f ? route.pathLength : distance;
        affordance = new ReachableAffordance
        {
            id = $"{zoneId}:go_to",
            action = "go_to",
            target_id = zoneId,
            label = zoneId,
            tags = ZoneTags(zone),
            distance = distance,
            path_length = pathLength,
            path_status = NavPathSafety.StatusToWireString(route.status),
            reason = route.reason ?? "",
            cost = pathLength,
            utility = 1f / (1f + pathLength),
            position = position,
            zone = zone,
            target = zone.transform,
        };

        return true;
    }

    static int ResolveAreaMask(Transform actor)
    {
        if (actor == null)
            return NavMesh.AllAreas;

        MalbersAnimalAdapter adapter = actor.GetComponent<MalbersAnimalAdapter>()
            ?? actor.GetComponentInParent<MalbersAnimalAdapter>()
            ?? actor.GetComponentInChildren<MalbersAnimalAdapter>();
        if (adapter != null)
            return adapter.NavigationAreaMask;

        NavMeshAgent agent = actor.GetComponent<NavMeshAgent>()
            ?? actor.GetComponentInParent<NavMeshAgent>()
            ?? actor.GetComponentInChildren<NavMeshAgent>();
        return agent != null ? agent.areaMask : NavMesh.AllAreas;
    }

    static string[] ZoneTags(ZoneVolume zone)
    {
        if (zone == null)
            return Array.Empty<string>();

        var tags = new List<string>
        {
            "place",
            $"zone.{zone.TypeString}",
        };

        if (!string.IsNullOrWhiteSpace(zone.surface))
            tags.Add($"surface.{zone.surface}");
        if (zone.confinement != ConfinementLevel.Open)
            tags.Add($"confinement.{zone.confinement.ToString().ToLowerInvariant()}");

        return tags.ToArray();
    }

    static int Compare(ReachableAffordance a, ReachableAffordance b)
    {
        int byStatus = StatusRank(a.path_status).CompareTo(StatusRank(b.path_status));
        if (byStatus != 0) return byStatus;

        int byCost = a.cost.CompareTo(b.cost);
        if (byCost != 0) return byCost;

        return string.Compare(a.target_id, b.target_id, StringComparison.OrdinalIgnoreCase);
    }

    static int StatusRank(string status)
    {
        if (string.Equals(status, "safe", StringComparison.OrdinalIgnoreCase)) return 0;
        if (string.Equals(status, "risky", StringComparison.OrdinalIgnoreCase)) return 1;
        if (string.Equals(status, "blocked", StringComparison.OrdinalIgnoreCase)) return 2;
        return 3;
    }
}
