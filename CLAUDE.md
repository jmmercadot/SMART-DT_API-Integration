# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a SIF-400 Digital Twin system - a full-stack web application that mirrors the SIF-400 Smart Factory assembly line (SMC SIFMES-400) in real time. The backend polls the real SIFMES-400 web API and the frontend visualizes per-station energy/power, compressed-air consumption, raw-material inventory, caps e-kanban, OEE, and alerts, with a natural-language chat assistant.

## Development Commands

### Backend (Python Flask)
```bash
cd backend
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py  # Starts on http://localhost:5001
```

By default the backend polls the real SIF-400 at `http://130.130.130.199/api` (requires the SIF-400 lab wireless network). To develop without the lab network, run the mock SIFMES API and point the backend at it:

```bash
python mock_sifmes_api.py                                  # mock API on http://localhost:8199/api
# Point the backend at the mock AND at a separate DB so mock data never mixes
# into the real research database (sif400.db):
SIF400_API_BASE=http://localhost:8199/api SIF400_DB=sif400_mock.db python app.py
```

The backend's database file is `SIF400_DB` (default `sif400.db`); the mock workflow and `.\start.ps1 -Mock` / `MOCK=1 ./start.sh` set it to `sif400_mock.db` so real lab data stays pristine.

Convenience scripts at the repo root:
- macOS/Linux (bash): `./start.sh` (backend + frontend; `MOCK=1 ./start.sh` also starts the mock and points the backend at it) and `./stop.sh`
- Windows (PowerShell): `.\start.ps1` (real SIF-400) or `.\start.ps1 -Mock` (mock), and `.\stop.ps1`. These always use `backend\venv\Scripts\python.exe`, so global-Python dependency gaps can't bite.

Windows/PowerShell gotchas (both bit us in practice):
- Bash-style `SIF400_API_BASE=... python app.py` does **not** set the variable in PowerShell — the backend silently stays pointed at the real SIF-400. Use `$env:SIF400_API_BASE = 'http://localhost:8199/api'; python app.py`, or just `.\start.ps1 -Mock`.
- Running the global `python` (e.g. `C:\Python314`) instead of the venv misses `requests` (`ModuleNotFoundError`). Activate the venv or use `backend\venv\Scripts\python.exe` / the `.ps1` scripts.

### Frontend (React)
```bash
cd frontend
npm install
npm start      # Starts on http://localhost:3000
npm run build  # Production build
npm test       # Run tests
```

### Database Management
- **Database file**: `backend/sif400.db` (SQLite, auto-created) — real lab data. Mock runs use `sif400_mock.db` (via `SIF400_DB`) so they never pollute it.
- **Reset database**: Delete the `.db` file and restart backend
- **Tables**: stations, energy_measurements, alerts, snapshots

## Architecture

### Data source: the SIFMES-400 API
Base URL `http://130.130.130.199/api` (only reachable on the SIF-400 lab network). All responses use the envelope `{"Success": bool, "Error": str|null, "Object": ...}`. Endpoints used (full docs at `{base}/help` on the device; captured samples in `api_probe_results*/`):
- `GET /api/checker` — connectivity probe
- `GET /api/ekanban` — remaining caps per feeder in SIF-405
- `GET /api/Inventory` — raw-material inventory per station (loaders, hoppers, feeders, pallets)
- `GET /api/performanceAnalytics?paOption={opt}&from={MM/dd/YYYY}&to={MM/dd/YYYY}` — opt ∈ AirAndEnergy | ProductionAndLogistics | OEE | Quality. Quirks (all handled in `sif400_client.py`/`collector.py`): slow on the device (needs a ~30s timeout); date slashes must stay unencoded (no %2F); **same-day ranges (from == to) answer Success=false** — for "today" data query a two-day window and read today's slice from the per-day buckets (labels are dd/MM/yyyy)
- NOT used deliberately: `databaseConnection` (refreshes the device DB — disruptive), `movService` (starts/stops the MES service), `warehouseStatus`/`deliveryNote`/`signatureImage` (stations not present on this testbed)

The API exposes **energy consumption**, not voltage/current. Per-station power shown in the UI is derived: Wh-total delta over a ~10-minute sliding window.

### Backend (`/backend/`)
- **`sif400_client.py`**: thin HTTP client for the SIFMES-400 API (`SIF400_API_BASE` env var overrides the base URL)
- **`collector.py`**: `SIF400Collector` — two background threads: a fast one (checker/ekanban/Inventory every 5s) and a slow one for performanceAnalytics (AirAndEnergy every 30s, OEE every 60s, 14-day history every 5min) so slow PA responses can't stall the fast feeds; derives power; writes `energy_measurements` rows and raw `snapshots`; tracks per-feed health (`feeds` in the connection snapshot, shown in the UI and chat when a feed fails); raises alerts (empty loaders/hoppers, low caps, power ceiling, API connection loss) — duplicates suppressed while an alert is open, and a dismissed alert is snoozed for 5 minutes before it can re-raise
- **`app.py`**: Flask REST API over the collected data (CORS-enabled)
- **`nlp_service.py`**: regex intent classification answering from SQLite (energy, power, air, caps, inventory, OEE, alerts, connection status); voltage/current questions get an explanation that the API reports energy instead
- **`mock_sifmes_api.py`**: mock of the real SIFMES-400 API for off-network development (port 8199); mimics envelope/schemas from the captured probes and simulates production

### Frontend (`/frontend/`)
- **`src/SIF400DigitalTwin.jsx`**: entire dashboard — station cards (power/energy + trend), measurement-history panel (SVG multi-station power chart with range selector + CSV export), line consumption panel (energy + air, 14-day bars), inventory panel, caps e-kanban, OEE panel (Today/7d/30d ranges; empty state when no production cycles — the device only computes OEE during MES-managed runs), dismissible alerts with per-alert-type troubleshooting tips (`ALERT_TIPS`), threshold config, chat; dark mode toggle (`sif400_theme` in localStorage, Tailwind `darkMode: 'class'`); panels are user-reorderable via hover arrows (order persisted in localStorage under `sif400_panel_layout`)
- **`public/issues/`**: data-driven common-issues documentation (issues.json + images) for the upcoming per-station troubleshooting panel; format documented in its README
- **React + Tailwind CSS** with lucide-react icons
- Polls backend: current-status/alerts every 3s, inventory/ekanban every 5s, performance every 30s

### Key API Endpoints (backend)
- `GET /api/current-status` - stations (power/energy/trend/status) + SIF-400 connection + line air/energy
- `GET /api/alerts`, `POST /api/alerts/{id}/resolve`
- `GET /api/ekanban`, `GET /api/inventory`, `GET /api/performance`
- `GET /api/history?range=1h|6h|24h|7d|all` - downsampled per-station power/energy series; `GET /api/history/export?range=...` - raw rows as CSV
- `GET /api/oee?days=N` - OEE for today (collector cache) or a wider window (queried on demand, 5-min cache)
- `GET|PUT /api/thresholds` - `caps_min`, `power_max_w`
- `POST /api/chat` - natural language queries

## Configuration

### Alert Thresholds (adjustable via UI or PUT /api/thresholds)
- **caps_min** (default 3): alert when a SIF-405 feeder has fewer caps
- **power_max_w** (default 500): alert when a station's derived average power exceeds this

### Station IDs
- SIFMES `StationID` 1/2/3/4 map to SIF-401, SIF-402, SIF-405, SIF-407 (`STATION_MAP` in collector.py and nlp_service.py; mirrored in the frontend)

### Development Ports
- Backend: 5001 (Flask); Frontend: 3000 (CRA); Mock SIFMES API: 8199

## Data Flow

1. **Collector thread** polls the SIFMES-400 API (or the mock)
2. **SQLite** stores stations, energy_measurements (history), alerts, and latest raw snapshots
3. **Frontend polls** backend APIs for live updates
4. **Chat interface** answers from the same stored data
5. **Alert system** reacts to real signals: inventory presence, cap counts, power ceiling, connection loss

## Testing

- Frontend tests: `npm test` (Jest/React Testing Library)
- No backend test suite currently configured
- Manual end-to-end testing: run `mock_sifmes_api.py` + backend + frontend, browse http://localhost:3000
- `probe_sif400.ps1` / `probe_sif400_round2.ps1`: discovery scripts run on the lab network; captured outputs live in `api_probe_results/` and `api_probe_results_round2/`

## Troubleshooting

- **Database issues**: Delete `sif400.db` to reset (required after schema changes)
- **Port conflicts**: Backend uses port 5001 to avoid macOS AirPlay conflicts on 5000; check for stale dev servers from other checkouts of this repo holding 5001/3000
- **"SIF-400 API: Disconnected" in the UI / panels not syncing**: the backend can't reach its data source. Check `GET /api/current-status` → `connection.api_base` and `connection.last_error`. If `api_base` is the real device and you're off the lab network, that's expected — connect to the lab network, or run the mock (`.\start.ps1 -Mock`). Empty panels here are a connectivity state, not a code bug.
- **Multiple backends fighting over port 5001**: on Windows a venv `python.exe` re-execs the base interpreter, so one `app.py` shows as two processes; leftover instances from a prior run can hold 5001 while a new one polls but can't bind, producing contradictory readings. `.\stop.ps1` clears them by command-line match; verify with `Get-NetTCPConnection -LocalPort 5001 -State Listen`.
- **Virtual environment**: Ensure `source venv/bin/activate` (Windows: `venv\Scripts\activate`) before running Python
