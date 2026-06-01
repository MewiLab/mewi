using System;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// App-level websocket message dispatcher.
/// Parses backend websocket messages and stores per-creature directives.
/// </summary>
[DisallowMultipleComponent]
public sealed class AgentWebSocketDispatcher : MonoBehaviour
{
    readonly Dictionary<string, DirectiveMessage> _latestDirectiveByCreature =
        new Dictionary<string, DirectiveMessage>(StringComparer.OrdinalIgnoreCase);

    [Serializable] sealed class IntentDecisionPayload
    {
        public string intent = "";
        public string target_id = "";
        public string target = "";
        public string reasoning = "";
    }

    [Serializable] sealed class AgentPlanResponse
    {
        public string type        = "";
        public string job_id      = "";
        public string creature_id = "";
        public string request_id  = "";
        public string status      = "";
        public IntentDecisionPayload intent;
        public string reasoning   = "";
        public string error       = "";
    }

    sealed class DirectiveMessage
    {
        public string requestId = "";
        public string intent = "";
        public string target = "";
    }

    public void HandleServerMessage(string message, AgentNetworkHub hub, bool logTraffic)
    {
        if (hub == null)
            return;

        AgentPlanResponse response;
        try
        {
            response = JsonUtility.FromJson<AgentPlanResponse>(message);
        }
        catch (Exception e)
        {
            Debug.LogWarning($"[AgentWebSocketDispatcher] failed to parse websocket response: {e.Message}");
            return;
        }

        if (response == null)
        {
            Debug.LogWarning("[AgentWebSocketDispatcher] websocket response parsed null");
            return;
        }

        string messageType = (response.type ?? "").Trim().ToLowerInvariant();
        if (messageType == "registered")
        {
            if (logTraffic)
                Debug.Log("[AgentWebSocketDispatcher] backend acknowledged creature registration");
            return;
        }

        string creatureId = Normalize(response.creature_id);
        string requestId = response.request_id ?? "";
        if (string.IsNullOrEmpty(creatureId))
        {
            Debug.LogWarning($"[AgentWebSocketDispatcher] websocket response missing creature_id: {message}");
            return;
        }

        string status = (response.status ?? "").Trim().ToLowerInvariant();
        if (status == "queued" || status == "processing")
        {
            if (logTraffic)
                Debug.Log($"[AgentWebSocketDispatcher] job {response.job_id} status={status} creature={creatureId} request={requestId}");
            return;
        }

        if (!hub.TryCompleteRequest(creatureId, requestId))
        {
            Debug.LogWarning($"[AgentWebSocketDispatcher] stale/unmatched response creature={creatureId} request={requestId} status={status}");
            return;
        }

        if (status == "error")
        {
            hub.RecordFailedResponse();
            Debug.LogWarning($"[AgentWebSocketDispatcher] job {response.job_id} errored creature={creatureId} request={requestId}: {response.error}");
            return;
        }

        if (status != "done")
        {
            if (logTraffic)
                Debug.Log($"[AgentWebSocketDispatcher] job {response.job_id} ended status={response.status} creature={creatureId} request={requestId}");
            return;
        }

        if (response.intent == null || string.IsNullOrWhiteSpace(response.intent.intent))
        {
            if (logTraffic)
                Debug.Log($"[AgentWebSocketDispatcher] job {response.job_id} done with no directive creature={creatureId} request={requestId}");
            return;
        }

        string target = !string.IsNullOrWhiteSpace(response.intent.target_id)
            ? response.intent.target_id
            : (response.intent.target ?? "");

        _latestDirectiveByCreature[creatureId] = new DirectiveMessage
        {
            requestId = requestId,
            intent = response.intent.intent.Trim(),
            target = target,
        };

        if (logTraffic)
            Debug.Log($"[AgentWebSocketDispatcher] directive creature={creatureId} request={requestId} intent={response.intent.intent}{(string.IsNullOrEmpty(target) ? "" : $" target={target}")}");
    }

    public bool TryConsumeDirective(string creatureId, out string intent, out string target)
    {
        intent = "";
        target = "";

        string id = Normalize(creatureId);
        if (string.IsNullOrEmpty(id))
            return false;

        if (!_latestDirectiveByCreature.TryGetValue(id, out DirectiveMessage message))
            return false;

        _latestDirectiveByCreature.Remove(id);
        if (message == null || string.IsNullOrWhiteSpace(message.intent))
            return false;

        intent = message.intent;
        target = message.target ?? "";
        return true;
    }

    static string Normalize(string creatureId)
        => string.IsNullOrWhiteSpace(creatureId) ? "" : creatureId.Trim();
}
