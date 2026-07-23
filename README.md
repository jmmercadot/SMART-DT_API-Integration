# SIF-400 Digital Twin

A full-stack digital twin of the SIF-400 Smart Factory assembly line (SMC SIFMES-400).
The backend polls the real SIFMES-400 web API on the lab network and the dashboard
mirrors the line in real time: per-station energy and derived power, compressed-air
consumption, raw-material inventory, caps e-kanban, OEE, alerts with troubleshooting
tips, measurement history with CSV export, and a natural-language chat assistant.

![stack](https://img.shields.io/badge/backend-Flask%20%2B%20SQLite-blue)
![stack](https://img.shields.io/badge/frontend-React%20%2B%20Tailwind-cyan)

## Quick start

```bash
./start.sh          # starts backend (5001) + frontend (3000) against the real SIF-400
MOCK=1 ./start.sh   # same, but against the bundled mock API (no lab network needed)
./stop.sh           # stops everything
```

Or run the pieces manually:

```bash
# Backend (Python 3, Flask) - polls the real SIF-400 at http://130.130.130.199/api
cd backend
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py                                     # http://localhost:5001

# Off the lab network? Run the mock SIFMES API and point the backend at it:
python mock_sifmes_api.py                                   # http://localhost:8199/api
SIF400_API_BASE=http://localhost:8199/api python app.py

# Frontend (React)
cd frontend
npm install
npm start                                         # http://localhost:3000
```

## How it works

```
SIFMES-400 API  ──poll──>  collector.py  ──SQLite──>  Flask API  ──HTTP──>  React dashboard
(real device or mock)      (2 threads)    sif400.db   (app.py)              (SIF400DigitalTwin.jsx)
```

- `backend/sif400_client.py` — HTTP client for the SIFMES-400 API and its quirks
  (30s performanceAnalytics budget, unencoded date slashes, no same-day ranges)
- `backend/collector.py` — background polling, power derivation from energy deltas,
  per-feed health tracking, alert generation (inventory presence, low caps, power
  ceiling, connection loss)
- `backend/nlp_service.py` — chat assistant answering from the collected data
- `backend/mock_sifmes_api.py` — faithful mock of the device API for off-network work

Full architecture notes, endpoint list, API quirks, and troubleshooting live in
[CLAUDE.md](CLAUDE.md). Captured samples of the real device's API responses are in
`api_probe_results*/` and `Documentation/`.

## Contributing troubleshooting docs

Operator-facing troubleshooting documentation lives in
[frontend/public/issues/](frontend/public/issues/) (`issues.json` + images) — see its
README for the format. The dashboard renders it directly; no code changes needed.

For this above ^
I am currently working on a new panel that would offer troubleshooting advice for the end-user when executing orders on the SIF-400 (for there are a lot of them)
