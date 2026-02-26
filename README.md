# Ledger System

A multi-user, desktop-first personal accounting system built with FastAPI, Jinja2, TailwindCSS, and SQLite.

## Features
- Multi-organization setup with admin, user, and read-only roles
- Transaction entry with categories, accounts, tags, and notes
- Filters, search, and CSV export
- Budgets with progress tracking
- Monthly and yearly reports

## Local Development

1. Create a virtual environment and install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Run the server:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

3. Open `http://localhost:8000` and register the first admin account.

## Docker

```bash
docker-compose up --build
```

The app will be available at `http://localhost:8000`.

## Environment Variables
- `SECRET_KEY`: session signing key (optional in development)

## Data Storage
SQLite database is stored at `data/app.db` by default. Mount the `data/` folder for persistence in Docker.
