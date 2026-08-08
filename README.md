# Khājā Byte — Backend API

Python/Flask API for the Khājā Byte canteen app. Serves the JSON API consumed by the Flutter app (web + Android). Data is stored in SQLite (`khajabyte.db`, auto-created on first run).

## Run
```bash
pip install -r requirements.txt
python3 app.py        # http://127.0.0.1:5001
```

## Deploy
- **Render** (production): service uses the `Procfile` → `gunicorn app:app`, Python 3.13 (`runtime.txt`). Auto-deploys on push to `main`.

## API overview
- `/api/auth/login` · `/api/auth/register` — auth (bearer token)
- `/api/menu` · `/api/orders` · `/api/bookings` · `/api/transactions`
- `/api/admin/*` — menu management, bookings, users, revenue, announcements

See the Flutter app repo (`khaja-byte-flutter`) for the client.
