using UnityEngine;

public static class ZoneVolumeUtility
{
    public static Vector3 CenterOrTransform(ZoneVolume zone)
    {
        if (zone == null) return Vector3.zero;
        return TryGetBoundsCenter(zone, out Vector3 center) ? center : zone.transform.position;
    }

    public static bool TryGetBoundsCenter(ZoneVolume zone, out Vector3 center)
    {
        center = Vector3.zero;
        if (!TryGetBounds(zone, out Bounds bounds)) return false;
        center = bounds.center;
        return true;
    }

    public static bool TryGetBounds(ZoneVolume zone, out Bounds bounds)
    {
        bounds = default;
        if (zone == null) return false;

        Collider[] colliders = zone.GetComponentsInChildren<Collider>();
        bool hasBounds = false;

        for (int i = 0; i < colliders.Length; i++)
        {
            Collider collider = colliders[i];
            if (collider == null || !collider.enabled) continue;
            if (!IsZoneFootprintCollider(zone, collider)) continue;

            if (!hasBounds)
            {
                bounds = collider.bounds;
                hasBounds = true;
            }
            else
            {
                bounds.Encapsulate(collider.bounds);
            }
        }

        if (!hasBounds) return false;
        return true;
    }

    static bool IsZoneFootprintCollider(ZoneVolume zone, Collider collider)
    {
        if (zone == null || collider == null || !collider.isTrigger) return false;

        Transform t = collider.transform;
        while (t != null)
        {
            if (t == zone.transform) return true;
            t = t.parent;
        }
        return false;
    }
}
