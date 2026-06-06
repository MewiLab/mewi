using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

/// <summary>
/// Local file outbox for raw report sessions.
/// Stores many JSON files by user and status, then sends them manually during
/// testing without changing the raw-data contract.
/// </summary>
public class ReportSessionFileOutbox : MonoBehaviour
{
    const string PendingStatus = "pending";
    const string SentStatus = "sent";
    const string FailedStatus = "failed";

    [Header("Transport")]
    [SerializeField] ReportSessionSender sender;

    [Header("Storage")]
    [Tooltip("Optional absolute root folder. Empty uses /tmp/mewi_report_sessions (Linux target).")]
    [SerializeField] string rootDirectory = "";
    [Tooltip("Fallback user folder when a payload has no user_id.")]
    [SerializeField] string defaultUserId = "local_user";

    [Header("Debug")]
    [SerializeField] bool sendPendingOnStart;
    [SerializeField] bool logOperations = true;

    bool _sendingBatch;

    public int PendingCount { get; private set; }
    public int SentCount { get; private set; }
    public int FailedCount { get; private set; }
    public string LastSavedPath { get; private set; }
    public string LastUploadResponse { get; private set; }

    void Awake()
    {
        ResolveDefaults();
        EnsureUserDirectories(defaultUserId);
        RefreshCounts();
    }

    void Start()
    {
        if (sendPendingOnStart && PendingCount > 0)
            SendAllPending();
    }

    public string ResolveRootDirectory()
    {
        return string.IsNullOrWhiteSpace(rootDirectory)
            ? Path.Combine("/tmp", "mewi_report_sessions")
            : rootDirectory.Trim();
    }

    public string SavePending(ReportSessionPayload payload)
    {
        if (payload == null || payload.session == null)
        {
            Debug.LogWarning("[ReportSessionFileOutbox] no report session payload to save.");
            return "";
        }

        string userId = SafePathSegment(string.IsNullOrWhiteSpace(payload.user_id) ? defaultUserId : payload.user_id);
        EnsureUserDirectories(userId);
        string dir = UserStatusDirectory(userId, PendingStatus);

        string fileName = $"{SafePathSegment(payload.session.session_id)}.json";
        string path = UniquePath(Path.Combine(dir, fileName));
        string tmpPath = path + ".tmp";

        File.WriteAllText(tmpPath, JsonUtility.ToJson(payload, true));
        if (File.Exists(path))
            File.Delete(path);
        File.Move(tmpPath, path);

        LastSavedPath = path;
        RefreshCounts();

        if (logOperations)
            Debug.Log($"[ReportSessionFileOutbox] saved pending session {path}");

        return path;
    }

    [ContextMenu("Report Outbox/Refresh Counts")]
    public void RefreshCounts()
    {
        PendingCount = FindFiles(PendingStatus).Count;
        SentCount = FindFiles(SentStatus).Count;
        FailedCount = FindFiles(FailedStatus).Count;
    }

    [ContextMenu("Report Outbox/Send Latest Pending")]
    public void SendLatestPending()
    {
        if (!CanSendNow())
            return;

        List<string> files = FindFiles(PendingStatus);
        if (files.Count == 0)
        {
            Debug.Log("[ReportSessionFileOutbox] no pending report sessions.");
            return;
        }

        SendFile(files[files.Count - 1]);
    }

    [ContextMenu("Report Outbox/Send All Pending")]
    public void SendAllPending()
    {
        if (!CanSendNow())
            return;

        if (_sendingBatch)
        {
            Debug.LogWarning("[ReportSessionFileOutbox] already sending a batch.");
            return;
        }

        List<string> files = FindFiles(PendingStatus);
        if (files.Count == 0)
        {
            Debug.Log("[ReportSessionFileOutbox] no pending report sessions.");
            return;
        }

        StartCoroutine(SendFilesSequentially(files));
    }

    public void SendFile(string path)
    {
        SendFile(path, null);
    }

    public void SendFile(string path, Action<ReportSessionSendResult> onComplete)
    {
        if (!CanSendNow())
        {
            if (onComplete != null)
                onComplete(null);
            return;
        }

        ResolveDefaults();
        if (sender == null)
        {
            Debug.LogWarning("[ReportSessionFileOutbox] missing ReportSessionSender.");
            if (onComplete != null)
                onComplete(null);
            return;
        }
        if (string.IsNullOrWhiteSpace(path) || !File.Exists(path))
        {
            Debug.LogWarning($"[ReportSessionFileOutbox] missing report session file: {path}");
            if (onComplete != null)
                onComplete(null);
            return;
        }

        string json = File.ReadAllText(path);
        string label = Path.GetFileName(path);
        sender.SendJson(json, label, result =>
        {
            HandleSendResult(path, result);
            if (onComplete != null)
                onComplete(result);
        });
    }

    [ContextMenu("Report Outbox/Move Failed Back To Pending")]
    public void MoveFailedBackToPending()
    {
        List<string> failed = FindFiles(FailedStatus);
        for (int i = 0; i < failed.Count; i++)
            MoveToStatus(failed[i], PendingStatus);

        RefreshCounts();
        if (logOperations)
            Debug.Log($"[ReportSessionFileOutbox] moved {failed.Count} failed file(s) back to pending.");
    }

    IEnumerator SendFilesSequentially(List<string> files)
    {
        _sendingBatch = true;
        for (int i = 0; i < files.Count; i++)
        {
            string path = files[i];
            bool done = false;
            SendFileWithCallback(path, () => done = true);
            while (!done)
                yield return null;
        }
        _sendingBatch = false;
        RefreshCounts();
    }

    void SendFileWithCallback(string path, Action onDone)
    {
        ResolveDefaults();
        if (sender == null || string.IsNullOrWhiteSpace(path) || !File.Exists(path))
        {
            if (onDone != null)
                onDone();
            return;
        }

        string json = File.ReadAllText(path);
        string label = Path.GetFileName(path);
        sender.SendJson(json, label, result =>
        {
            HandleSendResult(path, result);
            if (onDone != null)
                onDone();
        });
    }

    void HandleSendResult(string path, ReportSessionSendResult result)
    {
        LastUploadResponse = result != null ? result.responseText : "";
        bool success = result != null && result.success;
        string status = success ? SentStatus : FailedStatus;
        string movedPath = MoveToStatus(path, status);

        RefreshCounts();
        if (logOperations)
        {
            string code = result != null ? result.responseCode.ToString() : "0";
            Debug.Log($"[ReportSessionFileOutbox] moved {Path.GetFileName(path)} to {status} ({code}) -> {movedPath}");
        }
    }

    string MoveToStatus(string path, string status)
    {
        if (string.IsNullOrWhiteSpace(path) || !File.Exists(path))
            return "";

        FileInfo file = new FileInfo(path);
        DirectoryInfo statusDir = file.Directory;
        DirectoryInfo userDir = statusDir != null ? statusDir.Parent : null;
        string userPath = userDir != null ? userDir.FullName : ResolveRootDirectory();
        string targetDir = Path.Combine(userPath, status);

        Directory.CreateDirectory(targetDir);
        string targetPath = UniquePath(Path.Combine(targetDir, file.Name));
        File.Move(path, targetPath);
        return targetPath;
    }

    List<string> FindFiles(string status)
    {
        var files = new List<string>();
        string root = ResolveRootDirectory();
        if (!Directory.Exists(root))
            return files;

        string[] statusDirs = Directory.GetDirectories(root, status, SearchOption.AllDirectories);
        for (int i = 0; i < statusDirs.Length; i++)
        {
            string[] jsonFiles = Directory.GetFiles(statusDirs[i], "*.json", SearchOption.TopDirectoryOnly);
            files.AddRange(jsonFiles);
        }

        files.Sort(StringComparer.OrdinalIgnoreCase);
        return files;
    }

    string UserStatusDirectory(string userId, string status)
    {
        return Path.Combine(ResolveRootDirectory(), SafePathSegment(userId), status);
    }

    void EnsureUserDirectories(string userId)
    {
        string safeUserId = SafePathSegment(string.IsNullOrWhiteSpace(userId) ? defaultUserId : userId);
        Directory.CreateDirectory(UserStatusDirectory(safeUserId, PendingStatus));
        Directory.CreateDirectory(UserStatusDirectory(safeUserId, SentStatus));
        Directory.CreateDirectory(UserStatusDirectory(safeUserId, FailedStatus));
    }

    static string UniquePath(string path)
    {
        if (!File.Exists(path))
            return path;

        string dir = Path.GetDirectoryName(path) ?? "";
        string name = Path.GetFileNameWithoutExtension(path);
        string ext = Path.GetExtension(path);
        int i = 2;
        string candidate;
        do
        {
            candidate = Path.Combine(dir, $"{name}_{i}{ext}");
            i++;
        }
        while (File.Exists(candidate));

        return candidate;
    }

    static string SafePathSegment(string value)
    {
        if (string.IsNullOrWhiteSpace(value))
            return "unknown";

        char[] chars = value.Trim().ToCharArray();
        for (int i = 0; i < chars.Length; i++)
        {
            char c = chars[i];
            if (!(char.IsLetterOrDigit(c) || c == '_' || c == '-' || c == '.'))
                chars[i] = '_';
        }
        return new string(chars);
    }

    void ResolveDefaults()
    {
        if (sender == null)
            sender = GetComponent<ReportSessionSender>();
    }

    bool CanSendNow()
    {
        if (Application.isPlaying)
            return true;

        Debug.LogWarning("[ReportSessionFileOutbox] enter Play Mode before sending report sessions.");
        return false;
    }
}
