using UnityEngine;
using Unity.Cinemachine; 
using MalbersAnimations;

public class MultiCatCameraManager : MonoBehaviour
{
    [Header("Cats in the Sandbox")]
    public Transform[] cats; 
    private int currentCatIndex = 0;
    private int view_count = 2; 

    [Header("Cinemachine Cameras (Unity 6)")]
    public CinemachineCamera backCam;
    // public CinemachineCamera frontCam;
    public CinemachineCamera fpsCam;

    [Header("Target Paths")]
    [Tooltip("Path to the 3rd-person camera target")]
    public string cameraTargetPath = "Player Core/CM Main Target"; 
    
    [Tooltip("Make sure this path ends with the FPS_Anchor you created!")]
    public string headBonePath = "CG/Pelvis/Spine/Spine1/Spine2/Neck1/Neck2/FPS_Anchor"; 

    private int currentView = 0; 

    void Start()
    {
        // Initialize by focusing on the first cat
        if (cats.Length > 0)
        {
            SwitchCat(0);
            SetCameraPriority(); 
        }
    }

    void Update()
    {
        // LAYER 1: Switch between cats (using Tab key)
        if (Input.GetKeyDown(KeyCode.Tab))
        {
            if (cats.Length == 0) return; 
            currentCatIndex = (currentCatIndex + 1) % cats.Length;
            SwitchCat(currentCatIndex);
        }

        // LAYER 2: Switch camera angle (using V key)
        if (Input.GetKeyDown(KeyCode.V))
        {
            currentView = (currentView + 1) % view_count;
            SetCameraPriority();
        }
    }

    private void SwitchCat(int index)
    {
        for (int i = 0; i < cats.Length; i++)
        {
            if (cats[i] == null) continue;

            // Find Malbers Input and Camera Targets
            var mInput = cats[i].GetComponent<MInput>();
            
            // Now using your custom Inspector variable!
            Transform camTarget = cats[i].Find(cameraTargetPath); 
            Transform headBone = cats[i].Find(headBonePath); 

            if (i == index)
            {
                // ENABLE Player Control
                if (mInput != null) mInput.enabled = true;
                
                // Set target for Back View
                if (camTarget != null)
                {
                    backCam.Target.TrackingTarget = camTarget;
                }
                else
                {
                    Debug.LogWarning("Camera Target not found at path: " + cameraTargetPath + " on " + cats[i].name);
                }

                // Set target for FPS View
                if (headBone != null)
                {
                    fpsCam.Target.TrackingTarget = headBone;
                }
                else
                {
                    Debug.LogWarning("FPS_Anchor not found at path: " + headBonePath + " on " + cats[i].name);
                }
            }
            else
            {
                // DISABLE Player Control (Cat returns to AI state)
                if (mInput != null) mInput.enabled = false;
            }
        }
    }

    private void SetCameraPriority()
    {
        // 1. Reset both to standby
        backCam.Priority = 10;
        fpsCam.Priority = 10;

        // 2. Elevate the priority of the active view
        if (currentView == 0)
        {
            backCam.Priority = 20; 
        }
        else if (currentView == 1)
        {
            fpsCam.Priority = 20;
        }
    }
}