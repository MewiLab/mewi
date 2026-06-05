using System.Collections.Generic;
using UnityEngine;

[DisallowMultipleComponent]
public sealed class PlayerCatTargetFeedbackHud : MonoBehaviour
{
    [Header("Source")]
    [SerializeField] KeyboardProximityCatTargetSource targetSource;

    [Header("Markers")]
    [SerializeField] GameObject candidateMarkerPrefab;
    [SerializeField] GameObject lockedMarkerPrefab;
    [SerializeField] Color candidateColor = new Color(0.1f, 1f, 0.25f, 0.9f);
    [SerializeField] Color lockedColor = new Color(0.15f, 0.45f, 1f, 1f);
    [SerializeField, Min(0f)] float markerHeight = 1.25f;
    [SerializeField, Min(0.01f)] float candidateScale = 0.16f;
    [SerializeField, Min(0.01f)] float lockedScale = 0.24f;
    [SerializeField] bool billboardToCamera = true;
    [SerializeField] bool showSocialMarkers = true;

    readonly Dictionary<string, GameObject> _candidateMarkers = new Dictionary<string, GameObject>();
    GameObject _lockedMarker;
    Material _candidateMaterial;
    Material _lockedMaterial;

    public bool ShowSocialMarkers
    {
        get => showSocialMarkers;
        set
        {
            showSocialMarkers = value;
            if (!showSocialMarkers)
                HideAllMarkers();
        }
    }

    void Awake()
    {
        ResolveSource();
        _candidateMaterial = BuildMaterial(candidateColor);
        _lockedMaterial = BuildMaterial(lockedColor);
    }

    void LateUpdate()
    {
        if (!showSocialMarkers)
        {
            HideAllMarkers();
            return;
        }

        ResolveSource();
        if (targetSource == null)
        {
            HideAllMarkers();
            return;
        }

        targetSource.RebuildCandidates();
        bool hasLockedTarget = targetSource.TryGetCurrent(out PlayerCatTargetLock locked);
        string lockedTargetId = hasLockedTarget && locked.IsValid ? locked.TargetId : "";
        UpdateCandidateMarkers(targetSource.CurrentCandidates, lockedTargetId);
        UpdateLockedMarker(hasLockedTarget, locked);
    }

    public void ShowSocialMarkersNow(bool visible)
    {
        ShowSocialMarkers = visible;
    }

    void UpdateCandidateMarkers(IReadOnlyList<PlayerCatTargetLock> candidates, string lockedTargetId)
    {
        var seen = new HashSet<string>();
        for (int i = 0; i < candidates.Count; i++)
        {
            PlayerCatTargetLock candidate = candidates[i];
            if (!candidate.IsValid)
                continue;
            if (IsSameTarget(candidate.TargetId, lockedTargetId))
                continue;

            seen.Add(candidate.TargetId);
            GameObject marker = GetOrCreateCandidateMarker(candidate.TargetId);
            PositionMarker(marker, candidate.TargetTransform, candidateScale);
            marker.SetActive(true);
        }

        foreach (var pair in _candidateMarkers)
        {
            if (!seen.Contains(pair.Key) && pair.Value != null)
                pair.Value.SetActive(false);
        }
    }

    void UpdateLockedMarker(bool hasLockedTarget, PlayerCatTargetLock locked)
    {
        if (!hasLockedTarget || !locked.IsValid)
        {
            if (_lockedMarker != null)
                _lockedMarker.SetActive(false);
            return;
        }

        if (_lockedMarker == null)
            _lockedMarker = CreateMarker("PlayerCatTargetLock", lockedMarkerPrefab, _lockedMaterial);

        PositionMarker(_lockedMarker, locked.TargetTransform, lockedScale);
        _lockedMarker.SetActive(true);
    }

    GameObject GetOrCreateCandidateMarker(string targetId)
    {
        if (_candidateMarkers.TryGetValue(targetId, out GameObject marker) && marker != null)
            return marker;

        marker = CreateMarker($"PlayerCatCandidate-{targetId}", candidateMarkerPrefab, _candidateMaterial);
        _candidateMarkers[targetId] = marker;
        return marker;
    }

    GameObject CreateMarker(string markerName, GameObject prefab, Material material)
    {
        GameObject marker = prefab != null
            ? Instantiate(prefab)
            : CreateTriangleMarker(markerName, material);

        marker.name = markerName;
        marker.transform.SetParent(transform, worldPositionStays: true);

        Collider collider = marker.GetComponent<Collider>();
        if (collider != null && prefab == null)
            Destroy(collider);

        Renderer renderer = marker.GetComponent<Renderer>()
            ?? marker.GetComponentInChildren<Renderer>();
        if (renderer != null && material != null)
            renderer.sharedMaterial = material;

        marker.SetActive(false);
        return marker;
    }

    void PositionMarker(GameObject marker, Transform target, float scale)
    {
        if (marker == null || target == null)
            return;

        marker.transform.position = target.position + Vector3.up * markerHeight;
        marker.transform.localScale = Vector3.one * scale;
        FaceCamera(marker.transform);
    }

    void HideAllMarkers()
    {
        foreach (var marker in _candidateMarkers.Values)
        {
            if (marker != null)
                marker.SetActive(false);
        }

        if (_lockedMarker != null)
            _lockedMarker.SetActive(false);
    }

    void ResolveSource()
    {
        if (targetSource == null)
            targetSource = GetComponent<KeyboardProximityCatTargetSource>()
                ?? GetComponentInParent<KeyboardProximityCatTargetSource>()
                ?? GetComponentInChildren<KeyboardProximityCatTargetSource>();
    }

    static Material BuildMaterial(Color color)
    {
        Shader shader = Shader.Find("Universal Render Pipeline/Unlit")
            ?? Shader.Find("Unlit/Color")
            ?? Shader.Find("Universal Render Pipeline/Lit")
            ?? Shader.Find("Standard");
        if (shader == null)
            return null;

        var material = new Material(shader)
        {
            color = color,
        };
        if (material.HasProperty("_BaseColor"))
            material.SetColor("_BaseColor", color);
        if (material.HasProperty("_Color"))
            material.SetColor("_Color", color);
        return material;
    }

    static bool IsSameTarget(string a, string b)
        => !string.IsNullOrWhiteSpace(a) &&
           !string.IsNullOrWhiteSpace(b) &&
           string.Equals(a.Trim(), b.Trim(), System.StringComparison.OrdinalIgnoreCase);

    static GameObject CreateTriangleMarker(string markerName, Material material)
    {
        var marker = new GameObject(markerName);
        var meshFilter = marker.AddComponent<MeshFilter>();
        var meshRenderer = marker.AddComponent<MeshRenderer>();

        meshFilter.sharedMesh = BuildDownTriangleMesh();
        if (material != null)
            meshRenderer.sharedMaterial = material;

        return marker;
    }

    static Mesh BuildDownTriangleMesh()
    {
        var mesh = new Mesh
        {
            name = "PlayerCatTargetDownTriangle",
            vertices = new[]
            {
                new Vector3(-0.5f, 0.35f, 0f),
                new Vector3(0.5f, 0.35f, 0f),
                new Vector3(0f, -0.45f, 0f),
            },
            triangles = new[] { 0, 2, 1, 0, 1, 2 },
            uv = new[]
            {
                new Vector2(0f, 1f),
                new Vector2(1f, 1f),
                new Vector2(0.5f, 0f),
            },
        };
        mesh.RecalculateNormals();
        mesh.RecalculateBounds();
        return mesh;
    }

    void FaceCamera(Transform marker)
    {
        if (!billboardToCamera || marker == null)
            return;

        Camera camera = Camera.main;
        if (camera == null)
            return;

        Vector3 toCamera = camera.transform.position - marker.position;
        if (toCamera.sqrMagnitude <= 0.0001f)
            return;

        marker.rotation = Quaternion.LookRotation(toCamera.normalized, Vector3.up);
    }
}
