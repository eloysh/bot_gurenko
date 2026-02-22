import os
import json
import asyncio
from datetime import datetime
from typing import Any, Dict, Optional, List

import aiosqlite
import httpx
from fastapi import FastAPI, HTTPException, Request, Body
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles


# =========================
# ENV
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
# если не задано — будет работать и так, но лучше задать
if not PUBLIC_BASE_URL:
    PUBLIC_BASE_URL = "https://guurenko-ai.onrender.com"

APIFREE_API_KEY = os.getenv("APIFREE_API_KEY", "").strip()
APIFREE_BASE_URL = os.getenv("APIFREE_BASE_URL", "https://api.skycoding.ai").strip().rstrip("/")
APIFREE_HTTP_TIMEOUT_SEC = int(os.getenv("APIFREE_HTTP_TIMEOUT_SEC", "180"))

# Время ожидания задач
IMAGE_TIMEOUT_SEC = int(os.getenv("IMAGE_TIMEOUT_SEC", "3600"))
IMAGE_POLL_SEC = int(os.getenv("IMAGE_POLL_SEC", "5"))
VIDEO_TIMEOUT_SEC = int(os.getenv("VIDEO_TIMEOUT_SEC", "7200"))
VIDEO_POLL_SEC = int(os.getenv("VIDEO_POLL_SEC", "8"))
MUSIC_TIMEOUT_SEC = int(os.getenv("MUSIC_TIMEOUT_SEC", "1800"))
MUSIC_POLL_SEC = int(os.getenv("MUSIC_POLL_SEC", "5"))

# дефолт-модели (можно менять в ENV)
DEFAULT_CHAT_MODEL = os.getenv("DEFAULT_CHAT_MODEL", "openai/gpt-5.2")
GROK_CHAT_MODEL = os.getenv("GROK_CHAT_MODEL", "xai/grok-4")

DEFAULT_IMAGE_MODEL = os.getenv("DEFAULT_IMAGE_MODEL", "google/nano-banana-pro")
DEFAULT_VIDEO_MODEL = os.getenv("DEFAULT_VIDEO_MODEL", "klingai/kling-v2.6/pro/image-to-video")

# Для музыки — поставь корректную модель из API Free (название зависит от твоего аккаунта)
# Пример: "mureka-ai/mureka-v8/generate-song"
DEFAULT_MUSIC_MODEL = os.getenv("DEFAULT_MUSIC_MODEL", "mureka-ai/mureka-v8/generate-song")

# SQLite — для Render лучше /var/data + подключить Disk
DB_PATH = os.getenv("DB_PATH", "/var/data/app.db").strip()

# webapp
WEBAPP_DIR = os.path.join(os.path.dirname(__file__), "webapp")


# =========================
# APP
# =========================
app = FastAPI(title="Creator Kristina Mini App Backend", version="1.0.0")

# Важно: mount webapp только если папка существует — чтобы деплой не падал
if os.path.isdir(WEBAPP_DIR):
    app.mount("/webapp", StaticFiles(directory=WEBAPP_DIR, html=True), name="webapp")


# =========================
# DB helpers
# =========================
async def db_fetchone(db: aiosqlite.Connection, sql: str, params: tuple = ()) -> Optional[aiosqlite.Row]:
    cur = await db.execute(sql, params)
    row = await cur.fetchone()
    await cur.close()
    return row

async def db_fetchall(db: aiosqlite.Connection, sql: str, params: tuple = ()) -> List[aiosqlite.Row]:
    cur = await db.execute(sql, params)
    rows = await cur.fetchall()
    await cur.close()
    return rows

async def init_db():
    # создаём папку под sqlite
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # USERS
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                tg_id INTEGER PRIMARY KEY,
                free_credits INTEGER DEFAULT 999999,
                pro_credits INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)

        # MIGRATIONS (если база старая и колонок нет)
        cols = await db_fetchall(db, "PRAGMA table_info(users)")
        col_names = {c["name"] for c in cols} if cols else set()

        if "free_credits" not in col_names:
            await db.execute("ALTER TABLE users ADD COLUMN free_credits INTEGER DEFAULT 999999")
        if "pro_credits" not in col_names:
            await db.execute("ALTER TABLE users ADD COLUMN pro_credits INTEGER DEFAULT 0")
        if "created_at" not in col_names:
            await db.execute("ALTER TABLE users ADD COLUMN created_at TEXT")
        if "updated_at" not in col_names:
            await db.execute("ALTER TABLE users ADD COLUMN updated_at TEXT")

        # JOBS
        await db.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,                  -- image | video | music
                status TEXT NOT NULL,                -- queued | running | done | error
                model TEXT,
                request_json TEXT,
                result_json TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)

        await db.commit()


async def get_or_create_user(tg_id: int) -> Dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        row = await db_fetchone(db, "SELECT tg_id, free_credits, pro_credits FROM users WHERE tg_id=?", (tg_id,))
        if row:
            return {"tg_id": row["tg_id"], "free_credits": row["free_credits"], "pro_credits": row["pro_credits"]}

        await db.execute(
            "INSERT INTO users(tg_id, free_credits, pro_credits, created_at, updated_at) VALUES (?,?,?,?,?)",
            (tg_id, 999999, 0, datetime.utcnow().isoformat(), datetime.utcnow().isoformat()),
        )
        await db.commit()
        return {"tg_id": tg_id, "free_credits": 999999, "pro_credits": 0}


# =========================
# API FREE client
# =========================
async def apifree_post(endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if not APIFREE_API_KEY:
        raise HTTPException(status_code=500, detail="APIFREE_API_KEY не задан")

    url = f"{APIFREE_BASE_URL}{endpoint}"
    headers = {"Authorization": f"Bearer {APIFREE_API_KEY}"}

    timeout = httpx.Timeout(APIFREE_HTTP_TIMEOUT_SEC)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(url, json=payload, headers=headers)

        try:
            data = r.json()
        except Exception:
            data = {"raw": r.text}

    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail=data)

    return data


# =========================
# STARTUP
# =========================
@app.on_event("startup")
async def _startup():
    await init_db()
    # webhook ставим каждый запуск (можно отключить, если не нужно)
    if BOT_TOKEN:
        await set_telegram_webhook()


# =========================
# HEALTH / HOME
# =========================
@app.get("/health")
async def health():
    return "OK"

@app.get("/", response_class=HTMLResponse)
async def root():
    # чтобы всегда открывалось — даже если webapp не примонтился
    return f"""
    <html><body style="font-family:Arial">
      <h2>Backend работает ✅</h2>
      <p>Mini App: <a href="/webapp/">/webapp/</a></p>
      <p>Models: <a href="/api/models">/api/models</a></p>
    </body></html>
    """


# =========================
# MODELS (для выпадающих списков)
# =========================
@app.get("/api/models")
async def api_models():
    return {
        "chat": [
            {"id": DEFAULT_CHAT_MODEL, "title": "GPT (default)"},
            {"id": GROK_CHAT_MODEL, "title": "Grok"},
        ],
        "image": [
            {"id": DEFAULT_IMAGE_MODEL, "title": "Nano Banana Pro"},
        ],
        "video": [
            {"id": DEFAULT_VIDEO_MODEL, "title": "Kling image-to-video"},
        ],
        "music": [
            {"id": DEFAULT_MUSIC_MODEL, "title": "Music (default)"},
        ],
    }


# =========================
# ME (профиль пользователя для Mini App)
# =========================
@app.get("/api/me")
async def api_me(tg_id: int):
    u = await get_or_create_user(int(tg_id))
    return u


# =========================
# CHAT (Mini App)
# =========================
@app.post("/api/chat")
async def api_chat(body: Dict[str, Any] = Body(default={})):
    message = (body or {}).get("message", "")
    model = (body or {}).get("model") or DEFAULT_CHAT_MODEL

    if not message:
        raise HTTPException(status_code=400, detail="message пустой")

    payload = {"model": model, "messages": [{"role": "user", "content": message}]}
    data = await apifree_post("/v1/chat/completions", payload)

    text = None
    try:
        text = data["choices"][0]["message"]["content"]
    except Exception:
        text = None

    return {"model": model, "text": text, "raw": data}


# =========================
# JOBS (image/video/music) submit + result
# =========================
def _pick_job_id(resp: Dict[str, Any]) -> str:
    # Пытаемся вытащить любой id, который встречается у провайдеров
    for k in ["id", "task_id", "job_id", "request_id", "generation_id"]:
        v = resp.get(k)
        if isinstance(v, str) and v:
            return v
        if isinstance(v, int):
            return str(v)
    # иногда id лежит внутри data
    data = resp.get("data")
    if isinstance(data, dict):
        for k in ["id", "task_id", "job_id"]:
            v = data.get(k)
            if v:
                return str(v)
    # крайний случай
    return str(int(datetime.utcnow().timestamp() * 1000))


async def save_job(job_id: str, job_type: str, status: str, model: str, req: Dict[str, Any], res: Dict[str, Any]):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR REPLACE INTO jobs(id,type,status,model,request_json,result_json,updated_at)
               VALUES (?,?,?,?,?,?,?)""",
            (
                job_id,
                job_type,
                status,
                model,
                json.dumps(req, ensure_ascii=False),
                json.dumps(res, ensure_ascii=False),
                datetime.utcnow().isoformat(),
            ),
        )
        await db.commit()


async def load_job(job_id: str) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        row = await db_fetchone(db, "SELECT * FROM jobs WHERE id=?", (job_id,))
        if not row:
            return None
        return {
            "id": row["id"],
            "type": row["type"],
            "status": row["status"],
            "model": row["model"],
            "request": json.loads(row["request_json"] or "{}"),
            "result": json.loads(row["result_json"] or "{}"),
            "updated_at": row["updated_at"],
        }


def _extract_url(resp: Dict[str, Any]) -> Optional[str]:
    # частые форматы: {"url": "..."} или {"data":[{"url":"..."}]}
    if isinstance(resp.get("url"), str):
        return resp["url"]
    d = resp.get("data")
    if isinstance(d, list) and d:
        u = d[0].get("url")
        if isinstance(u, str):
            return u
    return None


@app.post("/api/image/submit")
async def api_image_submit(body: Dict[str, Any] = Body(default={})):
    prompt = (body or {}).get("prompt", "")
    model = (body or {}).get("model") or DEFAULT_IMAGE_MODEL
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt пустой")

    req = {"model": model, "prompt": prompt}
    create = await apifree_post("/v1/images/generations", req)

    job_id = _pick_job_id(create)
    url = _extract_url(create)

    status = "done" if url else "running"
    await save_job(job_id, "image", status, model, req, create)

    return {"job_id": job_id, "status": status, "url": url}


@app.get("/api/image/result/{job_id}")
async def api_image_result(job_id: str):
    job = await load_job(job_id)
    if not job:
        return {"job_id": job_id, "status": "unknown"}

    url = _extract_url(job["result"])
    if url:
        return {"job_id": job_id, "status": "done", "url": url}

    # Если провайдер поддерживает отдельный эндпоинт статуса — добавим попытку (не у всех есть!)
    # ТОЛЬКО пробуем, если есть ключ/база
    try:
        # популярный паттерн у некоторых провайдеров
        data = await apifree_post("/v1/jobs/result", {"id": job_id})
        await save_job(job_id, "image", "done" if _extract_url(data) else "running", job["model"], job["request"], data)
        url2 = _extract_url(data)
        return {"job_id": job_id, "status": "done" if url2 else "running", "url": url2, "raw": data}
    except Exception:
        return {"job_id": job_id, "status": job["status"], "raw": job["result"]}


@app.post("/api/video/submit")
async def api_video_submit(body: Dict[str, Any] = Body(default={})):
    prompt = (body or {}).get("prompt", "")
    model = (body or {}).get("model") or DEFAULT_VIDEO_MODEL
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt пустой")

    req = {"model": model, "prompt": prompt}
    create = await apifree_post("/v1/videos/generations", req)

    job_id = _pick_job_id(create)
    url = _extract_url(create)

    status = "done" if url else "running"
    await save_job(job_id, "video", status, model, req, create)
    return {"job_id": job_id, "status": status, "url": url}


@app.get("/api/video/result/{job_id}")
async def api_video_result(job_id: str):
    job = await load_job(job_id)
    if not job:
        return {"job_id": job_id, "status": "unknown"}

    url = _extract_url(job["result"])
    if url:
        return {"job_id": job_id, "status": "done", "url": url}

    try:
        data = await apifree_post("/v1/jobs/result", {"id": job_id})
        await save_job(job_id, "video", "done" if _extract_url(data) else "running", job["model"], job["request"], data)
        url2 = _extract_url(data)
        return {"job_id": job_id, "status": "done" if url2 else "running", "url": url2, "raw": data}
    except Exception:
        return {"job_id": job_id, "status": job["status"], "raw": job["result"]}


@app.post("/api/music/submit")
async def api_music_submit(body: Dict[str, Any] = Body(default={})):
    lyrics = (body or {}).get("lyrics", "")
    style = (body or {}).get("style", "")
    model = (body or {}).get("model") or DEFAULT_MUSIC_MODEL
    if not lyrics:
        raise HTTPException(status_code=400, detail="lyrics пустой")

    req: Dict[str, Any] = {"model": model, "lyrics": lyrics}
    if style:
        req["style"] = style

    # У музыки у провайдеров часто другой endpoint — но ты просила через API Free.
    # Если у твоего API Free music endpoint другой — скажи, я поправлю под фактический.
    create = await apifree_post("/v1/music/generations", req)

    job_id = _pick_job_id(create)
    url = _extract_url(create)

    status = "done" if url else "running"
    await save_job(job_id, "music", status, model, req, create)
    return {"job_id": job_id, "status": status, "url": url}


@app.get("/api/music/result/{job_id}")
async def api_music_result(job_id: str):
    job = await load_job(job_id)
    if not job:
        return {"job_id": job_id, "status": "unknown"}

    url = _extract_url(job["result"])
    if url:
        return {"job_id": job_id, "status": "done", "url": url}

    try:
        data = await apifree_post("/v1/jobs/result", {"id": job_id})
        await save_job(job_id, "music", "done" if _extract_url(data) else "running", job["model"], job["request"], data)
        url2 = _extract_url(data)
        return {"job_id": job_id, "status": "done" if url2 else "running", "url": url2, "raw": data}
    except Exception:
        return {"job_id": job_id, "status": job["status"], "raw": job["result"]}


# =========================
# TELEGRAM: webhook + /start
# =========================
async def tg_call(method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if not BOT_TOKEN:
        raise HTTPException(status_code=500, detail="BOT_TOKEN не задан")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(url, json=payload)
        return r.json()

async def set_telegram_webhook():
    hook = f"{PUBLIC_BASE_URL}/telegram/webhook/hook"
    await tg_call("setWebhook", {"url": hook})
    print(f"[startup] setWebhook -> {hook}")

@app.post("/telegram/webhook/hook")
async def telegram_webhook_hook(req: Request):
    update = await req.json()
    msg = (update.get("message") or {})
    text = (msg.get("text") or "").strip()
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")

    if not chat_id:
        return {"ok": True}

    if text.startswith("/start"):
        miniapp_url = f"{PUBLIC_BASE_URL}/webapp/"
        await tg_call("sendMessage", {
            "chat_id": chat_id,
            "text": "Привет! Открывай Mini App 👇",
            "reply_markup": {
                "inline_keyboard": [[
                    {"text": "Открыть Mini App", "web_app": {"url": miniapp_url}}
                ]]
            }
        })
        return {"ok": True}

    # простая подсказка
    await tg_call("sendMessage", {
        "chat_id": chat_id,
        "text": "Открой Mini App через /start — там есть Chat / Фото / Видео / Музыка."
    })
    return {"ok": True}


# =========================
# (optional) favicon
# =========================
@app.get("/favicon.ico")
async def favicon():
    return JSONResponse(status_code=204, content=None)
