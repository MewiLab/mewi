#if UNITY_EDITOR
using UnityEditor;
using UnityEngine;

[CustomEditor(typeof(ReportSessionFileOutbox))]
public class ReportSessionFileOutboxEditor : Editor
{
    public override void OnInspectorGUI()
    {
        DrawDefaultInspector();

        var outbox = (ReportSessionFileOutbox)target;
        outbox.RefreshCounts();

        EditorGUILayout.Space();
        EditorGUILayout.LabelField("Pending", outbox.PendingCount.ToString());
        EditorGUILayout.LabelField("Sent", outbox.SentCount.ToString());
        EditorGUILayout.LabelField("Failed", outbox.FailedCount.ToString());

        EditorGUILayout.Space();
        if (GUILayout.Button("Reveal Outbox Folder"))
            EditorUtility.RevealInFinder(outbox.ResolveRootDirectory());

        using (new EditorGUI.DisabledScope(!Application.isPlaying))
        {
            if (GUILayout.Button("Send Latest Pending"))
                outbox.SendLatestPending();
            if (GUILayout.Button("Send All Pending"))
                outbox.SendAllPending();
            if (GUILayout.Button("Move Failed Back To Pending"))
                outbox.MoveFailedBackToPending();
        }

        if (!Application.isPlaying)
            EditorGUILayout.HelpBox("Enter Play Mode to send files; saving and folder reveal are available from the component at any time.", MessageType.Info);
    }
}
#endif
