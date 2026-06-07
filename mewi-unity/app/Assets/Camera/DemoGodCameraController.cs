using UnityEngine;
using Unity.Cinemachine;
#if ENABLE_INPUT_SYSTEM
using UnityEngine.InputSystem;
#endif

[RequireComponent(typeof(CinemachineCamera))]
public class DemoGodCameraController : MonoBehaviour
{
    public float moveSpeed = 8f;
    public float fastMultiplier = 4f;
    public float lookSensitivity = 2f;
    public int activePriorityThreshold = 20;
    public bool lockCursorWhileLooking = true;

    private CinemachineCamera cinemachineCamera;
    private float yaw;
    private float pitch;

    void Awake()
    {
        cinemachineCamera = GetComponent<CinemachineCamera>();
    }

    void Start()
    {
        CacheAngles();
    }

    void OnEnable()
    {
        CacheAngles();
    }

    void Update()
    {
        if (!IsActiveGodCamera())
        {
            UnlockCursor();
            return;
        }

        bool isLooking = IsLookButtonHeld();
        if (isLooking)
        {
            LockCursor();

            Vector2 lookDelta = ReadLookDelta();
            yaw += lookDelta.x * lookSensitivity;
            pitch -= lookDelta.y * lookSensitivity;
            pitch = Mathf.Clamp(pitch, -89f, 89f);

            transform.rotation = Quaternion.Euler(pitch, yaw, 0f);
        }
        else
        {
            UnlockCursor();
        }

        float speed = IsFastMoveHeld() ? moveSpeed * fastMultiplier : moveSpeed;
        Vector3 move = ReadMoveInput();

        if (move.sqrMagnitude > 1f)
        {
            move.Normalize();
        }

        transform.position += transform.TransformDirection(move) * speed * Time.deltaTime;
    }

    void OnDisable()
    {
        UnlockCursor();
    }

    private bool IsActiveGodCamera()
    {
        return cinemachineCamera == null || cinemachineCamera.Priority >= activePriorityThreshold;
    }

    private void CacheAngles()
    {
        Vector3 angles = transform.eulerAngles;
        yaw = angles.y;
        pitch = angles.x;
    }

    private Vector3 ReadMoveInput()
    {
        Vector3 move = Vector3.zero;

#if ENABLE_INPUT_SYSTEM
        Keyboard keyboard = Keyboard.current;
        if (keyboard != null)
        {
            if (keyboard.aKey.isPressed) move.x -= 1f;
            if (keyboard.dKey.isPressed) move.x += 1f;
            if (keyboard.sKey.isPressed) move.z -= 1f;
            if (keyboard.wKey.isPressed) move.z += 1f;
            if (keyboard.qKey.isPressed) move.y -= 1f;
            if (keyboard.eKey.isPressed) move.y += 1f;

            return move;
        }
#endif

#if ENABLE_LEGACY_INPUT_MANAGER
        move.x = Input.GetAxisRaw("Horizontal");
        move.z = Input.GetAxisRaw("Vertical");

        if (Input.GetKey(KeyCode.Q)) move.y -= 1f;
        if (Input.GetKey(KeyCode.E)) move.y += 1f;
#endif

        return move;
    }

    private Vector2 ReadLookDelta()
    {
#if ENABLE_INPUT_SYSTEM
        Mouse mouse = Mouse.current;
        if (mouse != null)
        {
            return mouse.delta.ReadValue() * 0.05f;
        }
#endif

#if ENABLE_LEGACY_INPUT_MANAGER
        return new Vector2(Input.GetAxis("Mouse X"), Input.GetAxis("Mouse Y"));
#else
        return Vector2.zero;
#endif
    }

    private bool IsLookButtonHeld()
    {
#if ENABLE_INPUT_SYSTEM
        Mouse mouse = Mouse.current;
        if (mouse != null)
        {
            return mouse.rightButton.isPressed;
        }
#endif

#if ENABLE_LEGACY_INPUT_MANAGER
        return Input.GetMouseButton(1);
#else
        return false;
#endif
    }

    private bool IsFastMoveHeld()
    {
#if ENABLE_INPUT_SYSTEM
        Keyboard keyboard = Keyboard.current;
        if (keyboard != null)
        {
            return keyboard.leftShiftKey.isPressed || keyboard.rightShiftKey.isPressed;
        }
#endif

#if ENABLE_LEGACY_INPUT_MANAGER
        return Input.GetKey(KeyCode.LeftShift) || Input.GetKey(KeyCode.RightShift);
#else
        return false;
#endif
    }

    private void LockCursor()
    {
        if (!lockCursorWhileLooking) return;

        Cursor.lockState = CursorLockMode.Locked;
        Cursor.visible = false;
    }

    private void UnlockCursor()
    {
        if (!lockCursorWhileLooking) return;

        Cursor.lockState = CursorLockMode.None;
        Cursor.visible = true;
    }
}
