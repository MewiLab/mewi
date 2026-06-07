/// </summary>
// Eye-perception channel: reads CreaturePerception's sensorEvents from the
// blackboard, summarises them down to the most informative slice, and writes
// the wire-format entity list to the snapshot.
//
// Filtering policy (was previously inside the websocket transport):
//   - Sort by descending intensity (closest/loudest first).
//   - Cap per category so one noisy group can't crowd out the rest.
//   - Take the top N after capping.
//   - Project world position to cat-relative distance + 8-way direction bucket.
/// </summary>
using System;
using System.Collections.Generic;
using UnityEngine;

public sealed class EntitiesChannel : ISnapshotChannel
{
    public string ChannelId => "entities";

    readonly int _maxEntities;
    readonly int _maxPerCategory;

    public EntitiesChannel(int maxEntities, int maxPerCategory)
    {
        _maxEntities    = maxEntities;
        _maxPerCategory = maxPerCategory;
    }

    public void Write(SnapshotPayload payload, CreatureBlackboard board, Transform self)
    {
        payload.entities = Summarise(board, self).ToArray();
    }

    List<EntityData> Summarise(CreatureBlackboard board, Transform self)
    {
        var sorted = new List<SensoryEvent>(board.sensorEvents);
        sorted.Sort((a, b) => b.intensity.CompareTo(a.intensity));

        var perCat = new Dictionary<string, int>();
        var result = new List<EntityData>(_maxEntities);

        for (int i = 0; i < sorted.Count && result.Count < _maxEntities; i++)
        {
            var evt = sorted[i];
            string cat = string.IsNullOrEmpty(evt.category) ? "unknown" : evt.category;

            perCat.TryGetValue(cat, out int count);
            if (count >= _maxPerCategory) continue;
            perCat[cat] = count + 1;

            Vector3 local = self.InverseTransformPoint(evt.position);
            string id = ResolveEntityId(evt);
            RememberTargetAlias(board, id, evt.source, evt.position);
            RememberTargetAlias(board, evt.label, evt.source, evt.position);
            if (evt.source != null)
            {
                RememberTargetAlias(board, evt.source.name, evt.source, evt.position);
                RememberTargetAlias(board, evt.source.root.name, evt.source, evt.position);
            }

            result.Add(new EntityData
            {
                id        = id,
                tags      = evt.tags ?? System.Array.Empty<string>(),
                distance  = Vector3.Distance(self.position, evt.position),
                direction = DirectionBucket(local),
            });
        }
        return result;
    }

    // 8-way bearing relative to the cat's forward.
    //   0° = front, +90° = right, -90° = left, ±180° = back.
    static string DirectionBucket(Vector3 local)
    {
        float angle = Mathf.Atan2(local.x, local.z) * Mathf.Rad2Deg;
        float abs   = Mathf.Abs(angle);
        if (abs <= 22.5f)  return "front";
        if (abs >= 157.5f) return "back";
        if (angle > 0f)
        {
            if (abs <= 67.5f)  return "front_right";
            if (abs <= 112.5f) return "right";
            return "back_right";
        }
        if (abs <= 67.5f)  return "front_left";
        if (abs <= 112.5f) return "left";
        return "back_left";
    }

    static string ResolveEntityId(SensoryEvent evt)
    {
        Transform source = evt.source;
        if (source != null)
        {
            CreatureBlackboard sourceBoard = source.GetComponent<CreatureBlackboard>()
                ?? source.GetComponentInParent<CreatureBlackboard>()
                ?? source.GetComponentInChildren<CreatureBlackboard>();
            if (sourceBoard != null)
                return NormalizeTargetId(sourceBoard.CreatureId);
        }

        return NormalizeTargetId(evt.label);
    }

    static void RememberTargetAlias(
        CreatureBlackboard board,
        string id,
        Transform target,
        Vector3 perceivedPosition)
    {
        if (board == null || target == null || string.IsNullOrWhiteSpace(id))
            return;

        board.RememberPerceivedTarget(id.Trim(), target, perceivedPosition);
    }

    static string NormalizeTargetId(string value)
    {
        if (string.IsNullOrWhiteSpace(value))
            return "";

        string trimmed = value.Trim();
        return !string.Equals(trimmed, "player_cat", StringComparison.OrdinalIgnoreCase)
            && trimmed.EndsWith("_cat", StringComparison.OrdinalIgnoreCase)
            ? trimmed.Substring(0, trimmed.Length - 4)
            : trimmed;
    }
}
