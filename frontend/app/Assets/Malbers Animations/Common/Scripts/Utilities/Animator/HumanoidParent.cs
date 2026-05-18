using MalbersAnimations.Scriptables;
using UnityEngine;

#if UNITY_EDITOR
using UnityEditor;
#endif
namespace MalbersAnimations.Utilities
{
    [AddComponentMenu("Malbers/Utilities/Transform/Humanoid Parent")]
    [DefaultExecutionOrder(1501)]
    public class HumanoidParent : MonoBehaviour
    {
        public Animator animator;
        [SearcheableEnum]
        [Tooltip("Which bone will be the parent of this gameobject")]
        public HumanBodyBones parent = HumanBodyBones.Spine;
        [Tooltip("Reset the Local Position of this gameobject when parented")]
        public BoolReference LocalPos;
        [Tooltip("Reset the Local Rotation of this gameobject when parented")]
        public BoolReference LocalRot;
        [Tooltip("Additional Local Position Offset to add after the gameobject is parented")]
        public Vector3Reference PosOffset;
        [Tooltip("Additional Local Rotation Offset to add after the gameobject is parented")]
        public Vector3Reference RotOffset;

        private void OnEnable()
        {
            if (animator == null) { animator = this.FindComponent<Animator>(); }

            if (animator != null)
                Align();
        }

        private void Align()
        {
            if (animator.avatar != null)
            {
                var boneParent = animator.GetBoneTransform(parent);

                if (boneParent != null && transform.parent != boneParent)
                {
                    transform.parent = boneParent;

                    if (LocalPos.Value) transform.localPosition = Vector3.zero;
                    if (LocalRot.Value) transform.localRotation = Quaternion.identity;

                    transform.localPosition += PosOffset;
                    transform.localRotation *= Quaternion.Euler(RotOffset);
                }
            }
            else
            {
                Debug.LogWarning($"Avatar is missing in the animator. [{name}]", this);
                enabled = false;
            }
        }

        [ContextMenu("Try Align")]
        private void TryAlign()
        {
            if (animator != null && animator.avatar != null)
            {
                var boneParent = animator.GetBoneTransform(parent);

                if (boneParent != null && transform.parent != boneParent)
                {
                    if (LocalPos.Value) transform.position = boneParent.position;
                    if (LocalRot.Value) transform.localRotation = boneParent.rotation;

                    transform.localPosition += PosOffset;
                    transform.localRotation *= Quaternion.Euler(RotOffset);
                }
            }

            if (!Application.isPlaying)
                MTools.SetDirty(this);
        }

        private void OnValidate()
        {
            if (animator == null) animator = gameObject.FindComponent<Animator>();
        }
    }



#if UNITY_EDITOR


    //----------------------------------------------------------------------------------
    //Create an editor to draw the HumanoidParent component in an horizontal groups


    [CustomEditor(typeof(HumanoidParent))]
    public class HumanoidParentEditor : Editor
    {
        SerializedProperty animator, parent, LocalPos, LocalRot, PosOffset, RotOffset;

        private void OnEnable()
        {
            animator = serializedObject.FindProperty("animator");
            parent = serializedObject.FindProperty("parent");
            LocalPos = serializedObject.FindProperty("LocalPos");
            LocalRot = serializedObject.FindProperty("LocalRot");
            PosOffset = serializedObject.FindProperty("PosOffset");
            RotOffset = serializedObject.FindProperty("RotOffset");
        }

        public override void OnInspectorGUI()
        {
            serializedObject.Update();
            using (new GUILayout.VerticalScope(EditorStyles.helpBox))
            {
                using (new GUILayout.HorizontalScope())
                {
                    EditorGUILayout.PropertyField(animator);
                    EditorGUILayout.PropertyField(parent, GUIContent.none, GUILayout.MaxWidth(120));
                }

                using (new GUILayout.HorizontalScope())
                {
                    EditorGUILayout.PropertyField(LocalPos);
                    EditorGUIUtility.labelWidth = 80;
                    EditorGUILayout.PropertyField(LocalRot, GUILayout.MinWidth(100));
                    EditorGUIUtility.labelWidth = 0;
                }

                EditorGUILayout.PropertyField(PosOffset);
                EditorGUILayout.PropertyField(RotOffset);
            }
            serializedObject.ApplyModifiedProperties();
        }
    }
#endif
}
