using System;
using System.Text;
using System.Threading;
using Cysharp.Threading.Tasks;
using UnityEngine;
using UnityEngine.Networking;

[DisallowMultipleComponent]
public class AttachmentSessionSender : MonoBehaviour
{
    [Header("Backend")]
    [SerializeField] BackendConfig config;

    [Header("Source")]
    [SerializeField] AttachmentBehaviorLogger logger;
    [SerializeField, Min(1)] int minimumEventsToSend = 1;

    [Header("Lifecycle")]
    [SerializeField] bool resetLoggerAfterSuccessfulSend;

    [Header("Debug")]
    [SerializeField] bool logTraffic = true;

    CancellationTokenSource _cts;

    public bool IsSending { get; private set; }
    public AttachmentAnalysisResponse LastResult { get; private set; }

    void Awake()
    {
        _cts = new CancellationTokenSource();
        AutoWire();
    }

    void OnDisable()
    {
        _cts?.Cancel();
        _cts?.Dispose();
        _cts = null;
        IsSending = false;
    }

    public void UseConfig(BackendConfig fallbackConfig)
    {
        if (config == null)
            config = fallbackConfig;
    }

    public void UseLogger(AttachmentBehaviorLogger fallbackLogger)
    {
        if (logger == null)
            logger = fallbackLogger;
    }

    [ContextMenu("Send Current Attachment Session")]
    public void SendCurrentSession()
    {
        SendCurrentSessionAsync().Forget();
    }

    public async UniTask<AttachmentAnalysisResponse> SendCurrentSessionAsync(CancellationToken ct = default(CancellationToken))
    {
        AutoWire();

        if (IsSending)
        {
            if (logTraffic)
                Debug.Log("[AttachmentSessionSender] send skipped: request already in flight");
            return LastResult;
        }

        if (config == null)
        {
            Debug.LogWarning("[AttachmentSessionSender] missing BackendConfig");
            return null;
        }

        if (logger == null)
        {
            Debug.LogWarning("[AttachmentSessionSender] missing AttachmentBehaviorLogger");
            return null;
        }

        if (logger.EventCount < minimumEventsToSend)
        {
            if (logTraffic)
                Debug.Log($"[AttachmentSessionSender] send skipped: only {logger.EventCount} event(s), minimum={minimumEventsToSend}");
            return null;
        }

        AttachmentSessionPayload payload = logger.BuildPayload();
        if (payload.events == null || payload.events.Length == 0)
        {
            Debug.LogWarning("[AttachmentSessionSender] send skipped: payload has no events");
            return null;
        }

        CancellationTokenSource linkedCts = null;
        CancellationToken effectiveCt = ct;
        if (_cts != null)
        {
            if (ct.CanBeCanceled)
            {
                linkedCts = CancellationTokenSource.CreateLinkedTokenSource(ct, _cts.Token);
                effectiveCt = linkedCts.Token;
            }
            else
            {
                effectiveCt = _cts.Token;
            }
        }

        IsSending = true;
        try
        {
            string json = JsonUtility.ToJson(payload);
            using var request = new UnityWebRequest(ApiRoutes.Resolve(config, ApiRoutes.AttachmentSession), "POST");
            request.uploadHandler = new UploadHandlerRaw(Encoding.UTF8.GetBytes(json));
            request.downloadHandler = new DownloadHandlerBuffer();
            request.SetRequestHeader("Content-Type", "application/json");
            config.ApplyAuth(request);

            if (config.requestTimeoutSeconds > 0)
                request.timeout = Mathf.CeilToInt(config.requestTimeoutSeconds);

            if (logTraffic)
                Debug.Log($"[AttachmentSessionSender] POST attachment session events={payload.events.Length}");

            await request.SendWebRequest().ToUniTask(cancellationToken: effectiveCt);

            if (request.result != UnityWebRequest.Result.Success)
            {
                string body = request.downloadHandler != null ? request.downloadHandler.text : "";
                Debug.LogWarning($"[AttachmentSessionSender] POST failed: {request.responseCode} {request.error} {body}");
                return null;
            }

            string responseJson = request.downloadHandler != null ? request.downloadHandler.text : "";
            LastResult = JsonUtility.FromJson<AttachmentAnalysisResponse>(responseJson);

            if (logTraffic && LastResult != null)
            {
                Debug.Log(
                    $"[AttachmentSessionSender] result estimate={LastResult.player_attachment_estimate} " +
                    $"confidence={LastResult.confidence} events={LastResult.n_events}");
            }

            if (resetLoggerAfterSuccessfulSend)
                logger.ResetSession();

            return LastResult;
        }
        catch (OperationCanceledException) { return null; }
        catch (Exception e)
        {
            Debug.LogWarning($"[AttachmentSessionSender] send failed: {e.Message}");
            return null;
        }
        finally
        {
            linkedCts?.Dispose();
            IsSending = false;
        }
    }

    void AutoWire()
    {
        if (logger == null)
            logger = GetComponent<AttachmentBehaviorLogger>();
        if (logger == null)
            logger = GetComponentInParent<AttachmentBehaviorLogger>();
        if (logger == null)
            logger = GetComponentInChildren<AttachmentBehaviorLogger>();

        if (config != null)
            return;

        AgentNetworkManager bridge = GetComponent<AgentNetworkManager>();
        if (bridge == null)
            bridge = GetComponentInParent<AgentNetworkManager>();
        if (bridge == null)
            bridge = GetComponentInChildren<AgentNetworkManager>();

        if (bridge != null)
            config = bridge.config;
    }
}
