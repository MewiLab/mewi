// Collects every WanderZone in the scene and exposes the overlap "neighbor web"
// plus destination selection for ambient roaming.
// See docs/decisions/ADR-041-ambient-wander-and-exploration-zones.md.
//
// Authoring: drop ONE WanderZoneRegistry anywhere in the scene. It finds all
// WanderZones on Start and builds the adjacency graph from their overlaps.
// Recency is per-cat, so callers pass their own "recently visited" set; the
// registry itself is shared and stateless about who is asking.

using System.Collections.Generic;
using UnityEngine;
using UnityEngine.AI;

[DisallowMultipleComponent]
public sealed class WanderZoneRegistry : MonoBehaviour
{
    public static WanderZoneRegistry Instance { get; private set; }

    [Header("Neighbor graph")]
    [Tooltip("Extra slack (m) added when deciding if two circles count as overlapping neighbors.")]
    [Min(0f)] public float neighborSlack = 0.5f;

    [Header("Selection tuning")]
    [Tooltip("Weight multiplier for a zone the cat visited recently. <1 pushes it to spread out.")]
    [Range(0f, 1f)] public float recencyPenalty = 0.15f;

    [Tooltip("NavMesh sample radius when validating a picked point is reachable.")]
    [Min(0.1f)] public float navSampleRadius = 1.5f;

    [Tooltip("How many (zone, point) candidates to try before giving up this tick.")]
    [Min(1)] public int maxPickAttempts = 6;

    [Header("Debug")]
    [SerializeField] bool logBuild;

    readonly List<WanderZone> _zones = new List<WanderZone>();
    readonly Dictionary<WanderZone, List<WanderZone>> _neighbors =
        new Dictionary<WanderZone, List<WanderZone>>();

    public IReadOnlyList<WanderZone> Zones => _zones;
    public bool HasZones => _zones.Count > 0;

    void Awake()
    {
        if (Instance != null && Instance != this)
        {
            Debug.LogWarning($"[WanderZoneRegistry] duplicate on {name}; keeping {Instance.name}.");
            return;
        }
        Instance = this;
    }

    void OnDestroy()
    {
        if (Instance == this) Instance = null;
    }

    void Start()
    {
        Rebuild();
    }

    /// <summary>Re-scan all WanderZones and recompute the overlap graph.</summary>
    public void Rebuild()
    {
        _zones.Clear();
        _neighbors.Clear();

        _zones.AddRange(FindObjectsByType<WanderZone>(FindObjectsSortMode.None));

        for (int i = 0; i < _zones.Count; i++)
        {
            var list = new List<WanderZone>();
            for (int j = 0; j < _zones.Count; j++)
            {
                if (i == j) continue;
                if (_zones[i].IsNeighbor(_zones[j], neighborSlack))
                    list.Add(_zones[j]);
            }
            _neighbors[_zones[i]] = list;
        }

        if (logBuild)
            Debug.Log($"[WanderZoneRegistry] built {_zones.Count} zones, neighbor graph ready.");
    }

    public IReadOnlyList<WanderZone> NeighborsOf(WanderZone zone)
    {
        if (zone != null && _neighbors.TryGetValue(zone, out var list))
            return list;
        return System.Array.Empty<WanderZone>();
    }

    /// <summary>The zone whose centre is closest (XZ) to a world position, or null.</summary>
    public WanderZone NearestTo(Vector3 pos)
    {
        WanderZone best = null;
        float bestSqr = float.MaxValue;
        for (int i = 0; i < _zones.Count; i++)
        {
            Vector3 c = _zones[i].Center;
            float dx = c.x - pos.x, dz = c.z - pos.z;
            float sqr = dx * dx + dz * dz;
            if (sqr < bestSqr) { bestSqr = sqr; best = _zones[i]; }
        }
        return best;
    }

    /// <summary>
    /// Pick the next roaming destination. Prefers neighbors of <paramref name="current"/>
    /// so movement flows along the web; down-weights zones in <paramref name="recent"/>
    /// so the cat spreads out; validates the point against the NavMesh before returning.
    /// </summary>
    public bool TryPickDestination(
        Vector3 fromPos,
        WanderZone current,
        IReadOnlyCollection<WanderZone> recent,
        out WanderZone zone,
        out Vector3 point)
    {
        zone = null;
        point = default;
        if (_zones.Count == 0) return false;

        // Candidate set: neighbors of the current zone, else the whole map.
        IReadOnlyList<WanderZone> candidates = NeighborsOf(current);
        if (candidates.Count == 0)
            candidates = _zones;

        for (int attempt = 0; attempt < maxPickAttempts; attempt++)
        {
            WanderZone pick = WeightedPick(candidates, current, recent);
            if (pick == null) return false;

            Vector3 candidatePoint = pick.RandomPoint();
            if (NavMesh.SamplePosition(candidatePoint, out NavMeshHit hit, navSampleRadius, NavMesh.AllAreas))
            {
                zone = pick;
                point = hit.position;
                return true;
            }
        }
        return false;
    }

    WanderZone WeightedPick(
        IReadOnlyList<WanderZone> candidates,
        WanderZone current,
        IReadOnlyCollection<WanderZone> recent)
    {
        float total = 0f;
        // First pass: accumulate weights.
        for (int i = 0; i < candidates.Count; i++)
            total += WeightFor(candidates[i], current, recent);

        if (total <= 0f) return null;

        float roll = Random.value * total;
        for (int i = 0; i < candidates.Count; i++)
        {
            roll -= WeightFor(candidates[i], current, recent);
            if (roll <= 0f) return candidates[i];
        }
        return candidates[candidates.Count - 1];
    }

    float WeightFor(WanderZone z, WanderZone current, IReadOnlyCollection<WanderZone> recent)
    {
        if (z == null || z == current) return 0f;
        float w = 1f;
        if (recent != null && recent.Contains(z))
            w *= Mathf.Clamp01(recencyPenalty);
        return w;
    }
}
