using System;
using System.Collections.Generic;
using TMPro;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.Events;
using UnityEngine.InputSystem.UI;
using UnityEngine.UI;

/// <summary>
/// Runtime-built player dashboard overlay. The shell is intentionally data-led:
/// profile/sidebar on the left, tabbed scroll content on the right.
/// </summary>
public sealed class PlayerDashboardUI : MonoBehaviour
{
    const string RootName = "Generated_PlayerDashboard";

    enum DashboardTab
    {
        CatBonds,
        CompletedTasks,
    }

    [Header("Profile")]
    [SerializeField] string dashboardTitle = "Player Dashboard";
    [SerializeField] string playerName = "Player";
    [SerializeField] string playerSubtitle = "Harbor visitor";
    [SerializeField] Sprite playerProfilePhoto;

    [Header("Content")]
    [SerializeField] bool useSampleDataWhenEmpty = true;
    [SerializeField] List<CatRelationshipDashboardItem> relationships = new List<CatRelationshipDashboardItem>();
    [SerializeField] List<CompletedGameItem> completedItems = new List<CompletedGameItem>();

    [Header("Layout")]
    [SerializeField] Vector2 panelMargin = new Vector2(44f, 34f);
    [SerializeField] float sidebarWidth = 280f;
    [SerializeField] Vector2 profilePhotoSize = new Vector2(174f, 174f);
    [SerializeField] bool visibleOnStart;

    [Header("Events")]
    public UnityEvent opened;
    public UnityEvent closed;
    public DashboardStringEvent catSelected;
    public DashboardStringEvent taskSelected;

    [Header("Style")]
    [SerializeField] Color screenDimColor = new Color(0f, 0f, 0f, 0.38f);
    [SerializeField] Color panelColor = new Color(0.035f, 0.045f, 0.055f, 0.88f);
    [SerializeField] Color sidebarColor = new Color(0.08f, 0.105f, 0.13f, 0.86f);
    [SerializeField] Color widgetColor = new Color(0.10f, 0.13f, 0.16f, 0.84f);
    [SerializeField] Color cardColor = new Color(0.15f, 0.18f, 0.21f, 0.84f);
    [SerializeField] Color activeTabColor = new Color(0.25f, 0.78f, 0.74f, 0.92f);
    [SerializeField] Color inactiveTabColor = new Color(1f, 1f, 1f, 0.08f);
    [SerializeField] Color textColor = new Color(0.94f, 0.96f, 0.98f, 1f);
    [SerializeField] Color mutedTextColor = new Color(0.78f, 0.83f, 0.88f, 1f);
    [SerializeField] Color accentColor = new Color(0.25f, 0.78f, 0.74f, 0.95f);
    [SerializeField] Color warmAccentColor = new Color(1f, 0.72f, 0.32f, 0.95f);
    [SerializeField] Color goodAccentColor = new Color(0.46f, 0.88f, 0.53f, 0.95f);

    CanvasGroup _group;
    RectTransform _root;
    DashboardTab _activeTab = DashboardTab.CatBonds;
    string _selectedCatId = "";

    void Awake()
    {
        if (!Application.isPlaying) return;

        Rebuild();
        SetVisible(visibleOnStart);
    }

    [ContextMenu("Rebuild Dashboard")]
    public void Rebuild()
    {
        EnsureCanvas();
        DestroyGeneratedRoot();

        _root = CreateRect(RootName, transform);
        Stretch(_root);
        _group = _root.gameObject.AddComponent<CanvasGroup>();

        RectTransform dimmer = CreatePanel(_root, "ScreenDimmer", screenDimColor, 0f);
        Stretch(dimmer);
        dimmer.SetAsFirstSibling();

        RectTransform panel = CreatePanel(_root, "DashboardPanel", panelColor, 30f);
        StretchWithMargin(panel, panelMargin);

        HorizontalLayoutGroup shell = panel.gameObject.AddComponent<HorizontalLayoutGroup>();
        shell.padding = new RectOffset(18, 18, 18, 18);
        shell.spacing = 18f;
        shell.childControlWidth = true;
        shell.childControlHeight = true;
        shell.childForceExpandWidth = false;
        shell.childForceExpandHeight = true;

        BuildSidebar(panel);
        BuildContent(panel);
    }

    public void SetVisible(bool visible)
    {
        if (_group == null) return;

        bool wasVisible = _group.alpha > 0.01f;
        _group.alpha = visible ? 1f : 0f;
        _group.blocksRaycasts = visible;
        _group.interactable = visible;

        if (visible && !wasVisible) opened?.Invoke();
        if (!visible && wasVisible) closed?.Invoke();
    }

    public void Toggle()
    {
        SetVisible(_group == null || _group.alpha <= 0.01f);
    }

    public bool IsVisible
    {
        get { return _group != null && _group.alpha > 0.01f; }
    }

    public void ShowCatBonds()
    {
        _activeTab = DashboardTab.CatBonds;
        Rebuild();
    }

    public void ShowCompletedTasks()
    {
        _activeTab = DashboardTab.CompletedTasks;
        Rebuild();
    }

    public void SetRelationships(IEnumerable<CatRelationshipDashboardItem> items)
    {
        relationships.Clear();
        if (items != null)
        {
            foreach (CatRelationshipDashboardItem item in items)
                if (item != null) relationships.Add(item);
        }
        Rebuild();
    }

    public void SetCompletedItems(IEnumerable<CompletedGameItem> items)
    {
        completedItems.Clear();
        if (items != null)
        {
            foreach (CompletedGameItem item in items)
                if (item != null) completedItems.Add(item);
        }
        Rebuild();
    }

    public void SetSelectedCat(string catId)
    {
        _selectedCatId = catId ?? "";
        _activeTab = DashboardTab.CatBonds;
        Rebuild();
    }

    void BuildSidebar(RectTransform parent)
    {
        RectTransform sidebar = CreatePanel(parent, "Sidebar", sidebarColor, 24f);
        SetFixedWidth(sidebar, sidebarWidth);
        AddVerticalLayout(sidebar, 18, 18, 20, 20, 18f);

        TextMeshProUGUI title = CreateText(sidebar, dashboardTitle, 25f, textColor, FontStyles.Bold);
        SetWrappedEllipsis(title, 2);

        RectTransform profile = CreatePanel(sidebar, "ProfileCard", widgetColor, 22f);
        SetFixedHeight(profile, 300f);
        AddVerticalLayout(profile, 18, 18, 18, 18, 12f);

        RectTransform photoRow = CreateRect("PlayerPhotoRow", profile);
        SetFixedHeight(photoRow, profilePhotoSize.y);
        HorizontalLayoutGroup photoLayout = photoRow.gameObject.AddComponent<HorizontalLayoutGroup>();
        photoLayout.childAlignment = TextAnchor.MiddleCenter;
        photoLayout.childControlWidth = false;
        photoLayout.childControlHeight = false;
        photoLayout.childForceExpandWidth = false;
        photoLayout.childForceExpandHeight = false;
        CreatePhotoSlot(photoRow, "PlayerPhoto", playerProfilePhoto, profilePhotoSize, 22f, PlayerInitials());
        photoRow.SetAsFirstSibling();

        TextMeshProUGUI name = CreateText(profile, playerName, 24f, textColor, FontStyles.Bold);
        name.alignment = TextAlignmentOptions.Center;
        SetSingleLineEllipsis(name);

        TextMeshProUGUI subtitle = CreateText(profile, playerSubtitle, 15f, mutedTextColor, FontStyles.Normal);
        subtitle.alignment = TextAlignmentOptions.Center;
        SetWrappedEllipsis(subtitle, 2);

        BuildTabButton(sidebar, "Bondness With Cats", DashboardTab.CatBonds);
        BuildTabButton(sidebar, "Task Completed", DashboardTab.CompletedTasks);

        RectTransform hint = CreatePanel(sidebar, "Hint", new Color(1f, 1f, 1f, 0.06f), 18f);
        hint.gameObject.AddComponent<LayoutElement>().flexibleHeight = 1f;
        AddVerticalLayout(hint, 14, 14, 12, 12, 6f);
        TextMeshProUGUI hintText = CreateText(hint, "Press Q to open or close this dashboard.", 14f, mutedTextColor, FontStyles.Normal);
        SetWrappedEllipsis(hintText, 3);
    }

    void BuildTabButton(RectTransform parent, string label, DashboardTab tab)
    {
        bool active = _activeTab == tab;
        RectTransform buttonRect = CreateButtonPanel(parent, "Tab_" + SafeName(label), active ? activeTabColor : inactiveTabColor, 18f, delegate
        {
            _activeTab = tab;
            Rebuild();
        });
        SetFixedHeight(buttonRect, 54f);
        AddVerticalLayout(buttonRect, 16, 16, 8, 8, 0f);

        TextMeshProUGUI text = CreateText(buttonRect, label, 17f, active ? Color.white : textColor, FontStyles.Bold);
        text.alignment = TextAlignmentOptions.Center;
        SetSingleLineEllipsis(text);
    }

    void BuildContent(RectTransform parent)
    {
        RectTransform contentShell = CreatePanel(parent, "ContentShell", widgetColor, 24f);
        SetFlexibleWidth(contentShell);
        AddVerticalLayout(contentShell, 20, 20, 18, 18, 14f);

        string title = _activeTab == DashboardTab.CatBonds ? "Bondness With Cats" : "Task Completed";
        string subtitle = _activeTab == DashboardTab.CatBonds
            ? "Every row is one companion. Click a cat portrait to inspect that bond."
            : "Completed progress is grouped as clickable rows with a cover card.";

        RectTransform header = CreatePanel(contentShell, "ContentHeader", new Color(1f, 1f, 1f, 0.06f), 18f);
        SetFixedHeight(header, 82f);
        AddVerticalLayout(header, 16, 16, 12, 12, 4f);
        TextMeshProUGUI headerTitle = CreateText(header, title, 27f, textColor, FontStyles.Bold);
        SetSingleLineEllipsis(headerTitle);
        TextMeshProUGUI sub = CreateText(header, subtitle, 15f, mutedTextColor, FontStyles.Normal);
        SetWrappedEllipsis(sub, 2);

        List<CatRelationshipDashboardItem> catData = null;
        if (_activeTab == DashboardTab.CatBonds)
        {
            catData = DisplayRelationships();
            BuildCatDetail(contentShell, SelectedCat(catData));
        }

        RectTransform scrollContent;
        CreateScrollArea(contentShell, out scrollContent);

        if (_activeTab == DashboardTab.CatBonds)
            BuildCatRows(scrollContent, catData);
        else
            BuildCompletedRows(scrollContent);
    }

    void BuildCatRows(RectTransform parent, List<CatRelationshipDashboardItem> data)
    {
        if (data == null)
            data = DisplayRelationships();

        for (int i = 0; i < data.Count; i++)
        {
            if (data[i] == null) continue;
            BuildCatRow(parent, data[i]);
        }
    }

    void BuildCompletedRows(RectTransform parent)
    {
        List<CompletedGameItem> data = DisplayCompletedItems();
        for (int i = 0; i < data.Count; i++)
        {
            if (data[i] == null) continue;
            BuildCompletedRow(parent, data[i]);
        }
    }

    void BuildCatDetail(RectTransform parent, CatRelationshipDashboardItem item)
    {
        RectTransform detail = CreatePanel(parent, "CatDetail", new Color(1f, 1f, 1f, 0.065f), 20f);
        SetFixedHeight(detail, 142f);

        HorizontalLayoutGroup layout = detail.gameObject.AddComponent<HorizontalLayoutGroup>();
        layout.padding = new RectOffset(16, 18, 16, 16);
        layout.spacing = 16f;
        layout.childControlWidth = true;
        layout.childControlHeight = true;
        layout.childForceExpandWidth = false;
        layout.childForceExpandHeight = false;
        layout.childAlignment = TextAnchor.MiddleLeft;

        RectTransform portrait = CreatePhotoSlot(detail, "SelectedCatPortrait", item != null ? item.profilePhoto : null, new Vector2(96f, 96f), 48f, CatInitials(item));
        SetFixedSize(portrait, 96f, 96f);

        RectTransform copy = CreateRect("SelectedCatCopy", detail);
        SetFlexibleWidth(copy);
        AddVerticalLayout(copy, 0, 0, 0, 0, 7f);

        RectTransform topLine = CreateRect("SelectedCatTopLine", copy);
        SetFixedHeight(topLine, 30f);
        HorizontalLayoutGroup topLayout = topLine.gameObject.AddComponent<HorizontalLayoutGroup>();
        topLayout.spacing = 10f;
        topLayout.childControlWidth = true;
        topLayout.childControlHeight = true;
        topLayout.childForceExpandWidth = false;

        TextMeshProUGUI name = CreateText(topLine, item != null ? item.catName : "Select a cat", 23f, textColor, FontStyles.Bold);
        SetFlexibleWidth(name.GetComponent<RectTransform>());
        SetSingleLineEllipsis(name);

        RectTransform badge = CreatePanel(topLine, "SelectedCatBadge", item != null ? TrustColor(item.trust) : inactiveTabColor, 15f);
        SetFixedWidth(badge, 132f);
        AddVerticalLayout(badge, 8, 8, 4, 4, 0f);
        TextMeshProUGUI badgeText = CreateText(badge, item != null ? item.relationshipLabel : "No cat", 13f, Color.white, FontStyles.Bold);
        badgeText.alignment = TextAlignmentOptions.Center;
        SetSingleLineEllipsis(badgeText);

        TextMeshProUGUI description = CreateText(copy, CatDescription(item), 15f, mutedTextColor, FontStyles.Normal);
        SetWrappedEllipsis(description, 2);

        TextMeshProUGUI memory = CreateText(copy, "Memory: " + MemorySummary(item), 13.5f, accentColor, FontStyles.Normal);
        SetSingleLineEllipsis(memory);
    }

    void BuildCatRow(RectTransform parent, CatRelationshipDashboardItem item)
    {
        bool selected = IsSelectedCat(item);
        RectTransform row = CreateButtonPanel(parent, "CatRow_" + SafeName(item.catName), selected ? Brighten(cardColor, 1.18f) : cardColor, 22f, delegate
        {
            SelectCat(item);
        });
        SetFixedHeight(row, 126f);

        HorizontalLayoutGroup layout = row.gameObject.AddComponent<HorizontalLayoutGroup>();
        layout.padding = new RectOffset(16, 18, 14, 14);
        layout.spacing = 16f;
        layout.childControlWidth = true;
        layout.childControlHeight = true;
        layout.childForceExpandWidth = false;
        layout.childForceExpandHeight = false;
        layout.childAlignment = TextAnchor.MiddleLeft;

        RectTransform portrait = CreatePhotoButton(row, "CatPortrait", item.profilePhoto, new Vector2(78f, 78f), 42f, CatInitials(item), delegate
        {
            SelectCat(item);
        });
        SetFixedSize(portrait, 78f, 78f);

        RectTransform copy = CreateRect("CatCopy", row);
        SetFlexibleWidth(copy);
        AddVerticalLayout(copy, 0, 0, 0, 0, 7f);

        RectTransform topLine = CreateRect("TopLine", copy);
        SetFixedHeight(topLine, 30f);
        HorizontalLayoutGroup topLayout = topLine.gameObject.AddComponent<HorizontalLayoutGroup>();
        topLayout.spacing = 10f;
        topLayout.childControlWidth = true;
        topLayout.childControlHeight = true;
        topLayout.childForceExpandWidth = false;

        TextMeshProUGUI name = CreateText(topLine, item.catName, 22f, textColor, FontStyles.Bold);
        SetFlexibleWidth(name.GetComponent<RectTransform>());
        SetSingleLineEllipsis(name);

        RectTransform badge = CreatePanel(topLine, "BondBadge", TrustColor(item.trust), 15f);
        SetFixedWidth(badge, 120f);
        AddVerticalLayout(badge, 8, 8, 4, 4, 0f);
        TextMeshProUGUI badgeText = CreateText(badge, item.relationshipLabel, 13f, Color.white, FontStyles.Bold);
        badgeText.alignment = TextAlignmentOptions.Center;
        SetSingleLineEllipsis(badgeText);

        string memory = MemorySummary(item);
        if (!string.IsNullOrWhiteSpace(item.lastSeenLocation))
            memory += " Last seen: " + item.lastSeenLocation + ".";
        TextMeshProUGUI episode = CreateText(copy, memory, 15f, mutedTextColor, FontStyles.Normal);
        SetWrappedEllipsis(episode, 2);

        RectTransform meters = CreateRect("Meters", copy);
        SetFixedHeight(meters, 30f);
        HorizontalLayoutGroup meterLayout = meters.gameObject.AddComponent<HorizontalLayoutGroup>();
        meterLayout.spacing = 12f;
        meterLayout.childControlHeight = true;
        meterLayout.childControlWidth = true;
        meterLayout.childForceExpandWidth = true;

        BuildCompactProgress(meters, "Trust", item.trust, TrustColor(item.trust));
        BuildCompactProgress(meters, "Bond", item.bond, accentColor);
    }

    void BuildCompletedRow(RectTransform parent, CompletedGameItem item)
    {
        RectTransform row = CreateButtonPanel(parent, "CompletedRow_" + SafeName(item.title), cardColor, 22f, delegate
        {
            taskSelected?.Invoke(item.taskId);
        });
        SetFixedHeight(row, 126f);

        HorizontalLayoutGroup layout = row.gameObject.AddComponent<HorizontalLayoutGroup>();
        layout.padding = new RectOffset(16, 18, 14, 14);
        layout.spacing = 16f;
        layout.childControlWidth = true;
        layout.childControlHeight = true;
        layout.childForceExpandWidth = false;
        layout.childForceExpandHeight = false;
        layout.childAlignment = TextAnchor.MiddleLeft;

        RectTransform cover = CreateCoverButton(row, item.coverImage, new Vector2(148f, 88f), delegate
        {
            taskSelected?.Invoke(item.taskId);
        });
        SetFixedSize(cover, 148f, 88f);

        RectTransform copy = CreateRect("TaskCopy", row);
        SetFlexibleWidth(copy);
        AddVerticalLayout(copy, 0, 0, 2, 2, 6f);

        TextMeshProUGUI title = CreateText(copy, item.title, 22f, textColor, FontStyles.Bold);
        SetSingleLineEllipsis(title);

        TextMeshProUGUI category = CreateText(copy, TaskMeta(item), 15f, goodAccentColor, FontStyles.Bold);
        SetSingleLineEllipsis(category);

        TextMeshProUGUI desc = CreateText(copy, item.description, 15f, mutedTextColor, FontStyles.Normal);
        SetWrappedEllipsis(desc, 2);
    }

    void CreateScrollArea(RectTransform parent, out RectTransform content)
    {
        RectTransform viewport = CreatePanel(parent, "ScrollViewport", new Color(1f, 1f, 1f, 0.04f), 18f);
        viewport.gameObject.AddComponent<RectMask2D>();
        viewport.gameObject.AddComponent<LayoutElement>().flexibleHeight = 1f;

        ScrollRect scroll = viewport.gameObject.AddComponent<ScrollRect>();
        scroll.horizontal = false;
        scroll.vertical = true;
        scroll.movementType = ScrollRect.MovementType.Clamped;
        scroll.scrollSensitivity = 22f;
        scroll.viewport = viewport;

        content = CreateRect("ScrollContent", viewport);
        content.anchorMin = new Vector2(0f, 1f);
        content.anchorMax = new Vector2(1f, 1f);
        content.pivot = new Vector2(0.5f, 1f);
        content.anchoredPosition = Vector2.zero;
        content.sizeDelta = Vector2.zero;
        AddVerticalLayout(content, 12, 12, 12, 12, 12f);

        ContentSizeFitter fitter = content.gameObject.AddComponent<ContentSizeFitter>();
        fitter.verticalFit = ContentSizeFitter.FitMode.PreferredSize;

        scroll.content = content;
    }

    void BuildCompactProgress(RectTransform parent, string label, float value, Color fillColor)
    {
        RectTransform wrap = CreateRect(label + "Progress", parent);
        SetFlexibleWidth(wrap);
        AddVerticalLayout(wrap, 0, 0, 0, 0, 4f);

        TextMeshProUGUI labelText = CreateText(wrap, label + " " + Mathf.RoundToInt(Mathf.Clamp01(value) * 100f) + "%", 13f, mutedTextColor, FontStyles.Normal);
        labelText.alignment = TextAlignmentOptions.Left;
        SetSingleLineEllipsis(labelText);

        RectTransform track = CreatePanel(wrap, "Track", new Color(1f, 1f, 1f, 0.12f), 5f);
        SetFixedHeight(track, 10f);

        RectTransform fill = CreatePanel(track, "Fill", fillColor, 5f);
        fill.anchorMin = Vector2.zero;
        fill.anchorMax = new Vector2(Mathf.Clamp01(value), 1f);
        fill.offsetMin = Vector2.zero;
        fill.offsetMax = Vector2.zero;
    }

    RectTransform CreatePhotoSlot(Transform parent, string name, Sprite sprite, Vector2 size, float radius, string fallbackText)
    {
        RectTransform slot = CreatePanel(parent, name, new Color(1f, 1f, 1f, 0.09f), radius);
        SetFixedSize(slot, size.x, size.y);

        if (sprite != null)
        {
            Mask mask = slot.gameObject.AddComponent<Mask>();
            mask.showMaskGraphic = true;
            AddImage(slot, sprite);
        }
        else
        {
            AddCenteredText(slot, fallbackText, 44f, textColor);
        }

        return slot;
    }

    RectTransform CreatePhotoButton(Transform parent, string name, Sprite sprite, Vector2 size, float radius, string fallbackText, UnityAction onClick)
    {
        RectTransform button = CreateButtonPanel(parent, name, new Color(1f, 1f, 1f, 0.09f), radius, onClick);
        SetFixedSize(button, size.x, size.y);

        if (sprite != null)
        {
            Mask mask = button.gameObject.AddComponent<Mask>();
            mask.showMaskGraphic = true;
            AddImage(button, sprite);
        }
        else
        {
            AddCenteredText(button, fallbackText, 26f, textColor);
        }

        return button;
    }

    RectTransform CreateCoverButton(Transform parent, Sprite sprite, Vector2 size, UnityAction onClick)
    {
        RectTransform cover = CreateButtonPanel(parent, "CoverCard", new Color(1f, 1f, 1f, 0.09f), 18f, onClick);
        SetFixedSize(cover, size.x, size.y);

        if (sprite != null)
        {
            Mask mask = cover.gameObject.AddComponent<Mask>();
            mask.showMaskGraphic = true;
            AddImage(cover, sprite);
        }
        else
        {
            AddCenteredText(cover, "DONE", 18f, goodAccentColor);
        }

        return cover;
    }

    Image AddImage(RectTransform parent, Sprite sprite)
    {
        GameObject go = new GameObject("Image", typeof(RectTransform));
        go.transform.SetParent(parent, false);
        SetLayer(go);
        RectTransform rect = go.GetComponent<RectTransform>();
        Stretch(rect);

        Image image = go.AddComponent<Image>();
        image.sprite = sprite;
        image.preserveAspect = true;
        image.raycastTarget = false;
        return image;
    }

    TextMeshProUGUI AddCenteredText(RectTransform parent, string text, float size, Color color)
    {
        TextMeshProUGUI label = CreateText(parent, text, size, color, FontStyles.Bold);
        RectTransform rect = label.GetComponent<RectTransform>();
        Stretch(rect);
        label.alignment = TextAlignmentOptions.Center;
        return label;
    }

    RectTransform CreateButtonPanel(Transform parent, string name, Color color, float radius, UnityAction onClick)
    {
        RectTransform rect = CreatePanel(parent, name, color, radius);
        Button button = rect.gameObject.AddComponent<Button>();
        button.targetGraphic = rect.GetComponent<DashboardRoundedGraphic>();
        button.transition = Selectable.Transition.ColorTint;
        button.colors = ButtonColors(color);
        if (onClick != null)
            button.onClick.AddListener(onClick);
        return rect;
    }

    RectTransform CreatePanel(Transform parent, string name, Color color, float radius)
    {
        RectTransform rect = CreateRect(name, parent);
        DashboardRoundedGraphic graphic = rect.gameObject.AddComponent<DashboardRoundedGraphic>();
        graphic.color = color;
        graphic.CornerRadius = radius;

        Outline outline = rect.gameObject.AddComponent<Outline>();
        outline.effectColor = new Color(1f, 1f, 1f, 0.10f);
        outline.effectDistance = new Vector2(1f, -1f);
        return rect;
    }

    TextMeshProUGUI CreateText(Transform parent, string text, float size, Color color, FontStyles style)
    {
        GameObject go = new GameObject("Text", typeof(RectTransform));
        go.transform.SetParent(parent, false);
        SetLayer(go);

        TextMeshProUGUI tmp = go.AddComponent<TextMeshProUGUI>();
        tmp.text = text;
        tmp.fontSize = size;
        tmp.color = color;
        tmp.fontStyle = style;
        tmp.alignment = TextAlignmentOptions.Left;
        tmp.enableWordWrapping = false;
        tmp.raycastTarget = false;
        tmp.margin = Vector4.zero;
        tmp.extraPadding = true;
        return tmp;
    }

    RectTransform CreateRect(string name, Transform parent)
    {
        GameObject go = new GameObject(name, typeof(RectTransform));
        go.transform.SetParent(parent, false);
        SetLayer(go);
        return go.GetComponent<RectTransform>();
    }

    void EnsureCanvas()
    {
        Canvas canvas = GetComponent<Canvas>();
        if (canvas == null) canvas = gameObject.AddComponent<Canvas>();
        canvas.renderMode = RenderMode.ScreenSpaceOverlay;
        canvas.sortingOrder = 20;
        canvas.pixelPerfect = true;

        CanvasScaler scaler = GetComponent<CanvasScaler>();
        if (scaler == null) scaler = gameObject.AddComponent<CanvasScaler>();
        scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
        scaler.referenceResolution = new Vector2(1280f, 720f);
        scaler.matchWidthOrHeight = 0.5f;

        if (GetComponent<GraphicRaycaster>() == null)
            gameObject.AddComponent<GraphicRaycaster>();

        EnsureEventSystem();
    }

    static void EnsureEventSystem()
    {
        EventSystem existing = FindFirstObjectByType<EventSystem>();
        if (existing != null)
        {
            InputSystemUIInputModule existingModule = existing.GetComponent<InputSystemUIInputModule>();
            if (existingModule == null)
                existingModule = existing.gameObject.AddComponent<InputSystemUIInputModule>();
            if (existingModule.actionsAsset == null)
                existingModule.AssignDefaultActions();
            return;
        }

        GameObject eventSystem = new GameObject("EventSystem");
        eventSystem.AddComponent<EventSystem>();
        InputSystemUIInputModule module = eventSystem.AddComponent<InputSystemUIInputModule>();
        module.AssignDefaultActions();
    }

    void DestroyGeneratedRoot()
    {
        for (int i = transform.childCount - 1; i >= 0; i--)
        {
            Transform child = transform.GetChild(i);
            if (child.name != RootName) continue;

            child.gameObject.SetActive(false);
            if (Application.isPlaying)
                Destroy(child.gameObject);
            else
                DestroyImmediate(child.gameObject);
        }
    }

    List<CatRelationshipDashboardItem> DisplayRelationships()
    {
        if (relationships.Count > 0 || !useSampleDataWhenEmpty)
            return relationships;

        return new List<CatRelationshipDashboardItem>
        {
            new CatRelationshipDashboardItem
            {
                catId = "miso",
                catName = "Miso",
                relationshipLabel = "Trusted",
                trust = 0.82f,
                bond = 0.66f,
                description = "Miso is comfortable approaching the player and often checks back after kind interactions.",
                latestMemoryEpisode = "Miso remembered the player feeding her near the dock.",
                memoryEpisodes = new List<string>
                {
                    "Fed near the dock",
                    "Sat beside the player during sunset"
                },
                lastSeenLocation = "Harbor"
            },
            new CatRelationshipDashboardItem
            {
                catId = "nori",
                catName = "Nori",
                relationshipLabel = "Curious",
                trust = 0.54f,
                bond = 0.38f,
                description = "Nori keeps a little distance, but will follow when the player does helpful things nearby.",
                latestMemoryEpisode = "Nori watched the player repair a lantern and stayed nearby.",
                memoryEpisodes = new List<string>
                {
                    "Watched the lantern repair",
                    "Followed at a distance by the village gate"
                },
                lastSeenLocation = "Village gate"
            },
            new CatRelationshipDashboardItem
            {
                catId = "sora",
                catName = "Sora",
                relationshipLabel = "Careful",
                trust = 0.36f,
                bond = 0.22f,
                description = "Sora needs slow, predictable movement before trust grows.",
                memoryEpisodes = new List<string>
                {
                    "Watched from under the boat",
                    "Accepted a quiet approach"
                },
                lastSeenLocation = "Old boat"
            }
        };
    }

    List<CompletedGameItem> DisplayCompletedItems()
    {
        if (completedItems.Count > 0 || !useSampleDataWhenEmpty)
            return completedItems;

        return new List<CompletedGameItem>
        {
            new CompletedGameItem
            {
                taskId = "harbor_path",
                title = "Found the harbor path",
                category = "Exploration",
                completedAt = "Day 1",
                description = "Reached the lower dock and opened a safer route."
            },
            new CompletedGameItem
            {
                taskId = "fed_miso",
                title = "Fed Miso",
                category = "Bond",
                completedAt = "Day 1",
                description = "Created a positive memory episode with Miso."
            },
            new CompletedGameItem
            {
                taskId = "old_boat",
                title = "Checked the old boat",
                category = "Story",
                completedAt = "Day 2",
                description = "Unlocked a new point of interest near the water."
            },
            new CompletedGameItem
            {
                taskId = "lantern_repair",
                title = "Repaired a dock lantern",
                category = "Village",
                completedAt = "Day 2",
                description = "Made the dock safer after sunset."
            }
        };
    }

    Color TrustColor(float value)
    {
        value = Mathf.Clamp01(value);
        if (value >= 0.72f) return goodAccentColor;
        if (value >= 0.42f) return warmAccentColor;
        return accentColor;
    }

    string PlayerInitials()
    {
        return Initials(playerName, "P");
    }

    static string CatInitials(CatRelationshipDashboardItem item)
    {
        return Initials(item != null ? item.catName : "", "C");
    }

    static string Initials(string value, string fallback)
    {
        if (string.IsNullOrWhiteSpace(value)) return fallback;

        string[] parts = value.Trim().Split(' ');
        if (parts.Length == 1)
            return parts[0].Substring(0, 1).ToUpperInvariant();

        return (parts[0].Substring(0, 1) + parts[parts.Length - 1].Substring(0, 1)).ToUpperInvariant();
    }

    static string MemorySummary(CatRelationshipDashboardItem item)
    {
        if (item != null && item.memoryEpisodes != null && item.memoryEpisodes.Count > 0)
        {
            var parts = new List<string>();
            for (int i = 0; i < item.memoryEpisodes.Count && i < 2; i++)
            {
                if (!string.IsNullOrWhiteSpace(item.memoryEpisodes[i]))
                    parts.Add(item.memoryEpisodes[i]);
            }

            if (parts.Count > 0)
                return "Episodes: " + string.Join("; ", parts) + ".";
        }

        if (item != null && !string.IsNullOrWhiteSpace(item.latestMemoryEpisode))
            return item.latestMemoryEpisode;

        return "No shared episode recorded yet.";
    }

    static string TaskMeta(CompletedGameItem item)
    {
        if (item == null) return "";

        string meta = item.category;
        if (!string.IsNullOrWhiteSpace(item.completedAt))
            meta += " - " + item.completedAt;
        return meta;
    }

    void SelectCat(CatRelationshipDashboardItem item)
    {
        if (item == null)
            return;

        string selectedKey = CatKey(item);
        bool changed = _selectedCatId != selectedKey;
        _selectedCatId = selectedKey;
        catSelected?.Invoke(!string.IsNullOrWhiteSpace(item.catId) ? item.catId : item.catName);
        if (changed)
            Rebuild();
    }

    CatRelationshipDashboardItem SelectedCat(List<CatRelationshipDashboardItem> data)
    {
        if (data == null || data.Count == 0)
            return null;

        if (!string.IsNullOrWhiteSpace(_selectedCatId))
        {
            for (int i = 0; i < data.Count; i++)
            {
                if (data[i] != null && CatKey(data[i]) == _selectedCatId)
                    return data[i];
            }
        }

        for (int i = 0; i < data.Count; i++)
        {
            if (data[i] == null)
                continue;

            _selectedCatId = CatKey(data[i]);
            return data[i];
        }

        return null;
    }

    bool IsSelectedCat(CatRelationshipDashboardItem item)
    {
        if (item == null)
            return false;

        if (string.IsNullOrWhiteSpace(_selectedCatId))
            return false;

        return CatKey(item) == _selectedCatId;
    }

    static string CatKey(CatRelationshipDashboardItem item)
    {
        if (item == null)
            return "";

        if (!string.IsNullOrWhiteSpace(item.catId))
            return item.catId;

        return item.catName ?? "";
    }

    static string CatDescription(CatRelationshipDashboardItem item)
    {
        if (item == null)
            return "Select a cat to see their relationship notes and latest shared memory.";

        if (!string.IsNullOrWhiteSpace(item.description))
            return item.description;

        if (!string.IsNullOrWhiteSpace(item.latestMemoryEpisode))
            return item.latestMemoryEpisode;

        return "No relationship description recorded yet.";
    }

    ColorBlock ButtonColors(Color baseColor)
    {
        ColorBlock colors = ColorBlock.defaultColorBlock;
        colors.normalColor = baseColor;
        colors.highlightedColor = Brighten(baseColor, 1.18f);
        colors.pressedColor = Brighten(baseColor, 0.86f);
        colors.selectedColor = Brighten(baseColor, 1.10f);
        colors.disabledColor = new Color(baseColor.r, baseColor.g, baseColor.b, baseColor.a * 0.45f);
        colors.colorMultiplier = 1f;
        colors.fadeDuration = 0.08f;
        return colors;
    }

    static Color Brighten(Color color, float amount)
    {
        return new Color(
            Mathf.Clamp01(color.r * amount),
            Mathf.Clamp01(color.g * amount),
            Mathf.Clamp01(color.b * amount),
            color.a);
    }

    static void AddVerticalLayout(RectTransform rect, int left, int right, int top, int bottom, float spacing)
    {
        VerticalLayoutGroup layout = rect.gameObject.AddComponent<VerticalLayoutGroup>();
        layout.padding = new RectOffset(left, right, top, bottom);
        layout.spacing = spacing;
        layout.childControlWidth = true;
        layout.childControlHeight = true;
        layout.childForceExpandWidth = true;
        layout.childForceExpandHeight = false;
    }

    static void SetFixedSize(RectTransform rect, float width, float height)
    {
        SetFixedWidth(rect, width);
        SetFixedHeight(rect, height);
    }

    static void SetFixedHeight(RectTransform rect, float preferredHeight)
    {
        LayoutElement element = rect.GetComponent<LayoutElement>();
        if (element == null) element = rect.gameObject.AddComponent<LayoutElement>();
        element.minHeight = preferredHeight;
        element.preferredHeight = preferredHeight;
        element.flexibleHeight = 0f;
    }

    static void SetFixedWidth(RectTransform rect, float preferredWidth)
    {
        LayoutElement element = rect.GetComponent<LayoutElement>();
        if (element == null) element = rect.gameObject.AddComponent<LayoutElement>();
        element.minWidth = preferredWidth;
        element.preferredWidth = preferredWidth;
        element.flexibleWidth = 0f;
    }

    static void SetFlexibleWidth(RectTransform rect)
    {
        LayoutElement element = rect.GetComponent<LayoutElement>();
        if (element == null) element = rect.gameObject.AddComponent<LayoutElement>();
        element.minWidth = 0f;
        element.preferredWidth = 0f;
        element.flexibleWidth = 1f;
    }

    static void SetSingleLineEllipsis(TextMeshProUGUI text)
    {
        if (text == null)
            return;

        text.enableWordWrapping = false;
        text.maxVisibleLines = 1;
        text.overflowMode = TextOverflowModes.Ellipsis;
    }

    static void SetWrappedEllipsis(TextMeshProUGUI text, int maxLines)
    {
        if (text == null)
            return;

        text.enableWordWrapping = true;
        text.maxVisibleLines = Mathf.Max(1, maxLines);
        text.overflowMode = TextOverflowModes.Ellipsis;
    }

    static void Stretch(RectTransform rect)
    {
        rect.anchorMin = Vector2.zero;
        rect.anchorMax = Vector2.one;
        rect.offsetMin = Vector2.zero;
        rect.offsetMax = Vector2.zero;
    }

    static void StretchWithMargin(RectTransform rect, Vector2 margin)
    {
        rect.anchorMin = Vector2.zero;
        rect.anchorMax = Vector2.one;
        rect.offsetMin = margin;
        rect.offsetMax = -margin;
    }

    static string SafeName(string value)
    {
        if (string.IsNullOrWhiteSpace(value)) return "Item";
        return value.Replace(" ", "_").Replace("/", "_");
    }

    void SetLayer(GameObject go)
    {
        go.layer = gameObject.layer;
    }
}

[Serializable]
public sealed class CatRelationshipDashboardItem
{
    public string catId = "";
    public string catName = "Cat";
    public Sprite profilePhoto;
    public string relationshipLabel = "New";
    [Range(0f, 1f)] public float trust = 0.5f;
    [Range(0f, 1f)] public float bond = 0.3f;
    [TextArea(2, 5)] public string description = "";
    public string latestMemoryEpisode = "";
    public List<string> memoryEpisodes = new List<string>();
    public string lastSeenLocation = "";
}

[Serializable]
public sealed class CompletedGameItem
{
    public string taskId = "";
    public string title = "Completed task";
    public string category = "Game";
    public string completedAt = "";
    public string description = "";
    public Sprite coverImage;
}

[Serializable]
public sealed class DashboardStringEvent : UnityEvent<string> { }
