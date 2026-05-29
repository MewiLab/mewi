using UnityEngine;

/// <summary>
/// Coordinates cursor visibility, lock state, and optional cursor textures while
/// the player dashboard is open.
/// </summary>
public sealed class PlayerDashboardCursorController : MonoBehaviour
{
    [SerializeField] PlayerDashboardUI dashboard;

    [Header("Behavior")]
    [SerializeField] bool controlCursor = true;
    [SerializeField] bool applyGameplayStateOnStart = true;
    [SerializeField] bool applyGameplayStateOnClose = true;

    [Header("Dashboard Cursor")]
    [SerializeField] bool dashboardCursorVisible = true;
    [SerializeField] CursorLockMode dashboardLockMode = CursorLockMode.None;
    [SerializeField] Texture2D dashboardCursorTexture;
    [SerializeField] Vector2 dashboardCursorHotspot = Vector2.zero;

    [Header("Gameplay Cursor")]
    [SerializeField] bool gameplayCursorVisible;
    [SerializeField] CursorLockMode gameplayLockMode = CursorLockMode.Locked;
    [SerializeField] Texture2D gameplayCursorTexture;
    [SerializeField] Vector2 gameplayCursorHotspot = Vector2.zero;

    [Header("Texture")]
    [SerializeField] CursorMode cursorMode = CursorMode.Auto;

    void Awake()
    {
        if (dashboard == null)
            dashboard = GetComponent<PlayerDashboardUI>() ?? FindFirstObjectByType<PlayerDashboardUI>();

        if (dashboard == null)
            return;

        dashboard.opened.AddListener(OnDashboardOpened);
        dashboard.closed.AddListener(OnDashboardClosed);
    }

    void Start()
    {
        if (!controlCursor)
            return;

        if (dashboard != null && dashboard.IsVisible)
            ApplyDashboardCursor();
        else if (applyGameplayStateOnStart)
            ApplyGameplayCursor();
    }

    void OnDestroy()
    {
        if (dashboard == null)
            return;

        dashboard.opened.RemoveListener(OnDashboardOpened);
        dashboard.closed.RemoveListener(OnDashboardClosed);
    }

    public void ApplyDashboardCursor()
    {
        ApplyCursor(dashboardCursorVisible, dashboardLockMode, dashboardCursorTexture, dashboardCursorHotspot);
    }

    public void ApplyGameplayCursor()
    {
        ApplyCursor(gameplayCursorVisible, gameplayLockMode, gameplayCursorTexture, gameplayCursorHotspot);
    }

    void OnDashboardOpened()
    {
        if (controlCursor)
            ApplyDashboardCursor();
    }

    void OnDashboardClosed()
    {
        if (controlCursor && applyGameplayStateOnClose)
            ApplyGameplayCursor();
    }

    void ApplyCursor(bool visible, CursorLockMode lockMode, Texture2D texture, Vector2 hotspot)
    {
        Cursor.lockState = lockMode;
        Cursor.visible = visible;
        Cursor.SetCursor(texture, ValidHotspot(texture, hotspot), cursorMode);
    }

    static Vector2 ValidHotspot(Texture2D texture, Vector2 hotspot)
    {
        if (texture == null)
            return Vector2.zero;

        return new Vector2(
            Mathf.Clamp(hotspot.x, 0f, texture.width),
            Mathf.Clamp(hotspot.y, 0f, texture.height));
    }
}
