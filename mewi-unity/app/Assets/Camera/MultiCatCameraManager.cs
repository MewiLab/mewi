using UnityEngine;
using Unity.Cinemachine;
using MalbersAnimations;

public class MultiCatCameraManager : MonoBehaviour
{
    [Header("Cats in the Sandbox")]
    public Transform[] cats;
    [SerializeField] Transform activePlayerCat;
    [Tooltip("Off by default because Malbers MInput/MInputLink should own player input. Enable only for legacy possession/debug switching.")]
    [SerializeField] bool manageCatMInputStates;
    [SerializeField] bool disableMInputOnNpcCats = true;
    [SerializeField] bool handleKeyboardInput = true;
    [Tooltip("Legacy/debug only. Keep false for ADR-029 report sessions so Tab never changes actorId.")]
    [SerializeField] bool possessCatWhenFraming = false;

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
    bool _playerInputEnabled = true;

    public Transform ActivePlayerCat => activePlayerCat;
    public Transform ObservedCat => cats != null && currentCatIndex >= 0 && currentCatIndex < cats.Length
        ? cats[currentCatIndex]
        : null;

    void Start()
    {
        ResolveDemoGodCamera();

        if (cats != null && cats.Length > 0)
        {
            if (activePlayerCat == null)
                activePlayerCat = cats[0];

            FrameObservedCat(0);
            ApplyMInputState();
            SetCameraPriority();
        }
    }

    void Update()
    {
#if ENABLE_LEGACY_INPUT_MANAGER
        if (!handleKeyboardInput)
            return;

        if (Input.GetKeyDown(KeyCode.Tab))
            FrameNextCat();

        if (Input.GetKeyDown(KeyCode.V))
            CycleView();
#endif
    }

    public void SetKeyboardInputEnabled(bool enabled)
    {
        handleKeyboardInput = enabled;
    }

    public void SetPlayerControlEnabled(bool enabled)
    {
        _playerInputEnabled = enabled;
        ApplyMInputState();
    }

    public void SetActivePlayerCat(Transform playerCat)
    {
        if (playerCat == null)
            return;

        activePlayerCat = playerCat;
        ApplyMInputState();
    }

    public void FrameNextCat()
    {
        if (cats == null || cats.Length == 0)
            return;

        FrameObservedCat((currentCatIndex + 1) % cats.Length);
    }

    public void CycleView()
    {
        currentView = (currentView + 1) % GetAvailableViewCount();
        SetCameraPriority();
    }

    public void FrameObservedCat(int index)
    {
        if (cats == null || cats.Length == 0)
            return;

        currentCatIndex = Mathf.Clamp(index, 0, cats.Length - 1);
        Transform observed = cats[currentCatIndex];
        if (observed == null)
            return;

        if (possessCatWhenFraming)
            activePlayerCat = observed;

        SetCameraTargets(observed);
        ApplyMInputState();
        SetCameraPriority();
    }

    void SetCameraTargets(Transform cat)
    {
        Transform camTarget = cat.Find(cameraTargetPath);
        Transform headBone = cat.Find(headBonePath);

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
            Debug.LogWarning("Camera Target not found at path: " + cameraTargetPath + " on " + cat.name);
        }

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
            Debug.LogWarning("FPS_Anchor not found at path: " + headBonePath + " on " + cat.name);
        }
    }

    void ApplyMInputState()
    {
        if (!manageCatMInputStates || cats == null)
            return;

        for (int i = 0; i < cats.Length; i++)
        {
            Transform cat = cats[i];
            if (cat == null)
                continue;

            MInput mInput = cat.GetComponent<MInput>();
            if (mInput == null)
                continue;

            bool isActivePlayer = activePlayerCat != null && cat.root == activePlayerCat.root;
            if (isActivePlayer)
                mInput.enabled = _playerInputEnabled;
            else if (disableMInputOnNpcCats)
                mInput.enabled = false;
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
