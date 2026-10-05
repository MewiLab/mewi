#if UNITY_EDITOR
using UnityEditor;
using UnityEngine;

public static class PlayerDashboardMenu
{
    [MenuItem("GameObject/UI/Player Dashboard", false, 10)]
    static void CreatePlayerDashboard(MenuCommand command)
    {
        GameObject dashboardObject = new GameObject("PlayerDashboardUI");
        GameObjectUtility.SetParentAndAlign(dashboardObject, command.context as GameObject);
        Undo.RegisterCreatedObjectUndo(dashboardObject, "Create Player Dashboard");

        PlayerDashboardUI dashboard = dashboardObject.AddComponent<PlayerDashboardUI>();
        dashboardObject.AddComponent<PlayerDashboardToggleListener>();
        dashboardObject.AddComponent<PlayerDashboardCursorController>();
        dashboard.Rebuild();

        Selection.activeObject = dashboardObject;
    }
}
#endif
