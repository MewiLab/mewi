using UnityEngine;
using Unity.Cinemachine; 
using MalbersAnimations;

public class MultiCatCameraManager : MonoBehaviour
{
    [Header("Cats in the Sandbox")]
    public Transform[] cats; 
    private int currentCatIndex = 0;
    private const int ViewCount = 3; 

    [Header("Cinemachine Cameras (Unity 6)")]
    public CinemachineCamera backCam;
    // public CinemachineCamera frontCam;
    public CinemachineCamera fpsCam;
    public CinemachineCamera demoGodCam;

    [Header("Demo Camera")]
    public string demoGodCameraName = "CM_DemoGod";
    public bool instantiateDemoGodPrefabIfNeeded = true;

    [Header("Target Paths")]
    [Tooltip("Path to the 3rd-person camera target")]
    public string cameraTargetPath = "Player Core/CM Main Target"; 
    
    [Tooltip("Make sure this path ends with the FPS_Anchor you created!")]
    public string headBonePath = "CG/Pelvis/Spine/Spine1/Spine2/Neck1/Neck2/FPS_Anchor"; 

    private int currentView = 0; 

    void Start()
    {
        ResolveDemoGodCamera();

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
            currentView = (currentView + 1) % GetAvailableViewCount();
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
                if (backCam == null)
                {
                    Debug.LogWarning("Back camera is not assigned on CameraManager.");
                }
                else if (camTarget != null)
                {
                    backCam.Target.TrackingTarget = camTarget;
                }
                else
                {
                    Debug.LogWarning("Camera Target not found at path: " + cameraTargetPath + " on " + cats[i].name);
                }

                // Set target for FPS View
                if (fpsCam == null)
                {
                    Debug.LogWarning("FPS camera is not assigned on CameraManager.");
                }
                else if (headBone != null)
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
        // 1. Reset cameras to standby
        SetPriority(backCam, 10);
        SetPriority(fpsCam, 10);
        SetPriority(demoGodCam, 10);

        // 2. Elevate the priority of the active view
        if (currentView == 0)
        {
            SetPriority(backCam, 20); 
        }
        else if (currentView == 1)
        {
            SetPriority(fpsCam, 20);
        }
        else if (currentView == 2)
        {
            SetPriority(demoGodCam, 30);
        }
    }

    private int GetAvailableViewCount()
    {
        return demoGodCam == null ? 2 : ViewCount;
    }

    private void SetPriority(CinemachineCamera camera, int priority)
    {
        if (camera != null)
        {
            camera.Priority = priority;
        }
    }

    private void ResolveDemoGodCamera()
    {
        if (demoGodCam == null && !string.IsNullOrEmpty(demoGodCameraName))
        {
            CinemachineCamera[] cameras = FindObjectsByType<CinemachineCamera>(
                FindObjectsInactive.Include,
                FindObjectsSortMode.None);

            foreach (CinemachineCamera camera in cameras)
            {
                if (camera.name == demoGodCameraName)
                {
                    demoGodCam = camera;
                    break;
                }
            }
        }

        if (demoGodCam == null || demoGodCam.gameObject.scene.IsValid() || !instantiateDemoGodPrefabIfNeeded)
        {
            return;
        }

        GameObject instance = Instantiate(demoGodCam.gameObject);
        instance.name = demoGodCam.name;
        demoGodCam = instance.GetComponent<CinemachineCamera>();
    }
}
