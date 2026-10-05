using System.Collections.Generic;
using System.Text;
using UnityEngine;

[DisallowMultipleComponent]
public sealed class PlayerCatUserConfig : MonoBehaviour
{
    [Header("User")]
    [SerializeField] string userName = "vanillaSky00";
    [SerializeField] string sessionIdPrefix = "unity-session";

    [Header("Player Cat")]
    [SerializeField] string playerCreatureId = "vanillaSky00";
    [SerializeField] string playerPrefabAlias = "vanillaSky00";
    [SerializeField] Transform playerCatRoot;
    [SerializeField] CreatureBlackboard playerBlackboard;
    [SerializeField] SmartObject playerSmartObject;
    [SerializeField] bool addPlayerSmartObjectTag = true;

    [Header("Scene Systems")]
    [SerializeField] ReportSessionLogger reportSessionLogger;
    [SerializeField] bool rememberPlayerOnAllCreatureBlackboards = true;
    [SerializeField] bool applyOnAwake = true;

    public string UserName => userName;
    public string UserCatId => ResolvePlayerCreatureId();

    void Awake()
    {
        ResolveReferences();
        if (applyOnAwake)
            Apply();
    }

    public void ApplyUserName(string nextUserName)
    {
        if (!string.IsNullOrWhiteSpace(nextUserName))
        {
            userName = nextUserName.Trim();
            if (string.IsNullOrWhiteSpace(playerCreatureId))
                playerCreatureId = userName;
            if (string.IsNullOrWhiteSpace(playerPrefabAlias))
                playerPrefabAlias = userName;
        }

        ResolveReferences();
        Apply();
    }

    [ContextMenu("Player Cat User/Apply")]
    public void Apply()
    {
        ResolveReferences();

        string userCatId = ResolvePlayerCreatureId();
        if (string.IsNullOrWhiteSpace(userCatId))
            userCatId = "player";

        if (playerBlackboard != null)
            playerBlackboard.SetCreatureId(userCatId);

        ConfigureSmartObject(userCatId);

        if (reportSessionLogger != null)
        {
            string prefix = string.IsNullOrWhiteSpace(sessionIdPrefix)
                ? $"unity-session-{userCatId}"
                : sessionIdPrefix;
            reportSessionLogger.ConfigurePlayerIdentity(
                string.IsNullOrWhiteSpace(userName) ? userCatId : userName.Trim(),
                playerCatRoot,
                playerBlackboard,
                prefix);
        }

        if (rememberPlayerOnAllCreatureBlackboards)
            RememberPlayerOnAllCreatureBlackboards(userCatId);
    }

    void ConfigureSmartObject(string userCatId)
    {
        if (playerSmartObject == null)
            return;

        playerSmartObject.label = userCatId;
        if (!addPlayerSmartObjectTag)
            return;

        if (playerSmartObject.tags == null)
            playerSmartObject.tags = new List<string>();
        if (!playerSmartObject.HasTag("entity.player"))
            playerSmartObject.tags.Add("entity.player");
    }

    void RememberPlayerOnAllCreatureBlackboards(string userCatId)
    {
        if (playerCatRoot == null)
            return;

        CreatureBlackboard[] boards = FindObjectsByType<CreatureBlackboard>(
            FindObjectsInactive.Exclude,
            FindObjectsSortMode.None);

        for (int i = 0; i < boards.Length; i++)
        {
            CreatureBlackboard board = boards[i];
            if (board == null || board == playerBlackboard)
                continue;

            RememberAlias(board, userCatId);
            RememberAlias(board, userName);
            RememberAlias(board, playerCreatureId);
            RememberAlias(board, playerPrefabAlias);
            RememberAlias(board, playerCatRoot.name);
            RememberAlias(board, playerCatRoot.root.name);
            RememberAlias(board, "player");
            RememberAlias(board, "player_cat");
        }
    }

    void RememberAlias(CreatureBlackboard board, string alias)
    {
        if (board == null || playerCatRoot == null || string.IsNullOrWhiteSpace(alias))
            return;

        board.RememberPerceivedTarget(
            NormalizeId(alias),
            playerCatRoot,
            playerCatRoot.position);
    }

    string ResolvePlayerCreatureId()
    {
        if (!string.IsNullOrWhiteSpace(playerCreatureId))
            return playerCreatureId.Trim();
        if (!string.IsNullOrWhiteSpace(userName))
            return userName.Trim();
        return "";
    }

    void ResolveReferences()
    {
        if (playerCatRoot == null)
            playerCatRoot = transform;
        if (playerBlackboard == null && playerCatRoot != null)
            playerBlackboard = playerCatRoot.GetComponent<CreatureBlackboard>()
                ?? playerCatRoot.GetComponentInChildren<CreatureBlackboard>()
                ?? playerCatRoot.GetComponentInParent<CreatureBlackboard>();
        if (playerSmartObject == null && playerCatRoot != null)
            playerSmartObject = playerCatRoot.GetComponent<SmartObject>()
                ?? playerCatRoot.GetComponentInChildren<SmartObject>()
                ?? playerCatRoot.GetComponentInParent<SmartObject>();
        if (reportSessionLogger == null)
            reportSessionLogger = FindFirstObjectByType<ReportSessionLogger>();
    }

    static string NormalizeId(string value)
    {
        if (string.IsNullOrWhiteSpace(value))
            return "";

        string trimmed = value.Trim().ToLowerInvariant();
        var builder = new StringBuilder(trimmed.Length);
        bool lastWasSeparator = false;
        for (int i = 0; i < trimmed.Length; i++)
        {
            char c = trimmed[i];
            bool allowed = char.IsLetterOrDigit(c) || c == '-' || c == '_';
            if (allowed)
            {
                builder.Append(c);
                lastWasSeparator = false;
            }
            else if (!lastWasSeparator)
            {
                builder.Append('_');
                lastWasSeparator = true;
            }
        }

        return builder.ToString().Trim('_');
    }
}
