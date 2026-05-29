using UnityEngine;
using UnityEngine.Events;
using UnityEngine.InputSystem;

/// <summary>
/// Input System listener for the player dashboard. Keep input here so the
/// dashboard can also be opened by buttons, quest events, or other game systems.
/// </summary>
public sealed class PlayerDashboardToggleListener : MonoBehaviour
{
    [SerializeField] PlayerDashboardUI dashboard;
    [SerializeField] InputActionReference toggleAction;
    [SerializeField] string fallbackToggleBinding = "<Keyboard>/q";
    [SerializeField] bool pauseGameWhileOpen;

    public UnityEvent toggledOpen;
    public UnityEvent toggledClosed;

    float _previousTimeScale = 1f;
    InputAction _runtimeToggleAction;
    InputAction _activeToggleAction;
    bool _enabledActionHere;

    void Awake()
    {
        if (dashboard == null)
            dashboard = GetComponent<PlayerDashboardUI>() ?? FindFirstObjectByType<PlayerDashboardUI>();

        if (dashboard != null)
        {
            dashboard.opened.AddListener(OnDashboardOpened);
            dashboard.closed.AddListener(OnDashboardClosed);
        }
    }

    void OnEnable()
    {
        BindToggleAction();
    }

    void OnDisable()
    {
        UnbindToggleAction();
    }

    void OnDestroy()
    {
        if (dashboard != null)
        {
            dashboard.opened.RemoveListener(OnDashboardOpened);
            dashboard.closed.RemoveListener(OnDashboardClosed);
        }

        DisposeRuntimeAction();
    }

    public void Open()
    {
        if (dashboard != null)
            dashboard.SetVisible(true);
    }

    public void Close()
    {
        if (dashboard != null)
            dashboard.SetVisible(false);
    }

    void OnDashboardOpened()
    {
        if (pauseGameWhileOpen)
        {
            _previousTimeScale = Time.timeScale;
            Time.timeScale = 0f;
        }

        toggledOpen?.Invoke();
    }

    void OnDashboardClosed()
    {
        if (pauseGameWhileOpen)
            Time.timeScale = _previousTimeScale;

        toggledClosed?.Invoke();
    }

    void BindToggleAction()
    {
        UnbindToggleAction();

        _activeToggleAction = toggleAction != null ? toggleAction.action : null;
        if (_activeToggleAction == null && !string.IsNullOrWhiteSpace(fallbackToggleBinding))
        {
            _runtimeToggleAction = new InputAction("Toggle Player Dashboard", InputActionType.Button, fallbackToggleBinding);
            _activeToggleAction = _runtimeToggleAction;
        }

        if (_activeToggleAction == null)
            return;

        _activeToggleAction.performed += OnTogglePerformed;
        if (!_activeToggleAction.enabled)
        {
            _activeToggleAction.Enable();
            _enabledActionHere = true;
        }
    }

    void UnbindToggleAction()
    {
        if (_activeToggleAction != null)
        {
            _activeToggleAction.performed -= OnTogglePerformed;
            if (_enabledActionHere)
                _activeToggleAction.Disable();
        }

        _activeToggleAction = null;
        _enabledActionHere = false;
        DisposeRuntimeAction();
    }

    void DisposeRuntimeAction()
    {
        if (_runtimeToggleAction == null)
            return;

        _runtimeToggleAction.Dispose();
        _runtimeToggleAction = null;
    }

    void OnTogglePerformed(InputAction.CallbackContext context)
    {
        if (dashboard == null || !isActiveAndEnabled)
            return;

        dashboard.Toggle();
    }
}
