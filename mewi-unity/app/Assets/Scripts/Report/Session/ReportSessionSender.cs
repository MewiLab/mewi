using System;
using System.Collections;
using System.Text;
using UnityEngine;
using UnityEngine.Networking;

public class ReportSessionSendResult
{
    public bool success;
    public long responseCode;
    public string error;
    public string responseText;
    public string requestLabel;
}

/// <summary>
/// Thin transport for uploading one closed-session report payload to FastAPI.
/// Unity does not know storage details; the backend owns local files/S3/etc.
/// This is separate from the live websocket tick/report channel.
/// </summary>
public class ReportSessionSender : MonoBehaviour
{
    [Header("Backend")]
    public BackendConfig config;

    [Header("Debug")]
    [SerializeField] bool logTraffic = true;

    public void Send(ReportSessionPayload payload)
    {
        Send(payload, null);
    }

    public void Send(ReportSessionPayload payload, Action<ReportSessionSendResult> onComplete)
    {
        if (payload == null || payload.session == null)
        {
            Debug.LogWarning("[ReportSessionSender] skipped null report session payload.");
            if (onComplete != null)
            {
                onComplete(new ReportSessionSendResult
                {
                    success = false,
                    responseCode = 0,
                    error = "Null report session payload.",
                    responseText = "",
                    requestLabel = "",
                });
            }
            return;
        }

        string json = JsonUtility.ToJson(payload);
        SendJson(json, payload.session.session_id, onComplete);
    }

    public void SendJson(string json, string requestLabel, Action<ReportSessionSendResult> onComplete)
    {
        if (string.IsNullOrWhiteSpace(json))
        {
            Debug.LogWarning("[ReportSessionSender] skipped empty report session JSON.");
            if (onComplete != null)
            {
                onComplete(new ReportSessionSendResult
                {
                    success = false,
                    responseCode = 0,
                    error = "Empty report session JSON.",
                    responseText = "",
                    requestLabel = requestLabel ?? "",
                });
            }
            return;
        }

        StartCoroutine(SendJsonCoroutine(json, requestLabel ?? "", onComplete));
    }

    IEnumerator SendJsonCoroutine(string json, string requestLabel, Action<ReportSessionSendResult> onComplete)
    {
        if (config == null)
        {
            Debug.LogWarning("[ReportSessionSender] missing BackendConfig.");
            if (onComplete != null)
            {
                onComplete(new ReportSessionSendResult
                {
                    success = false,
                    responseCode = 0,
                    error = "Missing BackendConfig.",
                    responseText = "",
                    requestLabel = requestLabel,
                });
            }
            yield break;
        }

        string url = ApiRoutes.ResolveHttp(config, ApiRoutes.ReportSession);
        byte[] body = Encoding.UTF8.GetBytes(json);

        using (var request = new UnityWebRequest(url, UnityWebRequest.kHttpVerbPOST))
        {
            request.uploadHandler = new UploadHandlerRaw(body);
            request.downloadHandler = new DownloadHandlerBuffer();
            request.SetRequestHeader("Content-Type", "application/json");
            config.ApplyAuth(request);

            if (config.requestTimeoutSeconds > 0f)
                request.timeout = Mathf.CeilToInt(config.requestTimeoutSeconds);

            if (logTraffic)
                Debug.Log($"[ReportSessionSender] POST {url} bytes={body.Length}");

            yield return request.SendWebRequest();

            var result = new ReportSessionSendResult
            {
                success = request.result == UnityWebRequest.Result.Success,
                responseCode = request.responseCode,
                error = request.error ?? "",
                responseText = request.downloadHandler != null ? request.downloadHandler.text : "",
                requestLabel = requestLabel,
            };

            if (!result.success)
            {
                Debug.LogWarning($"[ReportSessionSender] upload failed: {result.responseCode} {result.error} {result.responseText}");
            }
            else if (logTraffic)
            {
                Debug.Log($"[ReportSessionSender] uploaded {requestLabel} response={result.responseText}");
            }

            if (onComplete != null)
                onComplete(result);
        }
    }
}
