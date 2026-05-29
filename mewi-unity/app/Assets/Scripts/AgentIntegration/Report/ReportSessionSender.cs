using System.Collections;
using System.Text;
using UnityEngine;
using UnityEngine.Networking;

/// <summary>
/// Thin transport for uploading one immutable report session to FastAPI.
/// Unity does not know storage details; the backend owns local files/S3/etc.
/// </summary>
public class ReportSessionSender : MonoBehaviour
{
    [Header("Backend")]
    public BackendConfig config;

    [Header("Debug")]
    [SerializeField] bool logTraffic = true;

    public void Send(ReportSessionPayload payload)
    {
        if (payload == null || payload.session == null)
        {
            Debug.LogWarning("[ReportSessionSender] skipped null report session payload.");
            return;
        }

        StartCoroutine(SendCoroutine(payload));
    }

    IEnumerator SendCoroutine(ReportSessionPayload payload)
    {
        if (config == null)
        {
            Debug.LogWarning("[ReportSessionSender] missing BackendConfig.");
            yield break;
        }

        string url = ApiRoutes.ResolveHttp(config, ApiRoutes.ReportSession);
        string json = JsonUtility.ToJson(payload);
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

            if (request.result != UnityWebRequest.Result.Success)
            {
                Debug.LogWarning($"[ReportSessionSender] upload failed: {request.responseCode} {request.error} {request.downloadHandler.text}");
                yield break;
            }

            if (logTraffic)
                Debug.Log($"[ReportSessionSender] uploaded session={payload.session.session_id} response={request.downloadHandler.text}");
        }
    }
}
