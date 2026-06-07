// Hand-authored "2D circle on the ground" the cat may roam inside.
// See docs/decisions/ADR-041-ambient-wander-and-exploration-zones.md.
//
// Authoring:
//   1. Create an empty GameObject on the ground (e.g. WZ_Harbor_01).
//   2. Add this WanderZone component.
//   3. Set the radius; move it so the gizmo circle sits on the walkable ground.
//   4. Place zones OVERLAPPING. Overlap is not cosmetic: two zones whose circles
//      intersect become "neighbors", and the cat hops along that neighbor web so
//      its roaming flows and stays inside the painted region.
//   5. Add a WanderZoneRegistry once anywhere in the scene; it auto-collects all
//      WanderZones and computes the neighbor graph.
//
// This component is descriptive only. It never moves the cat; the registry hands
// chosen points to the existing go_to / wander motor path.

using System.Collections.Generic;
using UnityEngine;

[DisallowMultipleComponent]
public class WanderZone : MonoBehaviour
{
    [Tooltip("Optional id for debugging/snapshots. Falls back to the GameObject name.")]
    public string zoneId = "";

    [Tooltip("Circle radius in metres. The cat picks jittered points inside this on the XZ plane.")]
    [Min(0.1f)] public float radius = 4f;

    [Tooltip("How far inside the radius the cat keeps its picked points (0 = anywhere, 0.9 = hug the centre).")]
    [Range(0f, 0.95f)] public float innerMargin = 0.15f;

    [Header("Gizmo")]
    [SerializeField] Color gizmoColor = new Color(0.3f, 0.8f, 1f, 0.9f);
    [SerializeField] bool drawNeighborLinks = true;

    public string EffectiveZoneId =>
        string.IsNullOrEmpty(zoneId) ? gameObject.name : zoneId;

    /// <summary>World-space centre of the zone (ground point).</summary>
    public Vector3 Center => transform.position;

    /// <summary>
    /// Two zones are neighbors when their circles overlap (or are within
    /// <paramref name="slack"/> of touching). Compared on the XZ plane so a small
    /// height difference between ground patches does not break adjacency.
    /// </summary>
    public bool IsNeighbor(WanderZone other, float slack = 0.5f)
    {
        if (other == null || other == this) return false;
        Vector3 a = Center, b = other.Center;
        float dx = a.x - b.x;
        float dz = a.z - b.z;
        float flatSqr = dx * dx + dz * dz;
        float reach = radius + other.radius + Mathf.Max(0f, slack);
        return flatSqr <= reach * reach;
    }

    /// <summary>
    /// A random point inside the zone on the XZ plane, area-uniform, kept within
    /// <see cref="innerMargin"/>. Y is the zone centre's height; callers should
    /// still NavMesh-sample before committing.
    /// </summary>
    public Vector3 RandomPoint()
    {
        float usable = radius * (1f - innerMargin);
        // sqrt keeps the distribution uniform over area instead of clustering centre.
        float r = usable * Mathf.Sqrt(Random.value);
        float theta = Random.value * Mathf.PI * 2f;
        Vector3 c = Center;
        return new Vector3(c.x + Mathf.Cos(theta) * r, c.y, c.z + Mathf.Sin(theta) * r);
    }

    void OnDrawGizmos()
    {
        DrawCircle(Center, radius, gizmoColor);
    }

    void OnDrawGizmosSelected()
    {
        if (!drawNeighborLinks) return;
        // Editor-time only: show which zones this one connects to so designers can
        // see the web while placing overlapping circles.
        var all = FindObjectsByType<WanderZone>(FindObjectsSortMode.None);
        Gizmos.color = new Color(1f, 0.9f, 0.2f, 0.9f);
        foreach (var z in all)
        {
            if (IsNeighbor(z))
                Gizmos.DrawLine(Center, z.Center);
        }
    }

    static void DrawCircle(Vector3 center, float radius, Color color)
    {
        const int segments = 36;
        Gizmos.color = color;
        Vector3 prev = center + new Vector3(radius, 0f, 0f);
        for (int i = 1; i <= segments; i++)
        {
            float t = (i / (float)segments) * Mathf.PI * 2f;
            Vector3 next = center + new Vector3(Mathf.Cos(t) * radius, 0f, Mathf.Sin(t) * radius);
            Gizmos.DrawLine(prev, next);
            prev = next;
        }
    }
}
