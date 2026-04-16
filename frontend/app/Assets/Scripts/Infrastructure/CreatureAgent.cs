using System;
using System.Collections;
using System.Collections.Generic;
using System.Text;
using UnityEngine;
using UnityEngine.Networking;

/// <summary>
/// Dumb messenger — no timer, no Update().
/// PeriodicMind calls TriggerTick() when it decides the LLM should think.
/// Builds a snapshot from the blackboard and POSTs it to the LangGraph backend.
/// </summary>
public class CreatureAgent : MonoBehaviour
{
    [Header("Backend")]
    public string backendUrl = "http://localhost:8000/agent/tick";

    CreatureBlackboard _board;

    public void Init(CreatureBlackboard board)
    {
        _board = board;
    }

    /// <summary>Called by PeriodicMind — never call from Update().</summary>
    public void TriggerTick()
    {
        if (_board == null) return;
        StartCoroutine(SendSnapshot(BuildPayload()));
    }

    // ── Payload ───────────────────────────────────────────────────────────────

    [Serializable] class Payload
    {
        public float        time;
        public SelfData     self;
        public MoodData     mood;
        public HealthData   health;
        public EntityData[] entities;
    }

    [Serializable] class SelfData
    {
        public float x, y, z, rotY;
        public bool  playerInSight;
        public float closestPlayerDist;
    }

    [Serializable] class MoodData
    {
        public float fear, trust, curiosity, social, energy;
    }

    [Serializable] class HealthData
    {
        public float hunger;
    }

    [Serializable] class EntityData
    {
        public string type;      // SensoryEvent.SenseType as string
        public string label;     // human-readable name, e.g. "BP_House_2"
        public string category;  // semantic class, e.g. "house", "lantern", "shelter"
        public float  intensity; // 0-1
        public float  px, py, pz;
    }

    Payload BuildPayload()
    {
        var entities = new List<EntityData>();
        foreach (var evt in _board.sensorEvents)
        {
            entities.Add(new EntityData
            {
                type      = evt.type.ToString(),
                label     = evt.label,
                category  = evt.category,
                intensity = evt.intensity,
                px        = evt.position.x,
                py        = evt.position.y,
                pz        = evt.position.z,
            });
        }

        return new Payload
        {
            time   = Time.time,
            self   = new SelfData
            {
                x                 = transform.position.x,
                y                 = transform.position.y,
                z                 = transform.position.z,
                rotY              = transform.eulerAngles.y,
                playerInSight     = _board.playerInSight,
                closestPlayerDist = _board.closestPlayerDist,
            },
            mood   = new MoodData
            {
                fear      = _board.mood.fear,
                trust     = _board.mood.trust,
                curiosity = _board.mood.curiosity,
                social    = _board.mood.social,
                energy    = _board.mood.energy,
            },
            health   = new HealthData { hunger = _board.health.hunger },
            entities = entities.ToArray(),
        };
    }

    // ── Send ─────────────────────────────────────────────────────────────────

    IEnumerator SendSnapshot(Payload payload)
    {
        string json = JsonUtility.ToJson(payload);
        var    req  = new UnityWebRequest(backendUrl, "POST");
        req.uploadHandler   = new UploadHandlerRaw(Encoding.UTF8.GetBytes(json));
        req.downloadHandler = new DownloadHandlerBuffer();
        req.SetRequestHeader("Content-Type", "application/json");
        Debug.Log("Send via creatureagent");
        yield return req.SendWebRequest();

        if (req.result != UnityWebRequest.Result.Success)
            Debug.LogWarning($"[CreatureAgent] Send failed: {req.error}");
    }
}
