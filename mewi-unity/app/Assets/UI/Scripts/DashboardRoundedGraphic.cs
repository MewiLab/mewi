using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;

/// <summary>
/// Lightweight filled rounded rectangle for transparent dashboard widgets.
/// Avoids sprite dependencies so the dashboard can be dropped into any scene.
/// </summary>
[RequireComponent(typeof(CanvasRenderer))]
public sealed class DashboardRoundedGraphic : MaskableGraphic
{
    [SerializeField, Min(0f)] float cornerRadius = 18f;
    [SerializeField, Range(2, 16)] int cornerSegments = 8;

    public float CornerRadius
    {
        get { return cornerRadius; }
        set
        {
            cornerRadius = Mathf.Max(0f, value);
            SetVerticesDirty();
        }
    }

    protected override void OnPopulateMesh(VertexHelper vh)
    {
        vh.Clear();

        Rect rect = GetPixelAdjustedRect();
        float radius = Mathf.Min(cornerRadius, Mathf.Min(rect.width, rect.height) * 0.5f);
        int segments = Mathf.Max(2, cornerSegments);

        var points = new List<Vector2>((segments + 1) * 4);
        AddCorner(points, new Vector2(rect.xMax - radius, rect.yMax - radius), radius, 90f, 0f, segments);
        AddCorner(points, new Vector2(rect.xMax - radius, rect.yMin + radius), radius, 0f, -90f, segments);
        AddCorner(points, new Vector2(rect.xMin + radius, rect.yMin + radius), radius, -90f, -180f, segments);
        AddCorner(points, new Vector2(rect.xMin + radius, rect.yMax - radius), radius, 180f, 90f, segments);

        Color32 fill = color;
        vh.AddVert(rect.center, fill, Vector2.zero);

        for (int i = 0; i < points.Count; i++)
            vh.AddVert(points[i], fill, Vector2.zero);

        for (int i = 0; i < points.Count; i++)
        {
            int next = i + 1;
            if (next >= points.Count) next = 0;
            vh.AddTriangle(0, i + 1, next + 1);
        }
    }

    static void AddCorner(
        List<Vector2> points,
        Vector2 center,
        float radius,
        float startDegrees,
        float endDegrees,
        int segments)
    {
        if (radius <= 0f)
        {
            points.Add(center);
            return;
        }

        for (int i = 0; i <= segments; i++)
        {
            float t = i / (float)segments;
            float angle = Mathf.Lerp(startDegrees, endDegrees, t) * Mathf.Deg2Rad;
            points.Add(center + new Vector2(Mathf.Cos(angle), Mathf.Sin(angle)) * radius);
        }
    }
}
