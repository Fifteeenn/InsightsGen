"""InsightsGen HTTP API. Thin layer over core/ so any frontend can use it.

Endpoints (all JSON unless noted)
  POST   /api/session                      -> {session_id}
  POST   /api/session/{sid}/files          multipart upload, 1..n files -> workspace summary
  POST   /api/session/{sid}/sample         load the bundled sample dataset -> workspace summary
  GET    /api/session/{sid}                -> workspace summary (tables, profiles, joins)
  DELETE /api/session/{sid}/tables/{name}  -> workspace summary
  DELETE /api/session/{sid}                -> {ok}
  GET    /api/session/{sid}/suggestions    -> {questions: [...]}
  POST   /api/session/{sid}/ask            {question} -> answer (narrative, sql, chart, rows...)
  GET    /api/health

Sessions are in-memory workspaces keyed by a random id, evicted after SESSION_TTL
seconds of inactivity. The built React app (frontend/dist) is served at "/".
"""
from __future__ import annotations

import os
import secrets
import time
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.charts import _json_value, chart_payload, choose_chart
from core.loader import UnsupportedFileError
from core.pipeline import Answer, Workspace

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DIR = ROOT / "sample_data"
SAMPLE_FILES = ["orders.csv", "customers.csv", "products.csv", "regional_targets.xlsx"]
DIST = ROOT / "frontend" / "dist"

SESSION_TTL = int(os.getenv("SESSION_TTL_SECONDS", "7200"))
MAX_SESSIONS = int(os.getenv("MAX_SESSIONS", "100"))
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "100")) * 1024 * 1024

app = FastAPI(title="InsightsGen API", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],   # Vite dev server
    allow_methods=["*"], allow_headers=["*"],
)


# ---------------------------------------------------------------- sessions
class _Session:
    def __init__(self) -> None:
        self.ws = Workspace()
        self.touched = time.time()
        self.messages: list[dict] = []


_sessions: dict[str, _Session] = {}


def _evict() -> None:
    now = time.time()
    stale = [k for k, s in _sessions.items() if now - s.touched > SESSION_TTL]
    for k in stale:
        _sessions.pop(k, None)
    if len(_sessions) > MAX_SESSIONS:
        for k in sorted(_sessions, key=lambda k: _sessions[k].touched)[: len(_sessions) - MAX_SESSIONS]:
            _sessions.pop(k, None)


def _get(sid: str) -> _Session:
    s = _sessions.get(sid)
    if s is None:
        raise HTTPException(404, "Session not found or expired. Start a new session.")
    s.touched = time.time()
    return s


# ---------------------------------------------------------------- serializers
def _summary(ws: Workspace) -> dict:
    return {
        "tables": [
            {
                "name": p.name, "display_name": p.display_name, "rows": p.rows,
                "columns": [asdict(c) for c in p.columns],
                "sample": p.sample, "warnings": p.warnings,
            }
            for p in ws.profiles
        ],
        "joins": [asdict(j) for j in ws.joins],
        "model": os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
    }


def _answer(a: Answer) -> dict:
    out = {
        "question": a.question, "title": a.title, "narrative": a.narrative, "explanation": a.explanation,
        "sql": a.sql, "chart_hint": a.chart_hint, "clarification": a.clarification, "error": a.error,
        "attempts": [asdict(x) for x in a.attempts], "truncated": a.truncated, "elapsed_ms": a.elapsed_ms,
        "healed": a.healed, "ok": a.ok, "columns": [], "rows": [], "row_count": 0, "chart": None,
    }
    if a.df is not None:
        df = a.df
        out["columns"] = [str(c) for c in df.columns]
        out["rows"] = [[_json_value(v) for v in row] for row in df.itertuples(index=False, name=None)]
        out["row_count"] = len(df)
        out["chart"] = chart_payload(df, choose_chart(df, a.chart_hint))
    return out


# ---------------------------------------------------------------- routes
class AskBody(BaseModel):
    question: str


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "sessions": len(_sessions), "model": os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")}


@app.post("/api/session")
def create_session() -> dict:
    _evict()
    sid = secrets.token_urlsafe(16)
    _sessions[sid] = _Session()
    return {"session_id": sid}


@app.get("/api/session/{sid}")
def get_session(sid: str) -> dict:
    s = _get(sid)
    return {**_summary(s.ws), "messages": s.messages}


@app.delete("/api/session/{sid}")
def delete_session(sid: str) -> dict:
    _sessions.pop(sid, None)
    return {"ok": True}


@app.post("/api/session/{sid}/files")
async def upload_files(sid: str, files: list[UploadFile] = File(...)) -> dict:
    s = _get(sid)
    payload: list[tuple[str, bytes]] = []
    for f in files:
        data = await f.read()
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"{f.filename} is larger than the {MAX_UPLOAD_BYTES // (1024*1024)} MB limit.")
        payload.append((f.filename or "upload.csv", data))
    try:
        added = s.ws.add_files(payload)
    except UnsupportedFileError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, f"Could not read file: {e}")
    return {**_summary(s.ws), "added": [t.name for t in added]}


@app.post("/api/session/{sid}/sample")
def load_sample(sid: str) -> dict:
    s = _get(sid)
    existing = {t.source_file for t in s.ws.tables}
    files = [(n, (SAMPLE_DIR / n).read_bytes()) for n in SAMPLE_FILES if n not in existing]
    added = s.ws.add_files(files) if files else []
    return {**_summary(s.ws), "added": [t.name for t in added]}


@app.delete("/api/session/{sid}/tables/{name}")
def remove_table(sid: str, name: str) -> dict:
    s = _get(sid)
    s.ws.remove_table(name)
    return _summary(s.ws)


@app.get("/api/session/{sid}/suggestions")
def suggestions(sid: str) -> dict:
    s = _get(sid)
    return {"questions": s.ws.suggestions()}


@app.post("/api/session/{sid}/ask")
def ask(sid: str, body: AskBody) -> dict:
    s = _get(sid)
    q = body.question.strip()
    if not q:
        raise HTTPException(400, "Question is empty.")
    if len(q) > 1000:
        raise HTTPException(400, "Question is too long.")
    result = _answer(s.ws.ask(q))
    s.messages.append(result)
    return result


# ---------------------------------------------------------------- static frontend
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        candidate = DIST / path
        if path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(DIST / "index.html")
