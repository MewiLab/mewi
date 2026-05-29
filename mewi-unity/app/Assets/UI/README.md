# Player Dashboard UI

Runtime overlay for player-facing cat relationship memory and completed game
progress.

## How to use

1. In Unity, choose `GameObject > UI > Player Dashboard`.
2. Or create an empty GameObject and add `PlayerDashboardUI`.
3. Press Play. The component creates its own `Canvas`, `CanvasScaler`, and
   transparent rounded dashboard widgets.
4. Press `Q` to open the dashboard. Press `Q` again to close it.

`PlayerDashboardToggleListener` uses Unity's Input System and calls
`PlayerDashboardUI.Toggle()`. The default fallback binding is `<Keyboard>/q`.
For production, create an Input Actions asset, add a `ToggleDashboard` button
action bound to `<Keyboard>/q`, and assign that action to `Toggle Action`.

`PlayerDashboardCursorController` shows and unlocks the mouse while the
dashboard is open, then applies the configured gameplay cursor state when the
dashboard closes. This keeps pointer behavior separate from dashboard layout.

The dashboard itself exposes `opened` and `closed` events, so other systems can
listen for UI state changes without polling.

The component uses sample content when its lists are empty. Turn off
`Use Sample Data When Empty` when wiring real game state.

The dashboard is rendered by a screen-space overlay canvas, so it stays fitted
to the game view even when the third-person camera follows the cat. Use
`Panel Margin` to tune its distance from the screen edges.

The default styling uses larger TextMeshPro sizes, stronger translucent
surfaces, and a dim overlay behind the panel so text stays readable over the
moving 3D scene.

## Mouse and cursor setup

- `PlayerDashboardUI` creates or upgrades the scene `EventSystem` with
  `InputSystemUIInputModule`, so mouse clicks and scroll wheel input work with
  the Input System.
- Assign a cursor texture to `PlayerDashboardCursorController > Dashboard
  Cursor Texture` to use a custom mouse icon in the dashboard.
- Import cursor textures as `Texture Type: Cursor`, disable mipmaps, and set
  the hotspot to the click point, usually `(0, 0)` for an arrow or the center
  for a crosshair.
- For third-person gameplay, the default gameplay state hides and locks the
  cursor. Set `Gameplay Cursor Visible`, `Gameplay Lock Mode`, and optional
  `Gameplay Cursor Texture` if your game wants a visible custom cursor outside
  the dashboard.

## Layout

- Left sidebar: player profile, square profile photo, and tab buttons.
- `Bondness With Cats`: scrollable horizontal rows, one row per cat. Each row
  has a clickable circular cat profile.
- `Task Completed`: scrollable rows with a clickable cover card for each
  completed item.

## Runtime data

Feed cat relationship data with:

```csharp
dashboard.SetRelationships(items);
```

Each `CatRelationshipDashboardItem` supports:

- `catId`
- `catName`
- `profilePhoto`
- `relationshipLabel`
- `trust`
- `bond`
- `description`
- `latestMemoryEpisode`
- `memoryEpisodes`
- `lastSeenLocation`

Feed completed game progress with:

```csharp
dashboard.SetCompletedItems(items);
```

Each `CompletedGameItem` supports:

- `taskId`
- `title`
- `category`
- `completedAt`
- `description`
- `coverImage`
