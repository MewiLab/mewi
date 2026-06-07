using System;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// Builds the thin LLM affordance contract from already-scanned Unity state.
/// It describes possible intent targets; it never executes actions.
/// </summary>
public static class SnapshotAffordanceBuilder
{
    static readonly string[] DefaultIntents = { "REST", "SAFETY", "IDLE" };

    public static void Write(SnapshotPayload payload, CreatureBlackboard board, Transform self, int maxTargets)
    {
        List<AffordanceTargetData> targets = BuildTargets(payload, board, maxTargets);
        payload.targets = targets.ToArray();
        payload.available_intents = BuildAvailableIntents(targets).ToArray();
    }

    static List<AffordanceTargetData> BuildTargets(
        SnapshotPayload payload,
        CreatureBlackboard board,
        int maxTargets)
    {
        var byId = new Dictionary<string, TargetDraft>(StringComparer.OrdinalIgnoreCase);
        AddEntityTargets(payload, byId);
        AddFeelingTargets(board, byId);
        AddRouteTargets(payload, byId);

        var drafts = new List<TargetDraft>(byId.Values);
        drafts.Sort(CompareDrafts);

        int count = maxTargets > 0 ? Mathf.Min(maxTargets, drafts.Count) : 0;
        var result = new List<AffordanceTargetData>(count);
        for (int i = 0; i < count; i++)
            result.Add(drafts[i].ToWire());
        return result;
    }

    static void AddEntityTargets(SnapshotPayload payload, Dictionary<string, TargetDraft> byId)
    {
        if (payload == null || payload.entities == null) return;

        string agentId = payload.agent_id ?? "";
        for (int i = 0; i < payload.entities.Length; i++)
        {
            EntityData entity = payload.entities[i];
            string id = Clean(entity.id);
            if (string.IsNullOrEmpty(id)) continue;
            if (string.Equals(id, agentId, StringComparison.OrdinalIgnoreCase)) continue;

            TargetDraft draft = GetDraft(byId, id);
            draft.distance = entity.distance;
            draft.AddTags(entity.tags);
            AddSupportsFromText(draft, id, entity.tags, "");
        }
    }

    static void AddFeelingTargets(CreatureBlackboard board, Dictionary<string, TargetDraft> byId)
    {
        if (board == null || board.feelingEvents == null) return;

        for (int i = 0; i < board.feelingEvents.Count; i++)
        {
            FeelingEvent evt = board.feelingEvents[i];
            string id = Clean(evt.sourceLabel);
            if (string.IsNullOrEmpty(id) || string.Equals(id, "unknown", StringComparison.OrdinalIgnoreCase))
                id = evt.source != null ? Clean(evt.source.name) : "";
            if (string.IsNullOrEmpty(id)) continue;

            TargetDraft draft = GetDraft(byId, id);
            string[] tags = FeelingTags(evt);
            draft.AddTags(tags);
            AddSupportsFromText(draft, $"{id} {evt.description} {evt.meaning} {evt.sense}", tags, "");
        }
    }

    static void AddRouteTargets(SnapshotPayload payload, Dictionary<string, TargetDraft> byId)
    {
        ZoneRouteEntry[] routes = payload != null && payload.navigation_context != null
            ? payload.navigation_context.zone_routes
            : null;
        if (routes == null) return;

        for (int i = 0; i < routes.Length; i++)
        {
            ZoneRouteEntry route = routes[i];
            string id = Clean(route.id);
            if (string.IsNullOrEmpty(id)) continue;
            if (string.Equals(route.status, "blocked", StringComparison.OrdinalIgnoreCase)) continue;

            TargetDraft draft = GetDraft(byId, id);
            draft.distance = route.distance;
            draft.status = route.status ?? "";
            draft.pathStatus = route.status ?? "";
            draft.pathLength = route.path_length;
            draft.reason = route.reason ?? "";
            draft.AddSupport("EXPLORE");
            draft.AddTag("place");
            if (!string.IsNullOrWhiteSpace(route.status))
                draft.AddTag($"route.{route.status.ToLowerInvariant()}");
        }
    }

    static List<string> BuildAvailableIntents(List<AffordanceTargetData> targets)
    {
        var result = new List<string>();
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        void Add(string intent)
        {
            if (!string.IsNullOrWhiteSpace(intent) && seen.Add(intent))
                result.Add(intent);
        }

        if (targets != null)
        {
            for (int i = 0; i < targets.Count; i++)
            {
                string[] supports = targets[i].supports;
                if (supports == null) continue;
                for (int j = 0; j < supports.Length; j++)
                    Add(supports[j]);
            }
        }

        for (int i = 0; i < DefaultIntents.Length; i++)
            Add(DefaultIntents[i]);
        return result;
    }

    static void AddSupportsFromText(TargetDraft draft, string text, string[] tags, string action)
    {
        string haystack = $"{text} {action} {string.Join(" ", tags ?? Array.Empty<string>())}".ToLowerInvariant();

        if (ContainsAny(haystack, "food", "fish", "edible", "eat", "meal", "treat", "taste"))
        {
            draft.AddSupport("SEEK_FOOD");
            draft.AddSupport("INVESTIGATE");
        }

        if (ContainsAny(haystack, "player", "human", "person"))
        {
            draft.AddSupport("SEEK_PLAYER");
            draft.AddSupport("SOCIALIZE");
        }
        else if (ContainsAny(haystack, "cat", "kitten", "social"))
        {
            draft.AddSupport("SOCIALIZE");
            draft.AddSupport("INVESTIGATE");
        }

        if (ContainsAny(haystack, "place", "zone", "route", "go_to", "explore"))
            draft.AddSupport("EXPLORE");

        if (ContainsAny(haystack, "rest", "sleep", "comfort", "bed", "nest"))
            draft.AddSupport("REST");

        if (ContainsAny(haystack, "danger", "unsafe", "threat", "hide", "flee", "safety", "hot", "fire"))
            draft.AddSupport("SAFETY");

        if (draft.supports.Count == 0)
            draft.AddSupport("INVESTIGATE");
    }

    static string[] FeelingTags(FeelingEvent evt)
    {
        var tags = new List<string> { $"feeling.{evt.sense.ToString().ToLowerInvariant()}" };
        string text = $"{evt.description} {evt.meaning} {evt.triggerName} {evt.sourceLabel}".ToLowerInvariant();

        if (ContainsAny(text, "fish"))
            tags.Add("food.fish");
        else if (ContainsAny(text, "food", "edible", "eat", "meal", "treat", "taste"))
            tags.Add("food");

        if (ContainsAny(text, "danger", "unsafe", "threat", "hot", "fire"))
            tags.Add("danger");
        if (evt.contact)
            tags.Add("contact");
        return tags.ToArray();
    }

    static TargetDraft GetDraft(Dictionary<string, TargetDraft> byId, string id)
    {
        if (!byId.TryGetValue(id, out TargetDraft draft))
        {
            draft = new TargetDraft(id);
            byId[id] = draft;
        }
        return draft;
    }

    static bool ContainsAny(string text, params string[] needles)
    {
        if (string.IsNullOrEmpty(text)) return false;
        for (int i = 0; i < needles.Length; i++)
        {
            if (ContainsToken(text, needles[i])) return true;
        }
        return false;
    }

    static bool ContainsToken(string text, string needle)
    {
        if (string.IsNullOrEmpty(needle)) return false;

        int start = 0;
        while (start < text.Length)
        {
            int index = text.IndexOf(needle, start, StringComparison.OrdinalIgnoreCase);
            if (index < 0) return false;

            int before = index - 1;
            int after = index + needle.Length;
            bool left = before < 0 || !char.IsLetterOrDigit(text[before]);
            bool right = after >= text.Length || !char.IsLetterOrDigit(text[after]);
            if (left && right) return true;

            start = index + 1;
        }

        return false;
    }

    static string Clean(string value)
    {
        return string.IsNullOrWhiteSpace(value) ? "" : value.Trim();
    }

    static int CompareDrafts(TargetDraft a, TargetDraft b)
    {
        int byRank = IntentRank(a).CompareTo(IntentRank(b));
        if (byRank != 0) return byRank;

        int byDistance = a.distance.CompareTo(b.distance);
        if (byDistance != 0) return byDistance;

        return string.Compare(a.id, b.id, StringComparison.OrdinalIgnoreCase);
    }

    static int IntentRank(TargetDraft draft)
    {
        if (draft.HasSupport("SEEK_FOOD")) return 0;
        if (draft.HasSupport("SOCIALIZE") || draft.HasSupport("SEEK_PLAYER")) return 1;
        if (draft.HasSupport("EXPLORE")) return 2;
        if (draft.HasSupport("SAFETY")) return 3;
        if (draft.HasSupport("REST")) return 4;
        return 5;
    }

    sealed class TargetDraft
    {
        public readonly string id;
        public readonly List<string> supports = new List<string>();
        public readonly List<string> tags = new List<string>();
        readonly HashSet<string> _supportSet = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        readonly HashSet<string> _tagSet = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        public float distance;
        public string status = "";
        public string pathStatus = "";
        public float pathLength;
        public string reason = "";

        public TargetDraft(string id)
        {
            this.id = id;
        }

        public void AddSupport(string intent)
        {
            if (!string.IsNullOrWhiteSpace(intent) && _supportSet.Add(intent))
                supports.Add(intent);
        }

        public bool HasSupport(string intent)
        {
            return _supportSet.Contains(intent);
        }

        public void AddTag(string tag)
        {
            if (!string.IsNullOrWhiteSpace(tag) && _tagSet.Add(tag))
                tags.Add(tag);
        }

        public void AddTags(string[] values)
        {
            if (values == null) return;
            for (int i = 0; i < values.Length; i++)
                AddTag(values[i]);
        }

        public AffordanceTargetData ToWire()
        {
            return new AffordanceTargetData
            {
                id = id,
                supports = supports.ToArray(),
                tags = tags.ToArray(),
                distance = distance,
                status = status ?? "",
                path_status = pathStatus ?? status ?? "",
                path_length = pathLength,
                reason = reason ?? "",
            };
        }
    }
}
