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

    Dictionary<string, Transform> _map;

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
        return !string.IsNullOrWhiteSpace(key)
            && _map.TryGetValue(key.Trim(), out target)
            && target != null;
    }

    void Rebuild()
    {
        _map = new Dictionary<string, Transform>(StringComparer.OrdinalIgnoreCase);
        foreach (var entry in entries)
        {
            if (entry == null || entry.target == null || string.IsNullOrWhiteSpace(entry.key))
                continue;

            _map[entry.key.Trim()] = entry.target;
        }
    }
}
