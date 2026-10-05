using System;
using System.Collections.Generic;
using UnityEngine;
#if ENABLE_INPUT_SYSTEM
using UnityEngine.InputSystem;
using UnityEngine.InputSystem.Controls;
#endif

[Serializable]
public sealed class PlayerCatSocialActionBinding
{
    public bool enabled = true;
    public string label = "";
    public KeyCode key = KeyCode.None;
    public string socialKind = "";
    public string motorAction = "";
    [Tooltip("Off for actions already driven by Malbers input, such as left-click attack. The social event is still emitted.")]
    public bool playBodyAction = true;
    public bool requiresApproach;
}

[DisallowMultipleComponent]
public sealed class PlayerCatSocialInputRouter : MonoBehaviour
{
    [Header("Mode")]
    [SerializeField] PlayerCatCameraModeController modeController;
    [SerializeField] bool handleKeyboardInput = true;

    [Header("Systems")]
    [SerializeField] KeyboardProximityCatTargetSource targetSource;
    [SerializeField] PlayerCatSocialFsm socialFsm;

    [Header("Target Keys")]
    [SerializeField] KeyCode cycleTargetKey = KeyCode.Tab;
    [SerializeField] KeyCode clearTargetKey = KeyCode.Escape;

    [Header("Inspector Action Bindings")]
    [SerializeField] List<PlayerCatSocialActionBinding> actionBindings = BuildDefaultBindings();
    [SerializeField, HideInInspector] int defaultBindingsVersion;

    [Header("Inspector Debug")]
    [SerializeField, Min(0)] int debugBindingIndex;
    const int CurrentDefaultBindingsVersion = 2;

#if ENABLE_INPUT_SYSTEM
    [Header("Input System Actions (optional)")]
    [SerializeField] InputActionReference cycleTargetAction;
    [SerializeField] InputActionReference clearTargetAction;
    [SerializeField] InputActionReference nodYesAction;
    [SerializeField] InputActionReference shakeNoAction;
    [SerializeField] InputActionReference meowAction;
    [SerializeField] InputActionReference sitNearAction;
    [SerializeField] InputActionReference playInviteAction;
#endif

    void Awake()
    {
        ResolveReferences();
    }

#if ENABLE_INPUT_SYSTEM
    void OnEnable()
    {
        Bind(cycleTargetAction, OnCycleTarget);
        Bind(clearTargetAction, OnClearTarget);
        Bind(nodYesAction, OnNodYes);
        Bind(shakeNoAction, OnShakeNo);
        Bind(meowAction, OnMeow);
        Bind(sitNearAction, OnSitNear);
        Bind(playInviteAction, OnPlayInvite);
    }

    void OnDisable()
    {
        Unbind(cycleTargetAction, OnCycleTarget);
        Unbind(clearTargetAction, OnClearTarget);
        Unbind(nodYesAction, OnNodYes);
        Unbind(shakeNoAction, OnShakeNo);
        Unbind(meowAction, OnMeow);
        Unbind(sitNearAction, OnSitNear);
        Unbind(playInviteAction, OnPlayInvite);
    }
#endif

    void Update()
    {
        if (!handleKeyboardInput || !IsPlayerCameraMode())
            return;

        if (WasPressed(cycleTargetKey))
            CycleTarget();
        if (WasPressed(clearTargetKey))
            ClearTarget();

        for (int i = 0; i < actionBindings.Count; i++)
        {
            PlayerCatSocialActionBinding binding = actionBindings[i];
            if (binding == null || !binding.enabled || binding.key == KeyCode.None)
                continue;
            if (WasPressed(binding.key))
                Perform(binding);
        }
    }

    public void CycleTarget()
    {
        ResolveReferences();
        if (targetSource == null)
            return;

        if (!targetSource.TryGetCurrent(out _))
            targetSource.TryAcquireNearest(out _);
        else
            targetSource.TryCycle(1, out _);
    }

    public void ClearTarget()
    {
        targetSource?.Clear();
        socialFsm?.CancelActiveEpisode("user_clear_target");
    }

    public void NodYes() => Perform(PlayerCatSocialGesture.NodYes);
    public void ShakeNo() => Perform(PlayerCatSocialGesture.ShakeNo);
    public void Meow() => Perform(PlayerCatSocialGesture.Meow);
    public void SitNear() => Perform(PlayerCatSocialGesture.SitNear);
    public void PlayInvite() => Perform(PlayerCatSocialGesture.PlayInvite);

    public void Perform(PlayerCatSocialGesture gesture)
    {
        if (!IsPlayerCameraMode())
            return;

        ResolveReferences();
        socialFsm?.TryPerform(gesture);
    }

    public void Perform(PlayerCatSocialActionBinding binding)
    {
        if (binding == null || !binding.enabled || !IsPlayerCameraMode())
            return;

        ResolveReferences();
        socialFsm?.TryPerformAction(
            binding.socialKind,
            binding.motorAction,
            binding.requiresApproach,
            binding.playBodyAction);
    }

    public void SetKeyboardInputEnabled(bool enabled)
    {
        handleKeyboardInput = enabled;
    }

    [ContextMenu("Player Cat Social/Run Debug Binding")]
    public void RunDebugBinding()
    {
        ResolveReferences();
        if (actionBindings == null || actionBindings.Count == 0)
            return;

        int index = Mathf.Clamp(debugBindingIndex, 0, actionBindings.Count - 1);
        Perform(actionBindings[index]);
    }

    [ContextMenu("Player Cat Social/Cycle Target")]
    public void CycleTargetFromInspector()
    {
        CycleTarget();
    }

    [ContextMenu("Player Cat Social/Clear Target")]
    public void ClearTargetFromInspector()
    {
        ClearTarget();
    }

    bool IsPlayerCameraMode()
    {
        return modeController == null || modeController.IsPlayerCameraMode;
    }

    void ResolveReferences()
    {
        EnsureDefaultBindings();
        if (modeController == null)
            modeController = GetComponent<PlayerCatCameraModeController>()
                ?? GetComponentInParent<PlayerCatCameraModeController>()
                ?? GetComponentInChildren<PlayerCatCameraModeController>();
        if (targetSource == null)
            targetSource = GetComponent<KeyboardProximityCatTargetSource>()
                ?? GetComponentInParent<KeyboardProximityCatTargetSource>()
                ?? GetComponentInChildren<KeyboardProximityCatTargetSource>();
        if (socialFsm == null)
            socialFsm = GetComponent<PlayerCatSocialFsm>()
                ?? GetComponentInParent<PlayerCatSocialFsm>()
                ?? GetComponentInChildren<PlayerCatSocialFsm>();
    }

    void OnValidate()
    {
        EnsureDefaultBindings();
    }

    void EnsureDefaultBindings()
    {
        if (actionBindings == null)
            actionBindings = new List<PlayerCatSocialActionBinding>();
        if (actionBindings.Count <= 0)
        {
            actionBindings = BuildDefaultBindings();
            defaultBindingsVersion = CurrentDefaultBindingsVersion;
            return;
        }
        if (defaultBindingsVersion >= CurrentDefaultBindingsVersion)
            return;

        ApplyDefaultBindingMigrations(actionBindings);

        List<PlayerCatSocialActionBinding> defaults = BuildDefaultBindings();
        for (int i = 0; i < defaults.Count; i++)
        {
            PlayerCatSocialActionBinding candidate = defaults[i];
            if (!ContainsSocialKind(actionBindings, candidate.socialKind))
                actionBindings.Add(candidate);
        }
        defaultBindingsVersion = CurrentDefaultBindingsVersion;
    }

    static void ApplyDefaultBindingMigrations(List<PlayerCatSocialActionBinding> bindings)
    {
        for (int i = 0; i < bindings.Count; i++)
        {
            PlayerCatSocialActionBinding binding = bindings[i];
            if (binding == null)
                continue;

            string kind = Normalize(binding.socialKind);
            if (kind != "player_attack")
                binding.playBodyAction = true;

            switch (kind)
            {
                case "player_play_invite":
                    binding.label = "Play invite";
                    binding.key = KeyCode.Q;
                    binding.motorAction = string.IsNullOrWhiteSpace(binding.motorAction)
                        ? "scratch"
                        : binding.motorAction;
                    binding.playBodyAction = true;
                    binding.requiresApproach = true;
                    break;
                case "player_nod_yes":
                    binding.label = string.IsNullOrWhiteSpace(binding.label) || binding.label == "Nod yes"
                        ? "Yes / nod"
                        : binding.label;
                    binding.playBodyAction = true;
                    break;
                case "player_shake_no":
                    binding.label = string.IsNullOrWhiteSpace(binding.label) || binding.label == "Shake no"
                        ? "No / shake head"
                        : binding.label;
                    binding.playBodyAction = true;
                    break;
                case "player_attack":
                    binding.label = string.IsNullOrWhiteSpace(binding.label)
                        ? "Attack"
                        : binding.label;
                    binding.key = KeyCode.Mouse0;
                    binding.motorAction = "";
                    binding.playBodyAction = false;
                    binding.requiresApproach = false;
                    break;
            }
        }
    }

    static List<PlayerCatSocialActionBinding> BuildDefaultBindings()
    {
        return new List<PlayerCatSocialActionBinding>
        {
            Binding("Play invite", KeyCode.Q, "player_play_invite", "scratch", true),
            Binding("Attack", KeyCode.Mouse0, "player_attack", "", false, false),
            Binding("Meow", KeyCode.M, "player_meow", "vocalize", false),
            Binding("Yes / nod", KeyCode.N, "player_nod_yes", "nod_head", false),
            Binding("No / shake head", KeyCode.X, "player_shake_no", "no", false),
            Binding("Sit near", KeyCode.J, "player_sit_near", "sit", true),
            Binding("Groom", KeyCode.G, "player_groom", "groom", false),
            Binding("Poop", KeyCode.P, "player_poop", "poop", false),
            Binding("Pee", KeyCode.O, "player_pee", "pee", false),
            Binding("Scratch", KeyCode.K, "player_scratch", "scratch", false),
            Binding("Lie", KeyCode.L, "player_lie", "lie", false),
            Binding("Sleep", KeyCode.None, "player_sleep", "sleep", false),
            Binding("Smell target", KeyCode.R, "player_smell", "smell", true),
            Binding("Look around", KeyCode.I, "player_look_around", "look_around", false),
            Binding("Alert watch", KeyCode.None, "player_alert", "alert", false),
            Binding("Push", KeyCode.U, "player_push", "push", true),
            Binding("Shake body", KeyCode.Y, "player_shake", "shake", false),
            Binding("Dig", KeyCode.None, "player_dig", "dig", false),
            Binding("Crawl", KeyCode.None, "player_crawl", "crawl", false),
            Binding("Drink", KeyCode.None, "player_drink", "drink", false),
            Binding("Flinch", KeyCode.None, "player_flinch", "flinch", false),
            Binding("Startle", KeyCode.None, "player_startle", "startle", false),
            Binding("Stun", KeyCode.None, "player_stun", "stun", false),
            Binding("Open chest", KeyCode.None, "player_open_chest", "open_chest", true),
            Binding("Eat target", KeyCode.None, "player_eat", "eat", true),
        };
    }

    static PlayerCatSocialActionBinding Binding(
        string label,
        KeyCode key,
        string socialKind,
        string motorAction,
        bool requiresApproach,
        bool playBodyAction = true)
    {
        return new PlayerCatSocialActionBinding
        {
            enabled = true,
            label = label,
            key = key,
            socialKind = socialKind,
            motorAction = motorAction,
            playBodyAction = playBodyAction,
            requiresApproach = requiresApproach,
        };
    }

    static bool ContainsSocialKind(List<PlayerCatSocialActionBinding> bindings, string socialKind)
    {
        string normalized = Normalize(socialKind);
        for (int i = 0; i < bindings.Count; i++)
        {
            PlayerCatSocialActionBinding binding = bindings[i];
            if (binding != null && Normalize(binding.socialKind) == normalized)
                return true;
        }

        return false;
    }

    static string Normalize(string value)
        => string.IsNullOrWhiteSpace(value)
            ? ""
            : value.Trim().ToLowerInvariant().Replace('-', '_').Replace(' ', '_');

    static bool WasPressed(KeyCode key)
    {
        if (key == KeyCode.None)
            return false;

#if ENABLE_INPUT_SYSTEM
        if (WasMousePressed(key))
            return true;

        Keyboard keyboard = Keyboard.current;
        if (keyboard != null && TryConvertToInputSystemKey(key, out Key inputKey))
        {
            KeyControl control = keyboard[inputKey];
            if (control != null && control.wasPressedThisFrame)
                return true;
        }
#endif

#if ENABLE_LEGACY_INPUT_MANAGER
        if (Input.GetKeyDown(key))
            return true;
#endif

        return false;
    }

#if ENABLE_INPUT_SYSTEM
    static bool WasMousePressed(KeyCode key)
    {
        Mouse mouse = Mouse.current;
        if (mouse == null)
            return false;

        switch (key)
        {
            case KeyCode.Mouse0:
                return mouse.leftButton.wasPressedThisFrame;
            case KeyCode.Mouse1:
                return mouse.rightButton.wasPressedThisFrame;
            case KeyCode.Mouse2:
                return mouse.middleButton.wasPressedThisFrame;
            default:
                return false;
        }
    }

    static bool TryConvertToInputSystemKey(KeyCode keyCode, out Key inputKey)
    {
        switch (keyCode)
        {
            case KeyCode.None:
                inputKey = Key.None;
                return false;
            case KeyCode.Escape:
                inputKey = Key.Escape;
                return true;
            case KeyCode.Tab:
                inputKey = Key.Tab;
                return true;
            case KeyCode.Space:
                inputKey = Key.Space;
                return true;
            case KeyCode.Return:
                inputKey = Key.Enter;
                return true;
            case KeyCode.Backspace:
                inputKey = Key.Backspace;
                return true;
            case KeyCode.LeftShift:
                inputKey = Key.LeftShift;
                return true;
            case KeyCode.RightShift:
                inputKey = Key.RightShift;
                return true;
            case KeyCode.LeftControl:
                inputKey = Key.LeftCtrl;
                return true;
            case KeyCode.RightControl:
                inputKey = Key.RightCtrl;
                return true;
            case KeyCode.LeftAlt:
                inputKey = Key.LeftAlt;
                return true;
            case KeyCode.RightAlt:
                inputKey = Key.RightAlt;
                return true;
            case KeyCode.Alpha0:
                inputKey = Key.Digit0;
                return true;
            case KeyCode.Alpha1:
                inputKey = Key.Digit1;
                return true;
            case KeyCode.Alpha2:
                inputKey = Key.Digit2;
                return true;
            case KeyCode.Alpha3:
                inputKey = Key.Digit3;
                return true;
            case KeyCode.Alpha4:
                inputKey = Key.Digit4;
                return true;
            case KeyCode.Alpha5:
                inputKey = Key.Digit5;
                return true;
            case KeyCode.Alpha6:
                inputKey = Key.Digit6;
                return true;
            case KeyCode.Alpha7:
                inputKey = Key.Digit7;
                return true;
            case KeyCode.Alpha8:
                inputKey = Key.Digit8;
                return true;
            case KeyCode.Alpha9:
                inputKey = Key.Digit9;
                return true;
            default:
                return Enum.TryParse(keyCode.ToString(), true, out inputKey) && inputKey != Key.None;
        }
    }
#endif

#if ENABLE_INPUT_SYSTEM
    void OnCycleTarget(InputAction.CallbackContext _) => CycleTarget();
    void OnClearTarget(InputAction.CallbackContext _) => ClearTarget();
    void OnNodYes(InputAction.CallbackContext _) => NodYes();
    void OnShakeNo(InputAction.CallbackContext _) => ShakeNo();
    void OnMeow(InputAction.CallbackContext _) => Meow();
    void OnSitNear(InputAction.CallbackContext _) => SitNear();
    void OnPlayInvite(InputAction.CallbackContext _) => PlayInvite();

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
