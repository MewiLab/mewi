using System.Collections.Generic;
using UnityEditor;
using UnityEngine;
using UnityEngine.SceneManagement;

/// <summary>
/// Editor tool — stamps SmartObject components onto semantic-proxy children
/// by running SemanticCategoryConfig rules against the parent prop's name.
///
/// Expected authoring convention:
///   Each perceptible prop has a child on the "SemanticProp" layer
///   (trigger collider + optional label). The baker adds a SmartObject
///   to that child with tags derived from the parent prop's name.
///
/// Runtime never consults SemanticCategoryConfig. The baker is the only
/// bridge from name-patterns to runtime semantics.
/// </summary>
public static class SmartObjectBaker
{
    const string LAYER_NAME = "SemanticProp";

    [MenuItem("Tools/Mewi/Bake SmartObjects in Open Scene")]
    static void BakeOpenScene()
    {
        var config = LoadConfig();
        if (config == null) return;
        int layer = ResolveLayer();
        if (layer < 0) return;

        var report = new BakeReport();
        foreach (var root in SceneManager.GetActiveScene().GetRootGameObjects())
            WalkAndBake(root.transform, layer, config, report);
        report.Log("Scene");
    }

    [MenuItem("Tools/Mewi/Bake SmartObjects on Selection")]
    static void BakeSelection()
    {
        var config = LoadConfig();
        if (config == null) return;
        int layer = ResolveLayer();
        if (layer < 0) return;

        var report = new BakeReport();
        foreach (var go in Selection.gameObjects)
            WalkAndBake(go.transform, layer, config, report);
        report.Log("Selection");
    }

    [MenuItem("Tools/Mewi/Strip SmartObjects in Open Scene")]
    static void StripOpenScene()
    {
        int removed = 0;
        foreach (var root in SceneManager.GetActiveScene().GetRootGameObjects())
            foreach (var so in root.GetComponentsInChildren<SmartObject>(true))
            {
                Undo.DestroyObjectImmediate(so);
                removed++;
            }
        Debug.Log($"[SmartObjectBaker] Removed {removed} SmartObject components from open scene.");
    }

    // ─────────────────────────────────────────────────────────────────────────

    static void WalkAndBake(Transform t, int layer, SemanticCategoryConfig config, BakeReport report)
    {
        if (t.gameObject.layer == layer)
            TryBake(t.gameObject, config, report);

        for (int i = 0; i < t.childCount; i++)
            WalkAndBake(t.GetChild(i), layer, config, report);
    }

    static void TryBake(GameObject go, SemanticCategoryConfig config, BakeReport report)
    {
        // Skip if already stamped — bakes are idempotent by default.
        if (go.TryGetComponent<SmartObject>(out _))
        {
            report.already++;
            return;
        }

        // The prop's semantic identity lives on the PARENT (BP_House_2, SM_Fish_01, …).
        // The SemanticProp-layered child is just a perception proxy.
        Transform parent = go.transform.parent;
        string propName = parent != null ? parent.name : go.name;

        string category = config.GetCategory(propName);
        if (category == "unknown")
        {
            report.unknown.Add(propName);
            return;
        }

        var so = Undo.AddComponent<SmartObject>(go);
        so.tags  = new List<string> { $"prop.{category}" };
        so.label = !string.IsNullOrEmpty(config.GetLabelOverride(propName))
            ? config.GetLabelOverride(propName)
            : propName;

        EditorUtility.SetDirty(go);
        report.stamped++;
    }

    static SemanticCategoryConfig LoadConfig()
    {
        var guids = AssetDatabase.FindAssets("t:SemanticCategoryConfig");
        if (guids.Length == 0)
        {
            Debug.LogError("[SmartObjectBaker] No SemanticCategoryConfig asset found. Create one via Assets → Create → Creature → Semantic Category Config.");
            return null;
        }
        if (guids.Length > 1)
            Debug.LogWarning($"[SmartObjectBaker] {guids.Length} SemanticCategoryConfig assets found; using {AssetDatabase.GUIDToAssetPath(guids[0])}.");
        return AssetDatabase.LoadAssetAtPath<SemanticCategoryConfig>(AssetDatabase.GUIDToAssetPath(guids[0]));
    }

    static int ResolveLayer()
    {
        int layer = LayerMask.NameToLayer(LAYER_NAME);
        if (layer < 0)
            Debug.LogError($"[SmartObjectBaker] Layer '{LAYER_NAME}' not defined. Add it in Project Settings → Tags and Layers.");
        return layer;
    }

    class BakeReport
    {
        public int stamped;
        public int already;
        public readonly HashSet<string> unknown = new HashSet<string>();

        public void Log(string scope)
        {
            string missing = unknown.Count == 0
                ? ""
                : $"\n  Missing rules for: {string.Join(", ", unknown)}";
            Debug.Log($"[SmartObjectBaker] {scope} — stamped {stamped}, already had component {already}, no rule {unknown.Count}.{missing}");
        }
    }
}
