"""
cat_agent.py — Python agent that plays a Malbers Animal Controller cat in Unity.

Requirements:
    pip install anthropic mss

Usage:
    1. Attach AgentBridge.cs to your cat GameObject in Unity
    2. Press Play in Unity
    3. Run: python cat_agent.py --mode test        (test connection, no API key needed)
           python cat_agent.py --mode bridge       (LLM agent via HTTP bridge)
           python cat_agent.py --mode keypress     (LLM agent via raw keypresses, no Unity mod)

Action format sent to AgentBridge:
    {"action": "Jump",  "hold": 0.2}                       # button press
    {"action": "move",  "x": 0, "y": 1, "hold": 0.5}      # directional move
    {"action": "stop"}                                      # halt movement
"""

import argparse
import json
import time
import base64
import sys
import re
import urllib.request

# ==============================================================================
# CONFIG
# ==============================================================================

BRIDGE_URL = "http://localhost:8080"

# Human-readable descriptions for known Malbers button names.
# Used to build the LLM system prompt. Any button name not listed here
# gets a generic description — so the LLM still works even with custom names.
_KNOWN_DESCRIPTIONS = {
    "move":      "Move with axis: x (-1=left, 1=right), y (-1=back, 1=forward). Add 'hold' (seconds).",
    "stop":      "Stop all movement immediately.",
    "wait":      "Do nothing this step.",
    # common Malbers defaults — may differ in your project
    "Jump":      "Jump.",
    "Sprint":    "Sprint — hold for duration, releases automatically.",
    "Crouch":    "Crouch / toggle crouch.",
    "Dodge":     "Dodge or roll.",
    "Attack1":   "Primary attack.",
    "Attack2":   "Secondary attack.",
    "Interact":  "Interact with a nearby object or NPC.",
    "Action1":   "Action slot 1.",
    "Action2":   "Action slot 2.",
    "Action3":   "Action slot 3.",
    "Action4":   "Action slot 4.",
    "Ability1":  "Ability slot 1.",
    "Ability2":  "Ability slot 2.",
    "LockOn":    "Lock on to target.",
    "Strafe":    "Toggle strafe mode.",
    "Holster1":  "Equip holster slot 1.",
    "Holster2":  "Equip holster slot 2.",
    "Holster3":  "Equip holster slot 3.",
    "Inventory": "Open/close inventory.",
}

# Populated at startup from the bridge's /actions endpoint.
# Falls back to _KNOWN_DESCRIPTIONS keys if the bridge is unreachable.
_live_actions: list[str] = []


def fetch_live_actions() -> list[str]:
    """Fetch the real registered action names from the bridge."""
    resp = bridge_request("/actions")
    if resp and resp.get("actions"):
        names = resp["actions"]
        print(f"  [actions] Fetched {len(names)} actions from bridge: {names}")
        return names
    # fallback — bridge unreachable
    fallback = list(_KNOWN_DESCRIPTIONS.keys())
    print(f"  [actions] Could not fetch from bridge, using fallback list ({len(fallback)} actions).")
    return fallback


def get_actions_dict() -> dict:
    """Build the ACTIONS dict from live names + known descriptions."""
    return {
        name: {"description": _KNOWN_DESCRIPTIONS.get(name, f"Trigger the '{name}' input.")}
        for name in _live_actions
    }


SYSTEM_PROMPT = """You are an AI agent controlling a cat character in a 3D Unity game.
You see a screenshot of the game each frame and must decide what action to take.

Available actions — respond with EXACTLY one JSON object using one of these:
{actions_list}

The "hold" field (seconds, default 0.3) controls how long a button stays pressed.
For "move", "x" is horizontal (-1=left, 1=right) and "y" is forward/back (-1=back, 1=forward).

Rules:
1. Respond with ONLY a valid JSON object — no extra text.
2. Include a "reason" field briefly explaining your thinking.
3. Explore the environment. Be curious like a cat!
4. Navigate around obstacles rather than walking into them.
5. To sprint: send the Sprint action with a hold duration, then a move action.

Examples:
{{"action": "move",   "x": 0,   "y": 1,   "hold": 0.5, "reason": "path is clear ahead"}}
{{"action": "move",   "x": 0.5, "y": 0.8, "hold": 0.4, "reason": "moving diagonally"}}
{{"action": "stop",                                      "reason": "reached destination"}}
"""


# ==============================================================================
# SCREEN CAPTURE
# ==============================================================================

def capture_screen_b64() -> str:
    """Capture the primary monitor and return a base64-encoded PNG string."""
    import mss
    with mss.mss() as sct:
        img = sct.grab(sct.monitors[1])
        png_bytes = mss.tools.to_png(img.rgb, img.size)
        return base64.standard_b64encode(png_bytes).decode()


# ==============================================================================
# BRIDGE MODE — HTTP to AgentBridge in Unity
# ==============================================================================

def bridge_request(path, data=None):
    """GET or POST to AgentBridge. Returns parsed JSON or None on error."""
    url = f"{BRIDGE_URL}{path}"
    if data is not None:
        payload = json.dumps(data).encode()
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
    else:
        req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"  [!] Bridge error ({path}): {e}")
        return None


def bridge_ping() -> bool:
    r = bridge_request("/ping")
    return r is not None and r.get("status") == "ok"


def bridge_get_state():
    return bridge_request("/state")


def bridge_send_action(action_data: dict):
    payload = {k: action_data[k] for k in ("action", "hold", "x", "y") if k in action_data}
    return bridge_request("/action", data=payload)


# ==============================================================================
# KEYPRESS MODE — raw keyboard simulation (no Unity modification needed)
#
# Key bindings here are your KEYBOARD mappings, not action names.
# Update these to match your Unity Input settings if they differ.
# ==============================================================================

_KEY_MAP: dict[str, tuple | None] = {
    "Jump":      ("space",),
    "Sprint":    ("left shift",),
    "Crouch":    ("c",),
    "Dodge":     ("left ctrl",),
    "Attack1":   None,           # mouse left  — handled below
    "Attack2":   None,           # mouse right — handled below
    "Interact":  ("e",),
    "Action1":   ("1",),
    "Action2":   ("2",),
    "Action3":   ("r",),
    "Action4":   ("f",),
    "Ability1":  ("q",),
    "Ability2":  ("g",),
    "LockOn":    None,           # mouse middle — handled below
    "Strafe":    ("tab",),
    "Holster1":  ("4",),
    "Holster2":  ("5",),
    "Holster3":  ("6",),
    "Inventory": ("i",),
}


def keypress_send_action(action_data: dict):
    """Execute an action via pyautogui keypresses (fallback for keypress mode)."""
    import pyautogui

    action = action_data.get("action", "wait")
    hold   = float(action_data.get("hold", 0.3))

    if action in ("wait", "stop"):
        return

    if action == "move":
        x, y = float(action_data.get("x", 0)), float(action_data.get("y", 0))
        keys = []
        if y >  0.3: keys.append("w")
        if y < -0.3: keys.append("s")
        if x < -0.3: keys.append("a")
        if x >  0.3: keys.append("d")
        for k in keys: pyautogui.keyDown(k)
        time.sleep(hold)
        for k in keys: pyautogui.keyUp(k)
        return

    if action == "Attack1": pyautogui.click(button="left");   return
    if action == "Attack2": pyautogui.click(button="right");  return
    if action == "LockOn":  pyautogui.click(button="middle"); return

    keys = _KEY_MAP.get(action)
    if keys:
        for k in keys: pyautogui.keyDown(k)
        time.sleep(hold)
        for k in keys: pyautogui.keyUp(k)
    else:
        print(f"  [!] keypress mode: no mapping for '{action}' — add it to _KEY_MAP")


# ==============================================================================
# LLM DECISION MAKING
# ==============================================================================

def build_system_prompt() -> str:
    actions = get_actions_dict()
    actions_list = "\n".join(
        f'- "{name}" — {info["description"]}'
        for name, info in actions.items()
    )
    return SYSTEM_PROMPT.format(actions_list=actions_list)


def ask_llm(client, b64_image, game_state, history) -> str:
    """Send screenshot + state to Claude and get an action as raw text."""
    text = "What do you see? What action should the cat take next?"
    if game_state:
        text += f"\n\nCurrent game state: {json.dumps(game_state)}"

    user_content = [
        {"type": "image",
         "source": {"type": "base64", "media_type": "image/png", "data": b64_image}},
        {"type": "text", "text": text},
    ]

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=300,
        system=build_system_prompt(),
        messages=(history + [{"role": "user", "content": user_content}])[-10:],
    )
    return response.content[0].text


def parse_action(response_text: str) -> dict:
    """Extract a JSON action object from LLM response text."""
    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        pass

    match = re.search(r'\{[^{}]*\}', response_text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    print(f"  [!] Could not parse action: {response_text[:120]}")
    return {"action": "wait", "reason": "parse error"}


# ==============================================================================
# TEST MODE
# ==============================================================================

def countdown(seconds: int, message: str = "Starting in"):
    """Print a countdown so the user has time to switch to the Unity window."""
    for i in range(seconds, 0, -1):
        print(f"\r  {message} {i}s — switch to Unity now...  ", end="", flush=True)
        time.sleep(1)
    print(f"\r  Go!                                          ")


def run_test(focus_delay: int = 3):
    global _live_actions

    print("=" * 60)
    print("TEST MODE — AgentBridge connection check")
    print("=" * 60)

    # 1. Ping
    print("\n[1] Pinging AgentBridge...")
    if bridge_ping():
        print("    OK   AgentBridge is running.")
    else:
        print("    FAIL  Cannot reach AgentBridge at", BRIDGE_URL)
        print("    Make sure Unity is in Play mode with AgentBridge attached.")
        return

    # 2. Fetch + display real action names
    print("\n[2] Fetching registered actions from bridge...")
    _live_actions = fetch_live_actions()
    print(f"    OK   {_live_actions}")

    # Warn about any action in the test sequence that isn't registered
    button_actions = [a for a in _live_actions if a not in ("move", "stop", "wait")]
    if not button_actions:
        print("    WARNING: No button actions registered — only move/stop/wait available.")
        print("    Check that MInputLink has buttons configured in its action map.")

    # 3. Current state
    print("\n[3] Getting game state...")
    state_before = bridge_get_state()
    if state_before:
        pos = (state_before.get("posX", 0), state_before.get("posY", 0), state_before.get("posZ", 0))
        print(f"    OK   pos=({pos[0]:.2f}, {pos[1]:.2f}, {pos[2]:.2f})")
        print(f"    OK   state={state_before.get('activeState','?')}  "
              f"grounded={state_before.get('grounded','?')}  sprint={state_before.get('sprint','?')}")
    else:
        print("    FAIL  Could not fetch /state")
        return

    # 4. Movement test (always safe regardless of button names)
    print("\n[4] Movement test...")
    if focus_delay > 0:
        countdown(focus_delay, "Click the Unity window —")
    move_seq = [
        {"action": "move", "x": 0,  "y": 1,  "hold": 0.6},
        {"action": "move", "x": -1, "y": 0,  "hold": 0.4},
        {"action": "move", "x":  1, "y": 0,  "hold": 0.4},
        {"action": "move", "x": 0,  "y": -1, "hold": 0.4},
        {"action": "stop"},
    ]
    for i, act in enumerate(move_seq):
        label = f"move x={act.get('x',0)} y={act.get('y',0)}" if act["action"] == "move" else "stop"
        print(f"    [{i+1}] {label:30s}", end=" ", flush=True)
        result = bridge_send_action(act)
        print("OK" if result and result.get("ok") else "FAIL")
        time.sleep(act.get("hold", 0.3) + 0.15)

    # 5. Button test using real names from bridge
    if button_actions:
        print(f"\n[5] Button test ({min(3, len(button_actions))} of {len(button_actions)} buttons)...")
        for btn in button_actions[:3]:
            print(f"    {btn:30s}", end=" ", flush=True)
            result = bridge_send_action({"action": btn, "hold": 0.2})
            print("OK" if result and result.get("ok") else "FAIL")
            time.sleep(0.4)
    else:
        print("\n[5] Button test skipped — no button actions registered.")

    # 6. Compare positions
    print("\n[6] Checking movement delta...")
    state_after = bridge_get_state()
    if state_after and state_before:
        dx = state_after.get("posX", 0) - state_before.get("posX", 0)
        dz = state_after.get("posZ", 0) - state_before.get("posZ", 0)
        pos = (state_after.get("posX", 0), state_after.get("posY", 0), state_after.get("posZ", 0))
        print(f"    pos=({pos[0]:.2f}, {pos[1]:.2f}, {pos[2]:.2f})  dx={dx:.2f}  dz={dz:.2f}")
        if abs(dx) > 0.01 or abs(dz) > 0.01:
            print("\n    *** SUCCESS — the cat moved! ***")
        else:
            print("\n    *** WARNING — cat didn't move. Check Unity console for errors. ***")

    print(f"\n{'=' * 60}")
    print("Test complete. Next: python cat_agent.py --mode bridge")
    print("=" * 60)


# ==============================================================================
# MAIN AGENT LOOP
# ==============================================================================

def run_agent(mode: str, max_steps: int = 50, delay: float = 1.0, focus_delay: int = 3):
    global _live_actions
    import anthropic
    client = anthropic.Anthropic()

    print("=" * 60)
    print(f"CAT AGENT — mode={mode}  steps={max_steps}  delay={delay}s")
    print("=" * 60)

    if mode == "bridge":
        print("\nChecking AgentBridge...")
        if not bridge_ping():
            print("FAIL  Cannot reach AgentBridge at", BRIDGE_URL)
            sys.exit(1)
        _live_actions = fetch_live_actions()
        print(f"OK  AgentBridge connected. {len(_live_actions)} actions available.")
        if focus_delay > 0:
            countdown(focus_delay, "Click the Unity window —")
    else:
        # keypress mode — use the static known list
        _live_actions = list(_KNOWN_DESCRIPTIONS.keys())
        if focus_delay > 0:
            countdown(focus_delay, "Switch to your game window —")

    valid_actions = set(_live_actions)
    history = []

    for step in range(1, max_steps + 1):
        print(f"\n--- Step {step}/{max_steps} ---")

        try:
            b64 = capture_screen_b64()
        except Exception as e:
            print(f"  [!] Screen capture failed: {e}")
            time.sleep(delay)
            continue

        game_state = None
        if mode == "bridge":
            game_state = bridge_get_state()
            if game_state:
                pos = f"({game_state.get('posX',0):.1f}, {game_state.get('posY',0):.1f}, {game_state.get('posZ',0):.1f})"
                print(f"  [state] pos={pos}  state={game_state.get('activeState','?')}  "
                      f"grounded={game_state.get('grounded','?')}")

        try:
            response_text = ask_llm(client, b64, game_state, history)
            print(f"  [llm]   {response_text[:150]}")
        except Exception as e:
            print(f"  [!] LLM call failed: {e}")
            time.sleep(delay)
            continue

        action_data = parse_action(response_text)
        action_name = action_data.get("action", "wait")

        # Guard: if LLM hallucinated an action not in the registered list, skip it
        if action_name not in valid_actions:
            print(f"  [!] LLM sent unknown action '{action_name}' — skipping. Valid: {sorted(valid_actions)}")
            action_data = {"action": "wait", "reason": "invalid action from LLM"}

        print(f"  [act]   {action_data.get('action','?')}  reason={action_data.get('reason','?')}")

        if mode == "bridge":
            bridge_send_action(action_data)
        else:
            keypress_send_action(action_data)

        history.append({"role": "assistant", "content": response_text})
        if len(history) > 10:
            history = history[-10:]

        time.sleep(delay)

    print(f"\n{'=' * 60}")
    print("Agent finished.")


# ==============================================================================
# ENTRY POINT
# ==============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LLM Agent for Unity Cat Game")
    parser.add_argument("--mode",  choices=["bridge", "keypress", "test"],
                        default="test",
                        help="bridge=HTTP API | keypress=raw keys | test=connection check")
    parser.add_argument("--steps",       type=int,   default=50,  help="Max agent steps")
    parser.add_argument("--delay",       type=float, default=1.0, help="Seconds between steps")
    parser.add_argument("--focus-delay", type=int,   default=3,
                        help="Seconds to wait before sending actions (time to switch to Unity window)")
    args = parser.parse_args()

    if args.mode == "test":
        run_test(focus_delay=args.focus_delay)
    else:
        run_agent(args.mode, max_steps=args.steps, delay=args.delay, focus_delay=args.focus_delay)
