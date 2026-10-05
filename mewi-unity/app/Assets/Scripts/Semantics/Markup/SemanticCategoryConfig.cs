using System;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// ScriptableObject that maps GameObject name patterns to semantic categories.
/// Create via: Assets > Create > Creature > Semantic Category Config
///
/// PATTERN SYNTAX (evaluated top-to-bottom, first match wins):
///   *Fish*     = contains "Fish" anywhere (case-insensitive)
///   SM_Fish*   = starts with "SM_Fish"
///   Lantern_01 = exact match
///
/// STRATEGY FOR THIS SCENE:
///   The SM_ prefix asset pack follows the pattern:
///     SM_<Type>_<variant>_<index>
///   Rules target the TYPE segment only via wildcard contains (*Type*).
///   More specific rules go ABOVE general ones.
/// </summary>
[CreateAssetMenu(menuName = "Creature/Semantic Category Config", fileName = "SemanticCategoryConfig")]
public class SemanticCategoryConfig : ScriptableObject
{
    [Serializable]
    public class PatternRule
    {
        [Tooltip("Wildcard pattern. Use * as wildcard. Case-insensitive.")]
        public string pattern  = "";

        [Tooltip("Semantic category sent to the AI backend.")]
        public string category = "unknown";

        [Tooltip("Optional label override. Leave empty to use the parent GameObject name.")]
        public string labelOverride = "";
    }

    [Tooltip("Rules are evaluated top-to-bottom — first match wins. Put specific rules above general ones.")]
    public List<PatternRule> rules = new List<PatternRule>
    {
        // ── HOUSES ───────────────────────────────────────────────────────────
        new PatternRule { pattern = "BP_House*",        category = "house"    },

        // ── BOATS ─────────────────────────────────────────────────────────────
        new PatternRule { pattern = "BP_Boat*",         category = "boat"     },
        new PatternRule { pattern = "*Boat*",           category = "boat"     },

        // ── FISH NETS (must be before *Fish* or it catches these too) ─────────
        new PatternRule { pattern = "*Fish_net*",       category = "fish_net" },
        new PatternRule { pattern = "*fish_net*",       category = "fish_net" },
        new PatternRule { pattern = "*Fish_Net*",       category = "fish_net" },
        new PatternRule { pattern = "*Fish_net_beam*",  category = "fish_net" },

        // ── FOOD ──────────────────────────────────────────────────────────────
        new PatternRule { pattern = "*Fish*",           category = "fish"     },
        new PatternRule { pattern = "*Bread*",          category = "food"     },
        new PatternRule { pattern = "*Apple*",          category = "food"     },
        new PatternRule { pattern = "*B_Apple*",        category = "food"     },

        // ── CONTAINERS ────────────────────────────────────────────────────────
        new PatternRule { pattern = "*Barrel*",         category = "barrel"   },
        new PatternRule { pattern = "*Bucket*",         category = "bucket"   },
        new PatternRule { pattern = "*Box_fabric*",     category = "crate"    },
        new PatternRule { pattern = "*Box*",            category = "crate"    },
        new PatternRule { pattern = "*Basket*",         category = "basket"   },
        new PatternRule { pattern = "*Bag*",            category = "bag"      },
        new PatternRule { pattern = "*Pot*",            category = "pot"      },
        new PatternRule { pattern = "*Bottle*",         category = "bottle"   },
        new PatternRule { pattern = "*Plate*",          category = "plate"    },

        // ── FURNITURE ────────────────────────────────────────────────────────
        new PatternRule { pattern = "*Chair*",          category = "furniture" },
        new PatternRule { pattern = "*Table*",          category = "furniture" },
        new PatternRule { pattern = "*Shelf*",          category = "furniture" },

        // ── LIGHT SOURCES ─────────────────────────────────────────────────────
        new PatternRule { pattern = "*Lantern*",        category = "lantern"  },

        // ── STRUCTURE / ARCHITECTURE ──────────────────────────────────────────
        new PatternRule { pattern = "*Wood_column*",    category = "structure" },
        new PatternRule { pattern = "*Column*",         category = "structure" },
        new PatternRule { pattern = "*Beam*",           category = "structure" },
        new PatternRule { pattern = "*Window*",         category = "structure" },
        new PatternRule { pattern = "*Construction*",   category = "platform"  }, // scaffolding/dock platform
        new PatternRule { pattern = "*Fabric_floor*",   category = "surface"   },

        // ── NAVIGATION / CLIMBABLE ────────────────────────────────────────────
        // SM_Step_01 through SM_Step_35 are individual stair step mesh instances
        // The cat sees them all as "stairs" — don't need to distinguish each step
        new PatternRule { pattern = "*Step*",           category = "stairs"   },
        new PatternRule { pattern = "*Ladder*",         category = "ladder"   },

        // ── ROPES / RIGGING ───────────────────────────────────────────────────
        new PatternRule { pattern = "*Rope*",           category = "rope"     },
        new PatternRule { pattern = "*Chain*",          category = "rope"     },

        // ── TOOLS / PROPS ─────────────────────────────────────────────────────
        new PatternRule { pattern = "*Paddle*",         category = "tool"     },

        // ── NATURAL ───────────────────────────────────────────────────────────
        new PatternRule { pattern = "*Rock*",           category = "rock"     },

        // ── WORLD / BACKGROUND ───────────────────────────────────────────────
        new PatternRule { pattern = "*Backdrop*",       category = "scenery"  },
        new PatternRule { pattern = "Terrain",          category = "terrain"  },
        new PatternRule { pattern = "Plane",            category = "terrain"  },

        // ── UNRECOGNISED → "unknown" → skipped by stamper ─────────────────────
        // Add new rules here as you discover new asset types in the scene.
    };

    // ─────────────────────────────────────────────────────────────────────────
    //  Public API
    // ─────────────────────────────────────────────────────────────────────────

    public string GetCategory(string objectName)
    {
        foreach (var rule in rules)
            if (Matches(objectName, rule.pattern))
                return rule.category;
        return "unknown";
    }

    public string GetLabelOverride(string objectName)
    {
        foreach (var rule in rules)
            if (Matches(objectName, rule.pattern) && !string.IsNullOrEmpty(rule.labelOverride))
                return rule.labelOverride;
        return null;
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  Wildcard matcher (* only, case-insensitive)
    // ─────────────────────────────────────────────────────────────────────────

    public static bool Matches(string name, string pattern)
    {
        if (string.IsNullOrEmpty(pattern)) return false;
        if (pattern == "*") return true;
        if (!pattern.Contains("*"))
            return string.Equals(name, pattern, StringComparison.OrdinalIgnoreCase);

        string[] parts = pattern.Split('*');
        int pos = 0;

        for (int i = 0; i < parts.Length; i++)
        {
            if (string.IsNullOrEmpty(parts[i])) continue;
            int idx = name.IndexOf(parts[i], pos, StringComparison.OrdinalIgnoreCase);
            if (idx < 0) return false;
            if (i == 0 && !pattern.StartsWith("*") && idx != 0) return false;
            pos = idx + parts[i].Length;
        }

        if (!pattern.EndsWith("*") && parts.Length > 0)
        {
            string last = parts[parts.Length - 1];
            if (!string.IsNullOrEmpty(last) &&
                !name.EndsWith(last, StringComparison.OrdinalIgnoreCase))
                return false;
        }

        return true;
    }
}