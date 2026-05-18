using MalbersAnimations.Scriptables;
using System;
using UnityEngine;

namespace MalbersAnimations.Reactions
{
    [CreateAssetMenu(menuName = "Malbers Animations/Reactions2 Var", order = 100)]
    public class MReactions2Var : ScriptableObject
    {
        public Reaction2 reaction;

        public void React(Component component)
        {
            if (component == null)
            {
                Debug.LogWarning("There's no component set to apply the reactions");
                return;
            }
            reaction.React(component);
        }

        public void React(GameObject go)
        {
            if (go == null)
            {
                Debug.LogWarning("There's no gameobject set to apply the reactions");
                return;
            }
            reaction.React(go);
        }

        public void React(Transform t) => React((Component)t);

        public void React(GameObjectVar go) => React(go.Value);

        public void React(TransformVar t) => React((Component)t.Value);
    }


    [System.Serializable, AddTypeMenu("[Reaction Var]")]
    public class ScriptableReaction : Reaction
    {
        public MReactions2Var scriptableVar;

        public override Type ReactionType => scriptableVar.reaction.ReactionType;

        protected override bool _TryReact(Component reactor)
        {
            if (scriptableVar == null) return false;
            scriptableVar.React(reactor);
            return true;
        }
    }
}

