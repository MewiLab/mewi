using MalbersAnimations.Conditions;
using MalbersAnimations.Scriptables;
using UnityEngine;

namespace MalbersAnimations.Reactions
{
    [System.Serializable]

    [AddTypeMenu("Tools/Align Look At")]
    public class AlignReaction : Reaction
    {
        public override string DynamicName =>
            $"Align Look At to [{(Target != null && Target.Value != null ? Target.Value.name : "None")}] Align Time [{AlignTime}]"; //Name of the Reaction
        public override System.Type ReactionType => typeof(Component);

        public enum TargetType { Transform, Tag }

        public TargetType SearchTarget = TargetType.Transform;

        [Tooltip("The target to Look At Align")]
        [Hide(nameof(SearchTarget), 0)]
        public TransformReference Target;

        [Tooltip("Objects with tag to Look At Align")]
        [Hide(nameof(SearchTarget), 1)]
        public Tag Tag;

        [Tooltip("The Radius to search for targets. Zero ignore distance")]
        [Min(0)] public float distance = 0;

        [Tooltip("Filter the found target with these conditions")]
        public Conditions2 conditions;

        [Header("Align Settings")]
        public float AlignTime = 0.15f;
        public float AlignOffset = 0f;

        public AnimationCurve AlignCurve = new(MTools.DefaultCurve);


        protected override bool _TryReact(Component component)
        {
            if (component.TryGetComponent<MonoBehaviour>(out var Mono)) //Find a MonoBehaviour to start the Coroutine
            {
                var Targ = SearchTarget == TargetType.Transform ? Target.Value : FindByCondition(component);

                if (Targ != null)
                {
                    if (distance > 0)
                    {
                        MDebug.DrawCircle(component.transform.position, component.transform.rotation, distance, Color.green, 1f);

                        var dist = Vector3.Distance(component.transform.position, Targ.position);
                        if (dist > distance) return false; //Out of range
                    }

                    Mono.StartCoroutine(MTools.AlignLookAtTransform(component.transform, Targ, AlignTime, AlignOffset, AlignCurve));

                    return true;
                }
            }
            return false;
        }

        protected Transform FindByCondition(Component component)
        {
            Transform ClosestGo = null;
            float ClosestDistance = float.MaxValue;

            foreach (var go in Tag.gameObjects)
            {
                if (go == null) continue;
                if (go.transform.IsChildOf(component.transform)) continue; //Skip itself and its children
                if (component.transform.IsChildOf(go.transform)) continue; //Skip if the animal is part of the target
                if (!conditions.Evaluate(go)) continue; //Check extra conditions

                var DistTarget = Vector3.Distance(component.transform.position, go.transform.position);

                if (ClosestDistance > DistTarget)
                {
                    ClosestDistance = DistTarget;
                    ClosestGo = go.transform;
                }
            }
            return ClosestGo;
        }
    }
}
