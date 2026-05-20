using System;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// Scene-authored lookup from backend target keys to world transforms.
/// Keeps semantic scene resolution out of transport code.
/// </summary>
public class NamedTargetRegistry : MonoBehaviour
{
    [Serializable]
    public class Entry
    {
        public string key;
        public Transform target;
    }

    [SerializeField] List<Entry> entries = new List<Entry>();
    [SerializeField] bool autoRegisterSmartObjects = true;
    [SerializeField] bool fallbackToGameObjectName = true;

    Dictionary<string, Transform> _map;

    public IReadOnlyCollection<string> KnownKeys
    {
        get
        {
            if (_map == null) Rebuild();
            return _map.Keys;
        }
    }

    void Awake()
    {
        Rebuild();
    }

    void OnValidate()
    {
        if (Application.isPlaying) Rebuild();
    }

    public bool TryResolve(string key, out Transform target)
    {
        if (_map == null) Rebuild();
        target = null;
        if (string.IsNullOrWhiteSpace(key))
            return false;

        string normalized = key.Trim();
        if (_map.TryGetValue(normalized, out target) && target != null)
            return true;

        if (autoRegisterSmartObjects)
        {
            Rebuild();
            if (_map.TryGetValue(normalized, out target) && target != null)
                return true;
        }

        if (!fallbackToGameObjectName)
            return false;

        GameObject found = GameObject.Find(normalized);
        if (found == null)
            return false;

        target = found.transform;
        _map[normalized] = target;
        return true;
    }

    void Rebuild()
    {
        _map = new Dictionary<string, Transform>(StringComparer.OrdinalIgnoreCase);
        foreach (var entry in entries)
        {
            if (entry == null || entry.target == null || string.IsNullOrWhiteSpace(entry.key))
                continue;

            Register(entry.key, entry.target);
        }

        if (!autoRegisterSmartObjects) return;

        var smartObjects = FindObjectsByType<SmartObject>(FindObjectsSortMode.None);
        foreach (var smartObject in smartObjects)
        {
            if (smartObject == null) continue;

            Transform target = smartObject.perceptionCenter != null
                ? smartObject.perceptionCenter
                : smartObject.transform;

            Register(smartObject.Label, target);
            Register(smartObject.gameObject.name, target);
            if (smartObject.transform.parent != null)
                Register(smartObject.transform.parent.name, smartObject.transform.parent);
        }
    }

    void Register(string key, Transform target)
    {
        if (string.IsNullOrWhiteSpace(key) || target == null)
            return;

        _map[key.Trim()] = target;
    }
}
