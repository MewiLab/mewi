using System;
using System.Text;
using System.Threading;
using Cysharp.Threading.Tasks;
using UnityEngine;
using UnityEngine.Networking;

public class HttpActionReporter : MonoBehaviour
{
    [SerializeField] BackendConfig config;
    [SerializeField] bool logReports;

    CancellationTokenSource _cts;

    void Awake()
    {
        _cts = new CancellationTokenSource();
    }

    void OnDisable()
    {
        _cts?.Cancel();
        _cts?.Dispose();
        _cts = null;
    }

    public void UseConfig(BackendConfig fallbackConfig)
    {
        if (config == null)
            config = fallbackConfig;
    }

    public void Report(ActionReport report)
    {
        if (report == null) return;

        if (config == null)
        {
            if (logReports)
                Debug.Log($"[ActionReport] {report.agent_id} {report.commandId} {report.action} {report.status}: {report.reason}");
            return;
        }

        SendAsync(report, _cts?.Token ?? CancellationToken.None).Forget();
    }

    async UniTaskVoid SendAsync(ActionReport report, CancellationToken ct)
    {
        try
        {
            string json = JsonUtility.ToJson(report);
            using var req = new UnityWebRequest(ApiRoutes.Resolve(config, ApiRoutes.AgentReport), "POST");
            req.uploadHandler = new UploadHandlerRaw(Encoding.UTF8.GetBytes(json));
            req.downloadHandler = new DownloadHandlerBuffer();
            req.SetRequestHeader("Content-Type", "application/json");
            config.ApplyAuth(req);
            if (config.requestTimeoutSeconds > 0)
                req.timeout = Mathf.CeilToInt(config.requestTimeoutSeconds);

            await req.SendWebRequest().ToUniTask(cancellationToken: ct);

            if (req.result != UnityWebRequest.Result.Success)
                Debug.LogWarning($"[ActionReport] POST failed: {req.error}");
            else if (logReports)
                Debug.Log($"[ActionReport] sent {report.commandId} {report.status}");
        }
        catch (OperationCanceledException) { }
        catch (Exception e)
        {
            Debug.LogWarning($"[ActionReport] send failed: {e.Message}");
        }
    }
}
