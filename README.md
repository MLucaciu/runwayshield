# Runway Shield

Airport runway monitoring and protection system — HackTech Oradea.

## Prerequisites

- **Python 3.10+** — [python.org/downloads](https://www.python.org/downloads/)
- **Node.js 18+** — [nodejs.org](https://nodejs.org/)
- (Optional) [Docker](https://docs.docker.com/get-docker/) if you want to use the Dev Container

## Getting started

```bash
# Clone the repo (skip if you already have it)
git clone <repo-url>
cd runwayshield
```

### Option A — Run locally (no Docker)

#### 1. Install backend dependencies

```bash
cd backend
pip install -r requirements.txt
```

> On some systems you may need `pip3` instead of `pip`, or use a virtual environment:
> ```bash
> python -m venv venv
> source venv/bin/activate   # Linux / Mac
> venv\Scripts\activate      # Windows
> pip install -r requirements.txt
> ```

#### 2. Start the backend (Flask)

```bash
cd backend
python app.py
```

The API server starts on **http://localhost:8081**.
You can verify it works:

```bash
curl http://localhost:8081/api/status
```

#### 3. Install frontend dependencies

Open a **second** terminal:

```bash
cd frontend
npm install
```

#### 4. Start the frontend (React)

```bash
cd frontend
npm start
```

The React dev server starts on **http://localhost:3000**.
API requests are automatically proxied to the Flask backend.

#### 5. Open the app

Go to **http://localhost:3000** in your browser.

---

### Option B — Dev Container (Docker)

If you have Docker installed, you can skip all manual setup:

1. Open the project in VS Code / Cursor
2. Press `Ctrl+Shift+P` (or `Cmd+Shift+P` on Mac) → **"Dev Containers: Reopen in Container"**
3. The container builds automatically (Python 3.12 + Node 20) and installs all dependencies
4. Start the backend: `cd /workspace/backend && python app.py`
5. Start the frontend: `cd /workspace/frontend && npm start`
6. Open **http://localhost:3000**

---

## Running tests

```bash
# Backend tests
cd backend
pytest

# Frontend tests
cd frontend
npm test
```

## Project structure

```
.devcontainer/     Dev Container config (Docker)
backend/           Flask API (Python 3.12)
  app.py           Main server
  requirements.txt Python dependencies (flask, opencv, numpy, etc.)
  tests/           Pytest tests
frontend/          React UI
  src/             Components & styles
  public/          Static assets & favicon
models_testing/    ML model experiments
```

## Ports

| Service  | Port | URL                     |
|----------|------|-------------------------|
| Frontend | 3000 | http://localhost:3000    |
| Backend  | 8081 | http://localhost:8081    |
