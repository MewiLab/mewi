using MalbersAnimations;
using MalbersAnimations.Controller;
using UnityEngine;

[DisallowMultipleComponent]
public sealed class PlayerCatMalbersActionDriver : MonoBehaviour
{
    [Header("Malbers")]
    [SerializeField] MAnimal animal;
    [SerializeField] ModeID actionMode;
    [SerializeField] int actionModeId = 4;

    [Header("Execution")]
    [SerializeField] bool zeroInputAxisBeforeAction = true;
    [SerializeField] bool stopCurrentModeBeforeAction = true;
    [SerializeField] bool forceActivateIfTryFails = true;
    [SerializeField] bool logActions = true;

    [Header("Action Ability Indices")]
    [SerializeField] int startleAbilityIndex = 1;
    [SerializeField] int scratchAbilityIndex = 10;
    [SerializeField] int digAbilityIndex = 10;
    [SerializeField] int lookAroundAbilityIndex = 19;
    [SerializeField] int nodHeadAbilityIndex = 107;
    [SerializeField] int noAbilityIndex = 108;
    [SerializeField] int eatAbilityIndex = 2;
    [SerializeField] int drinkAbilityIndex = 7;
    [SerializeField] int sitAbilityIndex = 8;
    [SerializeField] int lieAbilityIndex = 11;
    [SerializeField] int sleepAbilityIndex = 6;
    [SerializeField] int groomAbilityIndex = 29;
    [SerializeField] int smellAbilityIndex = 16;
    [SerializeField] int alertAbilityIndex = 19;
    [SerializeField] int vocalizeAbilityIndex = 20;
    [SerializeField] int crawlAbilityIndex = 9;
    [SerializeField] int openChestAbilityIndex = 18;
    [SerializeField] int shakeAbilityIndex = 26;
    [SerializeField] int pushAbilityIndex = 13;
    [SerializeField] int poopAbilityIndex = 24;
    [SerializeField] int peeAbilityIndex = 25;

    int ActionModeId => actionMode != null ? actionMode.ID : actionModeId;

    void Awake()
    {
        ResolveReferences();
    }

    public bool TryPlay(string motorAction)
    {
        ResolveReferences();
        string action = Normalize(motorAction);
        if (animal == null || string.IsNullOrWhiteSpace(action))
            return false;

        if (!TryGetAbilityIndex(action, out int abilityIndex))
        {
            if (logActions)
                Debug.LogWarning($"[PlayerCatMalbersActionDriver] unmapped player action '{action}'.", this);
            return false;
        }

        int modeId = ActionModeId;
        if (modeId <= 0 || abilityIndex <= 0)
        {
            if (logActions)
                Debug.LogWarning($"[PlayerCatMalbersActionDriver] invalid action mode={modeId} ability={abilityIndex} for '{action}'.", this);
            return false;
        }

        if (zeroInputAxisBeforeAction)
            animal.SetInputAxis(Vector3.zero);
        if (stopCurrentModeBeforeAction)
            StopCurrentMode();

        bool activated = animal.Mode_TryActivate(modeId, abilityIndex);
        if (!activated && forceActivateIfTryFails)
            activated = animal.Mode_ForceActivate(modeId, abilityIndex);

        if (logActions)
        {
            string state = activated ? "played" : "rejected";
            Debug.Log($"[PlayerCatMalbersActionDriver] {state} action={action} mode={modeId} ability={abilityIndex}.", this);
        }

        return activated;
    }

    public bool TryGetAbilityIndex(string motorAction, out int abilityIndex)
    {
        switch (Normalize(motorAction))
        {
            case "flinch":
            case "stun":
            case "startle":
                abilityIndex = startleAbilityIndex;
                return abilityIndex > 0;
            case "scratch":
                abilityIndex = scratchAbilityIndex;
                return abilityIndex > 0;
            case "dig":
                abilityIndex = digAbilityIndex;
                return abilityIndex > 0;
            case "look_around":
                abilityIndex = lookAroundAbilityIndex;
                return abilityIndex > 0;
            case "nod_head":
            case "yes":
                abilityIndex = nodHeadAbilityIndex;
                return abilityIndex > 0;
            case "no":
                abilityIndex = noAbilityIndex;
                return abilityIndex > 0;
            case "eat":
                abilityIndex = eatAbilityIndex;
                return abilityIndex > 0;
            case "drink":
                abilityIndex = drinkAbilityIndex;
                return abilityIndex > 0;
            case "sit":
                abilityIndex = sitAbilityIndex;
                return abilityIndex > 0;
            case "lie":
                abilityIndex = lieAbilityIndex;
                return abilityIndex > 0;
            case "sleep":
                abilityIndex = sleepAbilityIndex;
                return abilityIndex > 0;
            case "groom":
                abilityIndex = groomAbilityIndex;
                return abilityIndex > 0;
            case "smell":
                abilityIndex = smellAbilityIndex;
                return abilityIndex > 0;
            case "alert":
                abilityIndex = alertAbilityIndex;
                return abilityIndex > 0;
            case "vocalize":
            case "meow":
                abilityIndex = vocalizeAbilityIndex;
                return abilityIndex > 0;
            case "crawl":
                abilityIndex = crawlAbilityIndex;
                return abilityIndex > 0;
            case "open_chest":
                abilityIndex = openChestAbilityIndex;
                return abilityIndex > 0;
            case "shake":
                abilityIndex = shakeAbilityIndex;
                return abilityIndex > 0;
            case "push":
                abilityIndex = pushAbilityIndex;
                return abilityIndex > 0;
            case "poop":
                abilityIndex = poopAbilityIndex;
                return abilityIndex > 0;
            case "pee":
                abilityIndex = peeAbilityIndex;
                return abilityIndex > 0;
            default:
                abilityIndex = 0;
                return false;
        }
    }

    void StopCurrentMode()
    {
        if (animal == null)
            return;

        if (animal.IsPlayingMode)
            animal.Mode_Stop(true);
        if (animal.IsPreparingMode)
            animal.Mode_Interrupt_Forced();
    }

    void ResolveReferences()
    {
        if (animal == null)
            animal = GetComponent<MAnimal>()
                ?? GetComponentInChildren<MAnimal>()
                ?? GetComponentInParent<MAnimal>();
    }

    static string Normalize(string value)
        => string.IsNullOrWhiteSpace(value)
            ? ""
            : value.Trim().ToLowerInvariant().Replace('-', '_').Replace(' ', '_');
}
