# Mewi — Behavioral Report Site

A hybrid Astro website that renders per-user behavioral analysis reports from game session logs.
Users interact with four AI cats (Mewi, Miso, Yuzu, Haru) in a Unity 3D fishing village;
their behavioral patterns are logged, processed, and visualized here as psychological trace reports.

---

## Concept

Inspired by attachment theory: cats respond unpredictably, revealing the user's
relational tendencies without self-report bias. Each report is a mirror held up by cats.

---

## Stack

| Layer        | Tool                              |
|--------------|-----------------------------------|
| Site         | [Astro](https://astro.build) hybrid output + Node adapter |
| Charts (UI)  | Chart.js 4 bundled by Astro/Vite  |
| Charts (PNG) | matplotlib + numpy (Python)       |
| Data pipeline| Python 3.10+                      |
| Fonts        | Shippori Mincho + Space Mono      |
| Deploy       | Node-capable host/container for remote S3-backed reports |

---

## Directory layout

```
mewi-report/
├── pipeline/
│   ├── raw_data/          ← raw JSON session logs from Unity backend
│   │   └── sessions/{userId}/{sessionId}.json
│   ├── report_overrides/  ← optional curated demo values, not Unity raw data
│   ├── user_info.json     ← display names / handles for report users
│   ├── processed_data/    ← report_{userId}.json (written by the backend)
│   ├── charts/output/     ← matplotlib PNGs, per user
│   └── scripts/
│       └── visualize.py   ← processed_data → chart PNGs (render-side only)
│
├── src/
│   ├── data/              ← processed JSONs copied here for Astro to read
│   ├── components/        ← Astro UI components
│   ├── layouts/Base.astro ← nav + theme toggle shell
│   ├── pages/
│   │   ├── index.astro
│   │   ├── 404.astro
│   │   └── user/report/[userId].astro
│   └── styles/global.css
│
├── public/
│   └── styles/global.css  ← CSS served as static file
│
└── .claude/CLAUDE.md      ← maintenance guide for future AI sessions
```

---

## Quick start

### 1. Install dependencies

```bash
npm install
uv sync          # creates .venv and installs matplotlib + numpy
```

### 2. Add raw session data

Drop one session JSON file into `pipeline/raw_data/sessions/{userId}/`.
FastAPI's `POST /api/v1/report/session` route writes this layout for Unity.
Each file is immutable raw data for one completed session:

```json
{
  "schema_version": "mewi.report.raw.v1",
  "user_id": "vanillasky_01",
  "source": { "app": "mewi-unity" },
  "session": {
    "session_id": "s1",
    "session_index": 1,
    "timestamp_start": "2026-05-23T14:00:00Z",
    "duration_seconds": 520,
    "events": []
  }
}
```

Processing is owned by the **attachment-report Lambda**. FastAPI stores raw
sessions and enqueues/no-ops depending on `MEWI_REPORT_PROCESSING_MODE`; it does
not build the processed report inline. This site is render-only. In local mode it
reads already-processed `report_*.json` files from `src/data/`; in remote mode it
fetches finished private-S3 reports through FastAPI's read gateway.

User-facing names live in `pipeline/user_info.json` (read by the backend
processor). Keep `user_id` stable for internal files, and set `display_name` /
`handle` for what appears in the report UI.

### 3. Render charts (optional)

Processed data is produced by the backend. Charts (matplotlib PNGs) are still
rendered here:

```bash
# Generate chart PNGs → pipeline/charts/output/{userId}/
uv run pipeline/scripts/visualize.py

# npm alias for the same:
npm run charts
```

> To regenerate processed data, run the backend ingestion (or call
> `app.services.report.process_report` directly in mewi-backend).

### 4. Develop locally

```bash
npm run dev
# → http://localhost:4321/user/report/{handle}
```

### 4b. View with Docker

```bash
docker compose up --build
# → http://localhost:4321
```

The viewer container bind-mounts `pipeline/processed_data/` into `src/data/`.
When the backend writes new `report_{userId}.json` files there, refresh the
index page to see the new reports without rebuilding the image.
If multiple reports share the same handle, the site keeps all of them visible
by assigning indexed routes such as `/user/report/vanillaSky00_1/` and
`/user/report/vanillaSky00_2/`.

### 5. Build and deploy

```bash
npm run build       # outputs to dist/
npm run preview     # preview the built site locally
```

The production report route is server-rendered, so deploy this as a Node app or
container, not as plain static files. The default Docker image builds the
standalone Astro server:

```bash
docker build -t mewi-report .
docker run --rm -p 4321:4321 \
  -e PUBLIC_REPORT_SOURCE=remote \
  -e REPORT_API_BASE=https://<your-fastapi-host> \
  mewi-report
```

Remote mode does not read S3 directly. The site calls FastAPI:

```text
GET /api/v1/report/me/attachment
Authorization: Bearer <report-read JWT>
```

FastAPI then reads `mewi-report-results-v0/results/{user_id}/attachment.json`
after checking the token. Required backend deploy env:

```text
MEWI_REPORT_RESULTS_BUCKET=mewi-report-results-v0
MEWI_REPORT_READ_JWT_SECRET=<shared signing secret>
AWS_REGION=ap-southeast-1
AWS_DEFAULT_REGION=ap-southeast-1
```

Open the deployed report with:

```text
https://<report-host>/report?token=<JWT-with-sub-user_id>
```

The older `/user/report/{handle}` directory remains the local/static demo path.

---

## Re-rendering a single chart

```bash
# Re-render only the radar chart for one user.
# --user can match either the internal user_id or the display name/handle.
uv run pipeline/scripts/visualize.py --user vanillaSky00 --chart radar

# Available chart keys:
#   trust_all       — all-cats trust overlay
#   radar           — hexagonal human action distribution
#   attention       — attention % per cat
#   attachment      — attachment profile bars
#   trust_mewi      — Mewi's trust arc
#   trust_bars_mewi — Mewi's trust signal bars
#   (replace 'mewi' with miso / yuzu / haru)
```

---

## Theme

The site ships with light and dark themes. The toggle is in the top-right nav.
User preference is persisted to `localStorage` under key `mewi-theme`.

---

## Adding a new user

1. Drop one or more `pipeline/raw_data/sessions/new_user/{session_id}.json` files.
2. Add `"new_user"` to `pipeline/user_info.json` with a `display_name` and optional `handle`.
3. Let the backend process it (it runs on ingest), or invoke
   `app.services.report.process_report` in mewi-backend to write
   `src/data/report_new_user.json`.
4. Rebuild the site — Astro picks up the new `src/data/report_new_user.json` automatically.
5. The new report is available from the index page. If its handle is unique,
   the route is `/user/report/{handle}`; duplicate handles are suffixed with
   `_1`, `_2`, and so on.

---

## Cat personas

Each cat has a MBTI-inspired persona that shapes how trust signals are derived:

| Cat  | Archetype | Key trait                              |
|------|-----------|----------------------------------------|
| Mewi | ISFJ      | Smell-led, reads place before moving   |
| Miso | ISFP      | Food-motivated, conservative effort    |
| Yuzu | ENTP      | Provocation-driven, tests reactions    |
| Haru | INFJ      | Reads mood, presence over contact      |

Persona metadata is encoded in the backend processor
(`mewi-backend/app/services/report/processor.py`, `CAT_META`).
