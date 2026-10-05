using UnityEngine;
using MalbersAnimations;
#if ENABLE_INPUT_SYSTEM
using UnityEngine.InputSystem;
#endif

public enum PlayerCatCameraMode
{
    PlayerCamera = 0,
    CatSwitcherObserve = 1,
}

[DisallowMultipleComponent]
public sealed class PlayerCatCameraModeController : MonoBehaviour
{
    [Header("Mode")]
    [SerializeField] PlayerCatCameraMode mode = PlayerCatCameraMode.PlayerCamera;
    [SerializeField] bool handleKeyboardInput = true;
    [SerializeField] KeyCode toggleModeKey = KeyCode.H;
    [SerializeField] KeyCode observeNextCatKey = KeyCode.Tab;
    [SerializeField] KeyCode cancelOrReturnKey = KeyCode.Escape;
    [SerializeField] KeyCode cycleViewKey = KeyCode.V;

#if ENABLE_INPUT_SYSTEM
    [Header("Input System Actions (optional)")]
    [SerializeField] InputActionReference toggleModeAction;
    [SerializeField] InputActionReference observeNextCatAction;
    [SerializeField] InputActionReference cancelOrReturnAction;
    [SerializeField] InputActionReference cycleViewAction;
#endif

    [Header("Player")]
    [SerializeField] Transform playerCatRoot;
    [SerializeField] MInput playerMInput;
    [Tooltip("Off by default because Malbers owns player input. Enable only if this controller should freeze/unfreeze the player cat in observe mode.")]
    [SerializeField] bool managePlayerMInput;

    [Header("Scene Systems")]
    [SerializeField] MultiCatCameraManager cameraManager;
    [SerializeField] KeyboardProximityCatTargetSource targetSource;
    [SerializeField] PlayerCatTargetFeedbackHud targetFeedbackHud;

    public PlayerCatCameraMode Mode => mode;
    public bool IsPlayerCameraMode => mode == PlayerCatCameraMode.PlayerCamera;
    public bool IsObserveMode => mode == PlayerCatCameraMode.CatSwitcherObserve;

    void Awake()
    {
        ResolveReferences();
        ApplyMode(mode);
    }

#if ENABLE_INPUT_SYSTEM
    void OnEnable()
    {
        Bind(toggleModeAction, OnToggleMode);
        Bind(observeNextCatAction, OnObserveNextCat);
        Bind(cancelOrReturnAction, OnCancelOrReturn);
        Bind(cycleViewAction, OnCycleView);
    }

    void OnDisable()
    {
        Unbind(toggleModeAction, OnToggleMode);
        Unbind(observeNextCatAction, OnObserveNextCat);
        Unbind(cancelOrReturnAction, OnCancelOrReturn);
        Unbind(cycleViewAction, OnCycleView);
    }
#endif

    void Update()
    {
#if ENABLE_LEGACY_INPUT_MANAGER
        if (!handleKeyboardInput)
            return;

        if (Input.GetKeyDown(toggleModeKey))
        {
            ToggleCameraMode();
            return;
        }

        if (mode == PlayerCatCameraMode.CatSwitcherObserve)
        {
            if (Input.GetKeyDown(observeNextCatKey))
                cameraManager?.FrameNextCat();
            if (Input.GetKeyDown(cycleViewKey))
                cameraManager?.CycleView();
            if (Input.GetKeyDown(cancelOrReturnKey))
                EnterPlayerCameraMode();
        }
#endif
    }

    public void ToggleCameraMode()
    {
        if (mode == PlayerCatCameraMode.PlayerCamera)
            EnterCatSwitcherObserveMode();
        else
            EnterPlayerCameraMode();
    }

    public void EnterPlayerCameraMode()
    {
        ApplyMode(PlayerCatCameraMode.PlayerCamera);
    }

    public void EnterCatSwitcherObserveMode()
    {
        ApplyMode(PlayerCatCameraMode.CatSwitcherObserve);
    }

    public void SetKeyboardInputEnabled(bool enabled)
    {
        handleKeyboardInput = enabled;
    }

    void ApplyMode(PlayerCatCameraMode nextMode)
    {
        ResolveReferences();
        mode = nextMode;

        bool playerEnabled = mode == PlayerCatCameraMode.PlayerCamera;
        if (managePlayerMInput && playerMInput != null)
            playerMInput.enabled = playerEnabled;

        if (cameraManager != null)
        {
            cameraManager.SetKeyboardInputEnabled(mode == PlayerCatCameraMode.CatSwitcherObserve);
            if (playerCatRoot != null)
                cameraManager.SetActivePlayerCat(playerCatRoot);
            cameraManager.SetPlayerControlEnabled(playerEnabled);
        }

        if (!playerEnabled)
            targetSource?.Clear();

        if (targetFeedbackHud != null)
            targetFeedbackHud.ShowSocialMarkers = playerEnabled;
    }

    void ResolveReferences()
    {
        if (playerCatRoot == null)
            playerCatRoot = transform;
        if (playerMInput == null && playerCatRoot != null)
            playerMInput = playerCatRoot.GetComponent<MInput>()
                ?? playerCatRoot.GetComponentInChildren<MInput>()
                ?? playerCatRoot.GetComponentInParent<MInput>();
        if (cameraManager == null)
            cameraManager = FindFirstObjectByType<MultiCatCameraManager>();
        if (targetSource == null)
            targetSource = GetComponent<KeyboardProximityCatTargetSource>()
                ?? GetComponentInChildren<KeyboardProximityCatTargetSource>()
                ?? GetComponentInParent<KeyboardProximityCatTargetSource>();
        if (targetFeedbackHud == null)
            targetFeedbackHud = GetComponent<PlayerCatTargetFeedbackHud>()
                ?? GetComponentInChildren<PlayerCatTargetFeedbackHud>()
                ?? GetComponentInParent<PlayerCatTargetFeedbackHud>();
    }

#if ENABLE_INPUT_SYSTEM
    void OnToggleMode(InputAction.CallbackContext _) => ToggleCameraMode();
    void OnObserveNextCat(InputAction.CallbackContext _)
    {
        if (mode == PlayerCatCameraMode.CatSwitcherObserve)
            cameraManager?.FrameNextCat();
    }

    void OnCancelOrReturn(InputAction.CallbackContext _)
    {
        if (mode == PlayerCatCameraMode.CatSwitcherObserve)
            EnterPlayerCameraMode();
    }

    void OnCycleView(InputAction.CallbackContext _)
    {
        if (mode == PlayerCatCameraMode.CatSwitcherObserve)
            cameraManager?.CycleView();
    }

    static void Bind(InputActionReference reference, System.Action<InputAction.CallbackContext> handler)
    {
        if (reference == null || reference.action == null)
            return;
        reference.action.performed -= handler;
        reference.action.performed += handler;
        reference.action.Enable();
    }

    static void Unbind(InputActionReference reference, System.Action<InputAction.CallbackContext> handler)
    {
        if (reference == null || reference.action == null)
            return;
        reference.action.performed -= handler;
    }
#endif
}
