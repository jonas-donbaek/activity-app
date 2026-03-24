# Strava Running Coach

Personal AI running coach web app that integrates with the Strava API. Built for half marathon training with real-time activity analysis, HR zone tracking, and race predictions.

## Features

- **Strava Sync** - OAuth2 integration with automatic activity import and stream analysis
- **HR Zone Analysis** - Zones synced directly from your Strava profile settings
- **Relative Effort** - hrTSS-based effort scoring using second-by-second HR data (same method as Strava)
- **Training Plan** - 12-week half marathon plan with daily workouts and auto-matching
- **Race Predictor** - Half marathon prediction using Riegel formula based on recent efforts
- **Pace Zones** - Time-in-zone distribution based on target race pace
- **Km Splits** - Per-kilometer breakdown with pace, HR, and elevation
- **Weekly Distance Chart** - Year-to-date running volume by calendar week
- **Recovery Status** - Readiness indicator based on recent training load
- **Coach Comments** - Automated feedback in Danish on each activity
- **Shoe Tracking** - Mileage tracking with retirement warnings

## Tech Stack

- **Backend**: Python 3.9+ / FastAPI / SQLAlchemy async
- **Database**: SQLite (aiosqlite)
- **Frontend**: Jinja2 templates / Pico CSS / Chart.js
- **API**: Strava API v3 (OAuth2 + Streams)

## Setup

### 1. Create a Strava API Application

Go to [https://www.strava.com/settings/api](https://www.strava.com/settings/api) and create an app:
- **Authorization Callback Domain**: `localhost`

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment

```bash
cp .env.example .env
```

Edit `.env` with your Strava API credentials:

```
STRAVA_CLIENT_ID=your_client_id
STRAVA_CLIENT_SECRET=your_client_secret
SECRET_KEY=a_random_secret_key
```

### 4. Run the app

```bash
python -m uvicorn app.main:app --port 8000
```

Open [http://localhost:8000](http://localhost:8000) and connect your Strava account.

### 5. Sync HR zones

After connecting Strava, your HR zones are automatically synced on each activity sync. You can also manually sync zones:

```
POST /api/zones/sync
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/dashboard` | Main dashboard |
| POST | `/api/activities/sync` | Sync activities from Strava |
| POST | `/api/activities/reanalyze` | Re-analyze all activities |
| GET | `/api/race-prediction` | Half marathon prediction |
| POST | `/api/zones/sync` | Sync HR zones from Strava |
| POST | `/api/plan/generate` | Generate training plan |
| GET | `/api/today` | Today's planned workout |

## Project Structure

```
app/
  config.py              # Settings (HR zones, race info)
  database.py            # SQLAlchemy async setup
  models.py              # Activity, Shoe, TrainingPlan models
  main.py                # FastAPI app entry point
  routers/
    api.py               # REST API endpoints
    auth.py              # Strava OAuth2 flow
    dashboard.py         # HTML page routes
    webhook.py           # Strava webhook handler
  services/
    activity_analyzer.py # HR zones, effort, splits, pace zones
    race_predictor.py    # Riegel-based race prediction
    strava_client.py     # Strava API client
    token_manager.py     # Encrypted token storage
    training_plan.py     # Plan generator
    weekly_summary.py    # Weekly stats & recovery
    plan_matcher.py      # Match activities to plan
    shoe_tracker.py      # Shoe mileage tracking
  templates/             # Jinja2 HTML templates
  static/                # CSS
```

## License

Private project.
