using UnityEngine;
using System.Collections.Generic;


#if UNITY_EDITOR
using UnityEditor;
#endif

namespace MalbersAnimations
{
    [CreateAssetMenu(menuName = "Malbers Animations/Tag", fileName = "New Tag", order = 3000)]
    public class Tag : IDs
    {
        public string TagName;
        public HashSet<GameObject> gameObjects = new();

        public bool ValidObjects => gameObjects != null && gameObjects.Count > 0;

        public virtual void Clear() => gameObjects.Clear();
        public virtual void Add(GameObject go)
        {
            gameObjects ??= new HashSet<GameObject>();
            gameObjects.Add(go);
        }

        public virtual void Remove(GameObject go) => gameObjects.Remove(go);

        protected virtual void OnEnable() => ID = name.GetHashCode();
    }

#if UNITY_EDITOR
    [CustomEditor(typeof(Tag))]
    public class TagEditor : Editor
    {
        SerializedProperty ID, TagName;

        Tag M;

        void OnEnable()
        {
            ID = serializedObject.FindProperty("ID");
            TagName = serializedObject.FindProperty("TagName");
            M = (Tag)target;

            if (!Application.isPlaying)
            {
                var tag = (Tag)target;
                var newName = tag.name;
                if (TagName.stringValue != newName)
                {
                    TagName.stringValue = newName;
                    ID.intValue = newName.GetHashCode();
                    serializedObject.ApplyModifiedProperties();
                }
            }
        }

        public override void OnInspectorGUI()
        {
            serializedObject.Update();
            EditorGUILayout.HelpBox("Tag ID is generated using name.GetHashCode().", MessageType.None);

            using (new GUILayout.VerticalScope(EditorStyles.helpBox))
            {
                using (new GUILayout.HorizontalScope())
                {
                    EditorGUIUtility.labelWidth = 70;
                    EditorGUILayout.PropertyField(TagName);
                    EditorGUIUtility.labelWidth = 20;
                    using (new EditorGUI.DisabledGroupScope(true))
                        EditorGUILayout.PropertyField(ID);
                    EditorGUIUtility.labelWidth = 0;
                }
            }
            using (new EditorGUI.DisabledGroupScope(true))
            {
                using (new GUILayout.VerticalScope(EditorStyles.helpBox))
                {
                    EditorGUILayout.LabelField($"Tagged GameObjects [{M.gameObjects.Count}] [RUNTIME ONLY]", EditorStyles.boldLabel);

                    if (Application.isPlaying && M.gameObjects != null)
                    {
                        var index = 0;
                        foreach (var item in M.gameObjects)
                        {
                            EditorGUILayout.ObjectField($"Tagged GameObject [{index}]", item, typeof(GameObject), true);
                            index++;
                        }
                    }
                }
            }

            serializedObject.ApplyModifiedProperties();
        }
    }

    public class TagNameSetter : AssetPostprocessor
    {
        static void OnPostprocessAllAssets(string[] importedAssets, string[] _, string[] __, string[] ___)
        {
            foreach (var path in importedAssets)
            {
                var tag = AssetDatabase.LoadAssetAtPath<Tag>(path);
                if (tag && tag.TagName != tag.name)
                {
                    tag.TagName = tag.name;
                    EditorUtility.SetDirty(tag);
                }
            }
        }
    }
#endif
}