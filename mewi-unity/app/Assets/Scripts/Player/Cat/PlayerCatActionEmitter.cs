using System;
using UnityEngine;

[DisallowMultipleComponent]
public sealed class PlayerCatActionEmitter : MonoBehaviour
{
    public static event Action<PlayerCatActionEvent> GlobalActionEmitted;
    public event Action<PlayerCatActionEvent> ActionEmitted;

    public void Emit(PlayerCatActionEvent actionEvent)
    {
        ActionEmitted?.Invoke(actionEvent);
        GlobalActionEmitted?.Invoke(actionEvent);
    }
}
