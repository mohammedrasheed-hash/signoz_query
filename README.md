# SigNoz Query Builder

Turns a customer + product + environment (and an optional HAR file) into a
narrowed SigNoz log filter. HAR upload auto-extracts the error endpoint,
status code, and incident time window. When no HAR is given, the time you
pick in the UI is used instead.

## Layout
```
backend/    FastAPI app (reuses the pandas routing + HAR logic)
  main.py
  k8s.csv
  ec2_servers.csv
  dockernames.csv      (optional - add if you have it)
  requirements.txt
frontend/   React + Vite UI
```

## Run the backend
```bash
cd backend
python -m venv .venv && source .venv/bin/activate      # optional
pip install -r requirements.txt
uvicorn main:app --reload --port 8731
```
Backend runs at http://localhost:8731

## Run the frontend
```bash
cd frontend
npm install
npm run dev
```
Frontend runs at http://localhost:5173

## How time is handled
- **HAR uploaded** -> time window comes from the HAR (the error timestamp +/- 2 min).
- **No HAR** -> whatever you choose in the Time section is used:
  - Relative: Last 15 min / 1 hour / 6 hours / 24 hours
  - Absolute: start + end datetime (entered as UTC)
  - None: no time clause

## Two query outputs
- **Without time** - paste into SigNoz's filter bar, set the range in SigNoz's own time picker.
- **With time** - a single string with nanosecond `timestamp >= / <=` clauses, for SigNoz's ClickHouse/expression mode.

> Note: confirm which mode your SigNoz filter bar uses. If the nanosecond
> `timestamp` clause is rejected, use the "without time" query and set the
> range in the picker.

## Notes baked into routing
- ctix -> k8s first (poc vs prod chosen by cluster), else EC2 fallback.
- csap / cftr -> EC2 if the client is in ec2_servers.csv, else namespace + body contains.
- csol -> EC2. co-island / csap-webapp -> fixed namespace/container + body contains.
- `k8s.namespace.name` may warn as ambiguous in SigNoz; if a query returns
  nothing, qualify it as `resource.k8s.namespace.name`.

  backend:  python3 -m uvicorn main:app --reload --port 8731
  frontend:  npm run dev
