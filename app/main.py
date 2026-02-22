import os
import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import httpx
import aiosqlite
from fastapi import FastAPI, HTTPException, Request, Body
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles


# =========================
# ENV
# =========================
def getenv(name: str, default: str = "") -> str:
    v = os.getenv(name, default)
    return v if v is not None else default


BOT_TOKEN = getenv("BOT_TOKEN", "").strip()
PUBLIC_BASE_URL = getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")  # https://guurenko-ai.onrender.com

APIFREE_API_KEY = getenv("APIFREE_API_KEY", "").strip()
APIFREE_BASE_URL = getenv("APIFREE_BASE_URL", "https://api.skycoding.ai").strip().rstrip("/")
APIFREE_HTTP_TIMEOUT_SEC = int(getenv("APIFREE_HTTP_TIMEOUT_SEC", "180"))

DB_PATH = getenv("DB_PATH", "/var/data/app.db")
INITIAL_FREE = int(getenv("INITIAL_FREE", "2"))

ADMIN_TG_IDS = set()
for x in getenv("ADMIN_TG_IDS", "").replace(" ", "").split(","):
    if x.strip().isdigit():
        ADMIN_TG_IDS.add(int(x.strip()))

BASE_DIR = os.path.dirname(__file__)
WEBAPP_DIR = os.path.join(BASE_DIR, "webapp")


# =========================
# MODELS
# =========================
DEFAULT_MODELS = {
    "chat": [
        {"id": "openai/gpt-5.2", "name": "GPT (OpenAI) — gpt-5.2", "paid": False},
        {"id": "xai/grok-4", "name": "Grok (xAI) — grok-4", "paid": False},
    ],
    "image": [
        {"id": "google/nano-banana-pro", "name": "Nano Banana Pro (Image)", "paid": False},
        {"id": "google/imagen-3", "name": "Imagen 3", "paid": True},
    ],
    "video": [
        {"id": "klingai/kling-v2.6/pro/image-to-video", "name": "Kling 2.6 Pro (I2V)", "paid": True},
        {"id": "google/veo-3.1/image-to-video", "name": "Veo 3.1 (I2V)", "paid": True},
    ],
    "music": [
        {"id": "mureka-ai/mureka-v8/generate-song", "name": "Mureka V8 (Song)", "paid": True},
        {"id": "suno/suno-v4", "name": "Suno v4 (Song)", "paid": True},
    ],
}


def load_models() -> Dict[str, List[Dict[str, Any]]]:
    raw = getenv("MODELS_JSON", "").strip()
    if not raw:
        return DEFAULT_MODELS
    try:
        data = json.loads(raw)
        out = {}
        for k in ["chat", "image", "video", "music"]:
            v = data.get(k)
            out[k] = v if isinstance(v, list) and v else DEFAULT_MODELS[k]
        return out
    except Exception:
        return DEFAULT_MODELS


MODELS = load_models()


# =========================
# APP
# =========================
app = FastAPI(title="Creator Mini App Backend", version="2.0.1")

# НЕ ПАДАЕМ если папки нет
if os.path.isdir(WEBAPP_DIR):
    app.mount("/webapp", StaticFiles(directory=WEBAPP_DIR, html=True), name="webapp")


# =========================
# DB helpers (aiosqlite compatible)
# =========================
async def db_connect() -> aiosqlite.Connection:
    d = os.path.dirname(DB_PATH)
    if d:
        os.makedirs(d, exist_ok=True)
    db = await aiosqlite.connect(DB_PATH)
    await db.execute("PRAGMA journal_mode=WAL;")
    await db.execute("PRAGMA foreign_keys=ON;")
    return db


async def db_fetchone(db: aiosqlite.Connection, sql: str, params: Tuple[Any, ...] = ()) -> Optional[Tuple]:
    cur = await db.execute(sql, params)
    row = await cur.fetchone()
    await cur.close()
    return row


async def db_fetchall(db: aiosqlite.Connection, sql: str, params: Tuple[Any, ...] = ()) -> List[Tuple]:
    cur = await db.execute(sql, params)
    rows = await cur.fetchall()
    await cur.close()
    return rows


async def ensure_users_schema(db: aiosqlite.Connection) -> None:
    """
    Миграция: если таблица users уже существует в старом формате,
    добавляем недостающие колонки free_credits/pro_credits.
    """
    # есть ли таблица
    row = await db_fetchone(db, "SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
    if not row:
        # создадим с нуля
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users(
                tg_id INTEGER PRIMARY KEY,
                free_credits INTEGER NOT NULL DEFAULT 0,
                pro_credits INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        return

    # проверяем колонки
    cols = await db_fetchall(db, "PRAGMA table_info(users)")
    col_names = {c[1] for c in cols}  # (cid, name, type, notnull, dflt_value, pk)

    if "free_credits" not in col_names:
        await db.execute("ALTER TABLE users ADD COLUMN free_credits INTEGER NOT NULL DEFAULT 0")

    if "pro_credits" not in col_names:
        await db.execute("ALTER TABLE users ADD COLUMN pro_credits INTEGER NOT NULL DEFAULT 0")

    if "created_at" not in col_names:
        # created_at необязателен, но добавим
        await db.execute("ALTER TABLE users ADD COLUMN created_at TEXT")


async def init_db() -> None:
    db = await db_connect()
    try:
        await ensure_users_schema(db)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS jobs(
                id TEXT PRIMARY KEY,
                tg_id INTEGER,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                model TEXT,
                provider_id TEXT,
                request_json TEXT,
                result_json TEXT,
                error_text TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
        await db.commit()
    finally:
        await db.close()


async def get_or_create_user(tg_id: int) -> Dict[str, Any]:
    db = await db_connect()
    try:
        # на всякий случай повторим миграцию (если кто-то удалил/сломал БД)
        await ensure_users_schema(db)

        row = await db_fetchone(db, "SELECT tg_id, free_credits, pro_credits FROM users WHERE tg_id=?", (tg_id,))
        if row:
            return {"tg_id": row[0], "free": int(row[1]), "pro": int(row[2])}

        await db.execute(
            "INSERT INTO users(tg_id, free_credits, pro_credits) VALUES (?,?,?)",
            (tg_id, INITIAL_FREE, 0),
        )
        await db.commit()
        return {"tg_id": tg_id, "free": INITIAL_FREE, "pro": 0}
    finally:
        await db.close()


async def consume_credit(tg_id: int) -> bool:
    if tg_id in ADMIN_TG_IDS:
        return True

    db = await db_connect()
    try:
        await ensure_users_schema(db)

        row = await db_fetchone(db, "SELECT free_credits, pro_credits FROM users WHERE tg_id=?", (tg_id,))
        if not row:
            await db.execute(
                "INSERT INTO users(tg_id, free_credits, pro_credits) VALUES (?,?,?)",
                (tg_id, INITIAL_FREE, 0),
            )
            await db.commit()
            return True

        free, pro = int(row[0]), int(row[1])

        if pro > 0:
            await db.execute("UPDATE users SET pro_credits=pro_credits-1 WHERE tg_id=?", (tg_id,))
            await db.commit()
            return True

        if free > 0:
            await db.execute("UPDATE users SET free_credits=free_credits-1 WHERE tg_id=?", (tg_id,))
            await db.commit()
            return True

        return False
    finally:
        await db.close()


# =========================
# API Free client
# =========================
def apifree_headers() -> Dict[str, str]:
    if not APIFREE_API_KEY:
        raise HTTPException(status_code=500, detail="APIFREE_API_KEY не задан")
    return {"Authorization": f"Bearer {APIFREE_API_KEY}"}


async def apifree_post(endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{APIFREE_BASE_URL}{endpoint}"
    timeout = httpx.Timeout(APIFREE_HTTP_TIMEOUT_SEC)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(url, json=payload, headers=apifree_headers())
        try:
            data = r.json()
        except Exception:
            data = {"raw": r.text}
    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail=data)
    return data


async def apifree_get(endpoint: str) -> Dict[str, Any]:
    url = f"{APIFREE_BASE_URL}{endpoint}"
    timeout = httpx.Timeout(APIFREE_HTTP_TIMEOUT_SEC)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.get(url, headers=apifree_headers())
        try:
            data = r.json()
        except Exception:
            data = {"raw": r.text}
    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail=data)
    return data


# =========================
# Startup
# =========================
@app.on_event("startup")
async def _startup() -> None:
    await init_db()

    # setWebhook (не критично)
    if BOT_TOKEN and PUBLIC_BASE_URL:
        try:
            hook = f"{PUBLIC_BASE_URL}/telegram/webhook/hook"
            async with httpx.AsyncClient(timeout=30) as client:
                await client.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
                    json={"url": hook},
                )
            print(f"[startup] setWebhook -> {hook}")
        except Exception as e:
            print("[startup] webhook set failed:", repr(e))


# =========================
# ROUTES
# =========================
@app.get("/health", response_class=PlainTextResponse)
async def health() -> str:
    return "OK"


@app.get("/", response_class=HTMLResponse)
async def root() -> str:
    if os.path.isdir(WEBAPP_DIR):
        return """
        <html><body style="font-family:Arial">
        <h3>Backend is running ✅</h3>
        <p>Mini App: <a href="/webapp/">/webapp/</a></p>
        </body></html>
        """
    return "<html><body><h3>Backend is running ✅</h3></body></html>"


@app.get("/api/models")
async def api_models() -> Dict[str, Any]:
    # фронту нужен именно такой формат
    return {"ok": True, "models": MODELS}


@app.get("/api/me")
async def api_me(tg_id: int) -> Dict[str, Any]:
    u = await get_or_create_user(int(tg_id))
    return {"ok": True, "user": u}


@app.post("/api/chat")
async def api_chat(body: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
    tg_id = body.get("tg_id")
    message = (body.get("message") or "").strip()
    model = (body.get("model") or "").strip() or MODELS["chat"][0]["id"]

    if not message:
        raise HTTPException(status_code=400, detail="message пустой")

    if tg_id is not None:
        tg_id = int(tg_id)
        ok = await consume_credit(tg_id)
        if not ok:
            return {"ok": False, "error": "no_credits"}

    # пример совместимого формата (если у провайдера OpenAI-like)
    payload = {"model": model, "messages": [{"role": "user", "content": message}]}
    data = await apifree_post("/v1/chat/completions", payload)

    text = None
    try:
        text = data["choices"][0]["message"]["content"]
    except Exception:
        text = data.get("text")

    return {"ok": True, "model": model, "text": text, "raw": data}


# ====== GENERATION submit/result ======
async def submit_generation(kind: str, model: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if kind == "image":
        ep = "/v1/images/generations"
    elif kind == "video":
        ep = "/v1/videos/generations"
    elif kind == "music":
        ep = "/v1/music/generations"
    else:
        raise HTTPException(status_code=400, detail="unknown kind")

    req = {"model": model, **payload}
    data = await apifree_post(ep, req)

    provider_id = (
        data.get("id")
        or data.get("task_id")
        or (data.get("data")[0].get("id") if isinstance(data.get("data"), list) and data["data"] else None)
    )

    url = data.get("url")
    if not url and isinstance(data.get("data"), list) and data["data"]:
        url = data["data"][0].get("url")

    return {"provider_id": provider_id, "url": url, "raw": data}


async def proxy_result(kind: str, provider_id: str) -> Dict[str, Any]:
    candidates: List[str] = []
    if kind == "image":
        candidates = [f"/v1/images/result/{provider_id}", f"/v1/images/{provider_id}"]
    elif kind == "video":
        candidates = [f"/v1/videos/result/{provider_id}", f"/v1/videos/{provider_id}"]
    elif kind == "music":
        candidates = [f"/v1/music/result/{provider_id}", f"/v1/music/{provider_id}"]

    last: Optional[Exception] = None
    for ep in candidates:
        try:
            return await apifree_get(ep)
        except Exception as e:
            last = e
    raise HTTPException(status_code=502, detail={"error": "provider_result_failed", "detail": str(last)})


@app.post("/api/image/submit")
async def api_image_submit(body: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
    tg_id = body.get("tg_id")
    prompt = (body.get("prompt") or "").strip()
    model = (body.get("model") or "").strip() or MODELS["image"][0]["id"]

    if not prompt:
        raise HTTPException(status_code=400, detail="prompt пустой")

    if tg_id is not None:
        tg_id = int(tg_id)
        ok = await consume_credit(tg_id)
        if not ok:
            return {"ok": False, "error": "no_credits"}

    res = await submit_generation("image", model, {"prompt": prompt, "image": body.get("image")})
    return {"ok": True, "model": model, **res}


@app.get("/api/image/result/{provider_id}")
async def api_image_result(provider_id: str) -> Dict[str, Any]:
    data = await proxy_result("image", provider_id)
    url = data.get("url")
    if not url and isinstance(data.get("data"), list) and data["data"]:
        url = data["data"][0].get("url")
    return {"ok": True, "url": url, "raw": data}


@app.post("/api/video/submit")
async def api_video_submit(body: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
    tg_id = body.get("tg_id")
    prompt = (body.get("prompt") or "").strip()
    model = (body.get("model") or "").strip() or MODELS["video"][0]["id"]

    if not prompt:
        raise HTTPException(status_code=400, detail="prompt пустой")

    if tg_id is not None:
        tg_id = int(tg_id)
        ok = await consume_credit(tg_id)
        if not ok:
            return {"ok": False, "error": "no_credits"}

    payload: Dict[str, Any] = {"prompt": prompt}
    if body.get("image"):
        payload["image"] = body.get("image")
    if body.get("images"):
        payload["images"] = body.get("images")

    res = await submit_generation("video", model, payload)
    return {"ok": True, "model": model, **res}


@app.get("/api/video/result/{provider_id}")
async def api_video_result(provider_id: str) -> Dict[str, Any]:
    data = await proxy_result("video", provider_id)
    url = data.get("url")
    if not url and isinstance(data.get("data"), list) and data["data"]:
        url = data["data"][0].get("url")
    return {"ok": True, "url": url, "raw": data}


@app.post("/api/music/submit")
async def api_music_submit(body: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
    tg_id = body.get("tg_id")
    lyrics = (body.get("lyrics") or "").strip()
    style = (body.get("style") or "").strip()
    model = (body.get("model") or "").strip() or MODELS["music"][0]["id"]

    if not lyrics:
        raise HTTPException(status_code=400, detail="lyrics пустой")

    if tg_id is not None:
        tg_id = int(tg_id)
        ok = await consume_credit(tg_id)
        if not ok:
            return {"ok": False, "error": "no_credits"}

    payload: Dict[str, Any] = {"lyrics": lyrics}
    if style:
        payload["style"] = style

    res = await submit_generation("music", model, payload)
    return {"ok": True, "model": model, **res}


@app.get("/api/music/result/{provider_id}")
async def api_music_result(provider_id: str) -> Dict[str, Any]:
    data = await proxy_result("music", provider_id)
    url = data.get("url")
    if not url and isinstance(data.get("data"), list) and data["data"]:
        url = data["data"][0].get("url")
    return {"ok": True, "url": url, "raw": data}


# =========================
# Telegram webhook
# =========================
async def tg_send_message(chat_id: int, text: str, reply_markup: Optional[Dict[str, Any]] = None) -> None:
    if not BOT_TOKEN:
        return
    payload: Dict[str, Any] = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    async with httpx.AsyncClient(timeout=30) as client:
        await client.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json=payload)


@app.post("/telegram/webhook/hook")
async def telegram_webhook_hook(req: Request) -> Dict[str, Any]:
    update = await req.json()
    message = update.get("message") or {}
    text = (message.get("text") or "").strip()
    chat = message.get("chat") or {}
    chat_id = chat.get("id")

    if not chat_id:
        return {"ok": True}

    if text.startswith("/start"):
        miniapp_url = (PUBLIC_BASE_URL + "/webapp/") if PUBLIC_BASE_URL else "/webapp/"
        await tg_send_message(
            chat_id,
            "Привет! Открывай Mini App 👇",
            reply_markup={
                "inline_keyboard": [[
                    {"text": "Открыть Mini App", "web_app": {"url": miniapp_url}}
                ]]
            }
        )
    return {"ok": True}
