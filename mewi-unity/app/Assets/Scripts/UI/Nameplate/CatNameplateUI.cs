using UnityEngine;
using UnityEngine.UI;

/// <summary>
/// Per-cat world-space nameplate and speech bubble.
///
/// Builds its own billboarded world-space canvas in code (no prefab required),
/// shows the cat's name above its head, and pops a chat bubble whenever the
/// creature speaks a social line (see <see cref="CreatureBlackboard.SocialLineSpoken"/>).
///
/// Visibility of the name tag and the bubble is gated by <see cref="ShowNameTag"/>
/// and <see cref="ShowBubble"/>, which CatNameplateManager drives from its
/// global toggles.
/// </summary>
[DisallowMultipleComponent]
public sealed class CatNameplateUI : MonoBehaviour
{
    [Header("Identity")]
    [Tooltip("Leave empty to use the creature id from the blackboard.")]
    [SerializeField] string displayNameOverride = "";

    [Header("Placement")]
    [SerializeField, Min(0f)] float headHeight = 1.4f;
    [Tooltip("Extra gap from the name tag up to the bubble, in canvas pixels.")]
    [SerializeField, Min(0f)] float bubbleGap = 64f;
    [Tooltip("World size of one canvas pixel. Smaller = smaller UI.")]
    [SerializeField, Min(0.0005f)] float uiScale = 0.01f;
    [SerializeField] bool billboardToCamera = true;

    [Header("Name Tag")]
    [SerializeField] bool showNameTag = true;
    [SerializeField] int nameFontSize = 14;
    [SerializeField] Color nameColor = Color.white;
    [SerializeField] Color nameBackgroundColor = new Color(0f, 0f, 0f, 0.55f);

    [Header("Bubble")]
    [SerializeField] bool showBubble = true;
    [SerializeField, Min(0.5f)] float bubbleSeconds = 3.5f;
    [SerializeField] int bubbleFontSize = 30;
    [SerializeField] Color bubbleTextColor = new Color(0.1f, 0.1f, 0.1f, 1f);
    [SerializeField] Color bubbleBackgroundColor = new Color(1f, 1f, 1f, 0.95f);
    [SerializeField, Min(40f)] float bubbleWidth = 360f;

    CreatureBlackboard _board;
    Canvas _canvas;
    RectTransform _root;

    GameObject _nameTagGO;
    Text _nameText;

    GameObject _bubbleGO;
    Text _bubbleText;
    float _bubbleHideAt = -1f;

    Camera _camera;

    public bool ShowNameTag
    {
        get => showNameTag;
        set
        {
            showNameTag = value;
            ApplyVisibility();
        }
    }

    public bool ShowBubble
    {
        get => showBubble;
        set
        {
            showBubble = value;
            ApplyVisibility();
        }
    }

    void Awake()
    {
        _board = GetComponent<CreatureBlackboard>()
            ?? GetComponentInParent<CreatureBlackboard>()
            ?? GetComponentInChildren<CreatureBlackboard>();
        BuildUi();
        RefreshName();
    }

    void OnEnable()
    {
        if (_board != null)
            _board.SocialLineSpoken += OnSocialLineSpoken;
    }

    void OnDisable()
    {
        if (_board != null)
            _board.SocialLineSpoken -= OnSocialLineSpoken;
    }

    void LateUpdate()
    {
        if (_root == null)
            return;

        if (_bubbleGO != null && _bubbleGO.activeSelf && Time.time >= _bubbleHideAt)
            HideBubble();

        // Keep the canvas pinned above the head and facing the camera.
        _root.position = transform.position + Vector3.up * headHeight;
        FaceCamera();
    }

    /// <summary>Set the bubble text directly (e.g. from a gameplay script).</summary>
    public void Say(string line)
    {
        OnSocialLineSpoken(line, "");
    }

    /// <summary>Re-read the display name from the override or the blackboard.</summary>
    public void RefreshName()
    {
        if (_nameText != null)
            _nameText.text = ResolveDisplayName();
    }

    void OnSocialLineSpoken(string say, string tone)
    {
        if (_bubbleGO == null || _bubbleText == null || string.IsNullOrWhiteSpace(say))
            return;

        _bubbleText.text = say.Trim();
        _bubbleHideAt = Time.time + bubbleSeconds;
        ApplyVisibility();
    }

    void HideBubble()
    {
        _bubbleHideAt = -1f;
        if (_bubbleGO != null)
            _bubbleGO.SetActive(false);
    }

    bool BubbleActive => _bubbleHideAt > 0f && Time.time < _bubbleHideAt;

    void ApplyVisibility()
    {
        if (_nameTagGO != null)
            _nameTagGO.SetActive(showNameTag);
        if (_bubbleGO != null)
            _bubbleGO.SetActive(showBubble && BubbleActive);
    }

    string ResolveDisplayName()
    {
        if (!string.IsNullOrWhiteSpace(displayNameOverride))
            return displayNameOverride.Trim();

        string id = _board != null ? _board.CreatureId : transform.root.name;
        return Prettify(id);
    }

    static string Prettify(string id)
    {
        if (string.IsNullOrWhiteSpace(id))
            return "Cat";

        string trimmed = id.Trim().Replace('_', ' ').Replace('-', ' ');
        if (trimmed.Length == 0)
            return "Cat";
        return char.ToUpperInvariant(trimmed[0]) + trimmed.Substring(1);
    }

    // -------------------------------------------------------------------------
    // UI construction (all built in code so no prefab wiring is needed)
    // -------------------------------------------------------------------------

    void BuildUi()
    {
        var rootGO = new GameObject("CatNameplateCanvas");
        _root = rootGO.AddComponent<RectTransform>();
        rootGO.transform.SetParent(transform, worldPositionStays: false);
        rootGO.transform.localPosition = Vector3.up * headHeight;
        rootGO.transform.localScale = Vector3.one * uiScale;

        _canvas = rootGO.AddComponent<Canvas>();
        _canvas.renderMode = RenderMode.WorldSpace;
        _canvas.sortingOrder = 100;
        _root.sizeDelta = new Vector2(bubbleWidth, 200f);

        Font font = ResolveFont();

        // Name tag (sits just above the head; box hugs the text).
        _nameTagGO = BuildLabel("NameTag", font, nameFontSize, nameColor, nameBackgroundColor,
            new Vector2(0f, 0f), wrap: false, fixedWidth: 0f, out _nameText);

        // Speech bubble (sits above the name tag; fixed width, text wraps).
        _bubbleGO = BuildLabel("Bubble", font, bubbleFontSize, bubbleTextColor, bubbleBackgroundColor,
            new Vector2(0f, bubbleGap), wrap: true, fixedWidth: bubbleWidth, out _bubbleText);

        ApplyVisibility();
    }

    GameObject BuildLabel(
        string labelName,
        Font font,
        int fontSize,
        Color textColor,
        Color backgroundColor,
        Vector2 anchoredPos,
        bool wrap,
        float fixedWidth,
        out Text text)
    {
        // Background panel: a layout group + size fitter make the box hug its text.
        var go = new GameObject(labelName);
        var rect = go.AddComponent<RectTransform>();
        go.transform.SetParent(_root, worldPositionStays: false);
        rect.anchorMin = new Vector2(0.5f, 0f);
        rect.anchorMax = new Vector2(0.5f, 0f);
        rect.pivot = new Vector2(0.5f, 0f);
        rect.anchoredPosition = anchoredPos;

        var background = go.AddComponent<Image>();
        background.color = backgroundColor;
        Sprite bg = ResolveBackgroundSprite();
        if (bg != null)
        {
            background.sprite = bg;
            background.type = Image.Type.Sliced;
        }

        var layout = go.AddComponent<VerticalLayoutGroup>();
        layout.padding = new RectOffset(16, 16, 8, 8);
        layout.childAlignment = TextAnchor.MiddleCenter;
        layout.childControlWidth = true;
        layout.childControlHeight = true;
        layout.childForceExpandWidth = wrap;   // wrapped bubble fills the fixed width
        layout.childForceExpandHeight = false;

        var fitter = go.AddComponent<ContentSizeFitter>();
        fitter.horizontalFit = wrap
            ? ContentSizeFitter.FitMode.Unconstrained
            : ContentSizeFitter.FitMode.PreferredSize;
        fitter.verticalFit = ContentSizeFitter.FitMode.PreferredSize;
        if (wrap && fixedWidth > 0f)
            rect.sizeDelta = new Vector2(fixedWidth, rect.sizeDelta.y);

        var textGO = new GameObject("Text");
        textGO.AddComponent<RectTransform>();
        textGO.transform.SetParent(rect, worldPositionStays: false);

        text = textGO.AddComponent<Text>();
        text.font = font;
        text.fontSize = fontSize;
        text.color = textColor;
        text.alignment = TextAnchor.MiddleCenter;
        text.horizontalOverflow = wrap ? HorizontalWrapMode.Wrap : HorizontalWrapMode.Overflow;
        text.verticalOverflow = VerticalWrapMode.Overflow;
        text.raycastTarget = false;

        return go;
    }

    void FaceCamera()
    {
        if (!billboardToCamera || _root == null)
            return;

        if (_camera == null || !_camera.isActiveAndEnabled)
            _camera = Camera.main;
        if (_camera == null)
            return;

        _root.rotation = Quaternion.LookRotation(
            _root.position - _camera.transform.position, Vector3.up);
    }

    static Font _cachedFont;
    static Font ResolveFont()
    {
        if (_cachedFont != null)
            return _cachedFont;
        _cachedFont = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf")
            ?? Resources.GetBuiltinResource<Font>("Arial.ttf");
        return _cachedFont;
    }

    static bool _bgSpriteResolved;
    static Sprite _cachedBgSprite;
    static Sprite ResolveBackgroundSprite()
    {
        if (_bgSpriteResolved)
            return _cachedBgSprite;
        _bgSpriteResolved = true;
        _cachedBgSprite = Resources.GetBuiltinResource<Sprite>("UI/Skin/Background.psd");
        return _cachedBgSprite;
    }
}
