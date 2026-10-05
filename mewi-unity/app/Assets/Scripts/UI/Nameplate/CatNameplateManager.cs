using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;

/// <summary>
/// Scene-level controller for cat nameplates and chat bubbles.
///
/// Drop one of these in the scene. It finds every <see cref="CreatureBlackboard"/>,
/// makes sure each cat has a <see cref="CatNameplateUI"/>, and keeps their name-tag
/// and bubble visibility in sync with the two global toggles.
///
/// It can also draw two clickable on-screen toggle buttons (Names / Bubbles).
/// Prefer wiring your own buttons to <see cref="ToggleNameTags"/> /
/// <see cref="ToggleBubbles"/> if you have a custom HUD.
/// </summary>
[DisallowMultipleComponent]
public sealed class CatNameplateManager : MonoBehaviour
{
    [Header("Global toggles")]
    [SerializeField] bool nameTagsEnabled = true;
    [SerializeField] bool bubblesEnabled = true;

    [Header("Discovery")]
    [Tooltip("Auto-attach a CatNameplateUI to every creature that lacks one.")]
    [SerializeField] bool autoAttachToCats = true;
    [Tooltip("Skip the player cat (creature id 'player'). Set false to label the player too.")]
    [SerializeField] bool skipPlayerCat = true;
    [Tooltip("Seconds between rescans so newly spawned cats get a nameplate. 0 = only on Start.")]
    [SerializeField, Min(0f)] float rescanSeconds = 3f;

    [Header("On-screen toggle buttons")]
    [Tooltip("Debug-only on-screen 'Names: ON / Bubbles: ON' buttons. Off by default so they never show in the game scene; wire your own HUD to ToggleNameTags/ToggleBubbles instead.")]
    [SerializeField] bool buildOnScreenButtons = false;
    [SerializeField] Vector2 buttonAnchor = new Vector2(16f, 16f);

    readonly List<CatNameplateUI> _plates = new List<CatNameplateUI>();
    float _nextRescan;

    Text _nameButtonLabel;
    Text _bubbleButtonLabel;

    public bool NameTagsEnabled => nameTagsEnabled;
    public bool BubblesEnabled => bubblesEnabled;

    void Start()
    {
        Rescan();
        if (buildOnScreenButtons)
            BuildButtons();
        ApplyToAll();
    }

    void Update()
    {
        if (rescanSeconds > 0f && Time.unscaledTime >= _nextRescan)
        {
            _nextRescan = Time.unscaledTime + rescanSeconds;
            Rescan();
        }
    }

    // -------------------------------------------------------------------------
    // Public toggle API (wire UI buttons / hotkeys to these)
    // -------------------------------------------------------------------------

    public void ToggleNameTags() => SetNameTags(!nameTagsEnabled);
    public void ToggleBubbles() => SetBubbles(!bubblesEnabled);

    public void SetNameTags(bool on)
    {
        nameTagsEnabled = on;
        ApplyToAll();
        UpdateButtonLabels();
    }

    public void SetBubbles(bool on)
    {
        bubblesEnabled = on;
        ApplyToAll();
        UpdateButtonLabels();
    }

    // -------------------------------------------------------------------------
    // Discovery + sync
    // -------------------------------------------------------------------------

    public void Rescan()
    {
        _plates.Clear();
        CreatureBlackboard[] boards = FindObjectsByType<CreatureBlackboard>(
            FindObjectsInactive.Exclude, FindObjectsSortMode.None);

        for (int i = 0; i < boards.Length; i++)
        {
            CreatureBlackboard board = boards[i];
            if (board == null)
                continue;
            if (skipPlayerCat && IsPlayer(board))
                continue;

            CatNameplateUI plate = board.GetComponent<CatNameplateUI>()
                ?? board.GetComponentInChildren<CatNameplateUI>();
            if (plate == null && autoAttachToCats)
                plate = board.gameObject.AddComponent<CatNameplateUI>();
            if (plate != null && !_plates.Contains(plate))
                _plates.Add(plate);
        }

        ApplyToAll();
    }

    void ApplyToAll()
    {
        for (int i = _plates.Count - 1; i >= 0; i--)
        {
            CatNameplateUI plate = _plates[i];
            if (plate == null)
            {
                _plates.RemoveAt(i);
                continue;
            }
            plate.ShowNameTag = nameTagsEnabled;
            plate.ShowBubble = bubblesEnabled;
        }
    }

    static bool IsPlayer(CreatureBlackboard board)
    {
        string id = board.CreatureId;
        return !string.IsNullOrEmpty(id) &&
               id.IndexOf("player", System.StringComparison.OrdinalIgnoreCase) >= 0;
    }

    // -------------------------------------------------------------------------
    // Built-in on-screen toggle buttons
    // -------------------------------------------------------------------------

    void BuildButtons()
    {
        Font font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf")
            ?? Resources.GetBuiltinResource<Font>("Arial.ttf");

        var canvasGO = new GameObject("CatNameplateToggleCanvas");
        canvasGO.transform.SetParent(transform, worldPositionStays: false);
        var canvas = canvasGO.AddComponent<Canvas>();
        canvas.renderMode = RenderMode.ScreenSpaceOverlay;
        canvas.sortingOrder = 500;
        canvasGO.AddComponent<CanvasScaler>().uiScaleMode =
            CanvasScaler.ScaleMode.ConstantPixelSize;
        canvasGO.AddComponent<GraphicRaycaster>();

        _nameButtonLabel = BuildButton(canvas.transform, font,
            new Vector2(buttonAnchor.x, buttonAnchor.y + 44f), ToggleNameTags);
        _bubbleButtonLabel = BuildButton(canvas.transform, font,
            buttonAnchor, ToggleBubbles);

        UpdateButtonLabels();
    }

    Text BuildButton(Transform parent, Font font, Vector2 anchoredPos,
        UnityEngine.Events.UnityAction onClick)
    {
        var go = new GameObject("ToggleButton");
        var rect = go.AddComponent<RectTransform>();
        go.transform.SetParent(parent, worldPositionStays: false);
        rect.anchorMin = Vector2.zero;
        rect.anchorMax = Vector2.zero;
        rect.pivot = Vector2.zero;
        rect.anchoredPosition = anchoredPos;
        rect.sizeDelta = new Vector2(170f, 38f);

        var image = go.AddComponent<Image>();
        image.color = new Color(0f, 0f, 0f, 0.6f);

        var button = go.AddComponent<Button>();
        button.onClick.AddListener(onClick);

        var textGO = new GameObject("Label");
        var textRect = textGO.AddComponent<RectTransform>();
        textGO.transform.SetParent(rect, worldPositionStays: false);
        textRect.anchorMin = Vector2.zero;
        textRect.anchorMax = Vector2.one;
        textRect.offsetMin = Vector2.zero;
        textRect.offsetMax = Vector2.zero;

        var text = textGO.AddComponent<Text>();
        text.font = font;
        text.fontSize = 18;
        text.color = Color.white;
        text.alignment = TextAnchor.MiddleCenter;
        text.raycastTarget = false;

        return text;
    }

    void UpdateButtonLabels()
    {
        if (_nameButtonLabel != null)
            _nameButtonLabel.text = nameTagsEnabled ? "Names: ON" : "Names: OFF";
        if (_bubbleButtonLabel != null)
            _bubbleButtonLabel.text = bubblesEnabled ? "Bubbles: ON" : "Bubbles: OFF";
    }
}
