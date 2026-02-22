import os
import json
import asyncio
from pathlib import Path
from typing import Any, Dict, Optional, List

import httpx
import aiosqlite
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks, Body
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

# -----------------------------
# ENV
# -----------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")  # https://guurenko-ai.onrender.com
APIFREE_API_KEY = os.getenv("APIFREE_API_KEY", "").strip()
APIFREE_BASE_URL = os.getenv("APIFREE_BASE_URL", "https://api.skycoding.ai").strip().rstrip("/")

# ВАЖНО: Render Disk должен быть примонтирован на /var/data
DB_PATH = os.getenv("DB_PATH", "/var/data/app.db").strip()

# Секрет вебхука. У тебя в логах /telegram/webhook/hook
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "hook").strip()

# Админ(ы) — чтобы не упираться в лимиты/оплаты при тесте
ADMIN_TG_IDS = set()
for x in (os.getenv("ADMIN_TG_IDS", "") or "").replace(" ", "").split(","):
    if x.isdigit():
        ADMIN_TG_IDS.add(int(x))

# Бесплатные кредиты по умолчанию (чтобы не получать 402 Payment Required)
INITIAL_FREE = int(os.getenv("INITIAL_FREE", "9999"))

# Таймауты/поллинг для генераций
IMAGE_TIMEOUT_SEC = int(os.getenv("IMAGE_TIMEOUT_SEC", "3600"))
IMAGE_POLL_SEC = int(os.getenv("IMAGE_POLL_SEC", "5"))
VIDEO_TIMEOUT_SEC = int(os.getenv("VIDEO_TIMEOUT_SEC", "7200"))
VIDEO_POLL_SEC = int(os.getenv("VIDEO_POLL_SEC", "8"))
MUSIC_TIMEOUT_SEC = int(os.getenv("MUSIC_TIMEOUT_SEC", "3600"))
MUSIC_POLL_SEC = int(os.getenv("MUSIC_POLL_SEC", "5"))

# Дефолтные модели (можно менять в ENV)
DEFAULT_CHAT_MODEL = os.getenv("DEFAULT_CHAT_MODEL", "openai/gpt-5.2").strip()
GROK_CHAT_MODEL = os.getenv("GROK_CHAT_MODEL", "xai/grok-4").strip()

DEFAULT_IMAGE_MODEL = os.getenv("DEFAULT_IMAGE_MODEL", "google/nano-banana-pro").strip()
DEFAULT_VIDEO_MODEL = os.getenv("DEFAULT_VIDEO_MODEL", "klingai/kling-v2.6/pro/image-to-video").strip()
DEFAULT_MUSIC_MODEL = os.getenv("DEFAULT_MUSIC_MODEL", "mureka-ai/mureka-v8/generate-song").strip()

APIFREE_HTTP_TIMEOUT_SEC = int(os.getenv("APIFREE_HTTP_TIMEOUT_SEC", "180"))

# -----------------------------
# APP
# -----------------------------
app = FastAPI(title="Creator Mini App Backend", version="2.0.0")

# -----------------------------
# WEBAPP mount (ищем папку webapp где бы она ни лежала)
# -----------------------------
BASE_DIR = Path(__file__).resolve().parent  # .../app
CANDIDATES = [
    BASE_DIR / "webapp",
    BASE_DIR.parent / "webapp",
    BASE_DIR.parent / "web",
    BASE_DIR / "web",
]
WEBAPP_DIR = None
for p in CANDIDATES:
    if p.exists() and p.is_dir():
        WEBAPP_DIR = p
        break

if WEBAPP_DIR:
    app.mount("/webapp", StaticFiles(directory=str(WEBAPP_DIR), html=True), name="webapp")


# -----------------------------
# DB helpers
# -----------------------------
async def init_db():
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            tg_id INTEGER PRIMARY KEY,
            free_credits INTEGER NOT NULL DEFAULT 0,
            pro_credits INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            tg_id INTEGER NOT NULL,
            kind TEXT NOT NULL,          -- image/video/music
            status TEXT NOT NULL,        -- queued/running/done/error
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
        cur = await db.execute(
            "SELECT tg_id, free_credits, pro_credits FROM users WHERE tg_id=?",
            (tg_id,),
        )
        row = await cur.fetchone()
        await cur.close()

        if row:
            return {"tg_id": row[0], "free": row[1], "pro": row[2]}

        await db.execute(
            "INSERT INTO users(tg_id, free_credits, pro_credits) VALUES (?,?,?)",
            (tg_id, INITIAL_FREE, 0),
        )
        await db.commit()
        return {"tg_id": tg_id, "free": INITIAL_FREE, "pro": 0}


async def consume_credit(tg_id: int) -> bool:
    if tg_id in ADMIN_TG_IDS:
        return True

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT free_credits, pro_credits FROM users WHERE tg_id=?",
            (tg_id,),
        )
        row = await cur.fetchone()
        await cur.close()

        if not row:
            # создаём пользователя и пробуем ещё раз
            await get_or_create_user(tg_id)
            return True  # у нового будет INITIAL_FREE

        free, pro = int(row[0]), int(row[1])

        if pro > 0:
            await db.execute(
                "UPDATE users SET pro_credits = pro_credits - 1 WHERE tg_id=?",
                (tg_id,),
            )
            await db.commit()
            return True

        if free > 0:
            await db.execute(
                "UPDATE users SET free_credits = free_credits - 1 WHERE tg_id=?",
                (tg_id,),
            )
            await db.commit()
            return True

        return False
    async with aiosqlite.connect(DB_PATH) as db:
        row = await db.execute_fetchone("SELECT free_credits, pro_credits FROM users WHERE tg_id=?", (tg_id,))
        if not row:
            await get_or_create_user(tg_id)
            row = (INITIAL_FREE, 0)

        free, pro = row
        if pro > 0:
            await db.execute("UPDATE users SET pro_credits=pro_credits-1 WHERE tg_id=?", (tg_id,))
            await db.commit()
            return True
        if free > 0:
            await db.execute("UPDATE users SET free_credits=free_credits-1 WHERE tg_id=?", (tg_id,))
            await db.commit()
            return True
        return False


async def save_job(job_id: str, tg_id: int, kind: str, status: str, model: str, req: Dict[str, Any], res: Optional[Dict[str, Any]] = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        INSERT OR REPLACE INTO jobs(id, tg_id, kind, status, model, request_json, result_json, updated_at)
        VALUES(?,?,?,?,?,?,?, datetime('now'))
        """, (
            job_id, tg_id, kind, status, model,
            json.dumps(req, ensure_ascii=False),
            json.dumps(res or {}, ensure_ascii=False),
        ))
        await db.commit()


async def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, tg_id, kind, status, model, request_json, result_json FROM jobs WHERE id=?",
            (job_id,),
        )
        row = await cur.fetchone()
        await cur.close()

        if not row:
            return None

        return {
            "id": row[0],
            "tg_id": row[1],
            "kind": row[2],
            "status": row[3],
            "model": row[4],
            "request": json.loads(row[5] or "{}"),
            "result": json.loads(row[6] or "{}"),
        }


# -----------------------------
# API FREE client
# -----------------------------
def _apifree_headers() -> Dict[str, str]:
    if not APIFREE_API_KEY:
        raise HTTPException(status_code=500, detail="APIFREE_API_KEY не задан")
    return {"Authorization": f"Bearer {APIFREE_API_KEY}"}


async def apifree_post(endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{APIFREE_BASE_URL}{endpoint}"
    timeout = httpx.Timeout(APIFREE_HTTP_TIMEOUT_SEC)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(url, json=payload, headers=_apifree_headers())
        try:
            data = r.json()
        except Exception:
            data = {"raw": r.text}

    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail={"provider_error": True, "status": r.status_code, "resp": data})
    return data


# -----------------------------
# Models catalog (чтобы выпадашки НЕ были пустыми)
# Можно переопределить ENV: MODELS_JSON
# -----------------------------
DEFAULT_MODELS = {
    "chat": [
        {"id": DEFAULT_CHAT_MODEL, "name": "ChatGPT"},
        {"id": GROK_CHAT_MODEL, "name": "Grok"},
    ],
    "image": [
        {"id": DEFAULT_IMAGE_MODEL, "name": "Nano Banana"},
    ],
    "video": [
        {"id": DEFAULT_VIDEO_MODEL, "name": "Kling I2V"},
    ],
    "music": [
        {"id": DEFAULT_MUSIC_MODEL, "name": "Mureka V8"},
    ],
}


def get_models_catalog() -> Dict[str, Any]:
    raw = os.getenv("MODELS_JSON", "").strip()
    if not raw:
        return DEFAULT_MODELS
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    return DEFAULT_MODELS


# -----------------------------
# Startup
# -----------------------------
@app.on_event("startup")
async def _startup():
    await init_db()


# -----------------------------
# Routes: WEB
# -----------------------------
@app.get("/")
async def root():
    if WEBAPP_DIR:
        return RedirectResponse("/webapp/")
    return HTMLResponse("<h3>Backend is running. No webapp folder found.</h3>")


@app.get("/health")
async def health():
    return {"ok": True}


# -----------------------------
# Routes: MiniApp API
# -----------------------------
@app.get("/api/models")
async def api_models():
    return {"ok": True, "models": get_models_catalog()}


@app.get("/api/me")
async def api_me(tg_id: int):
    # ВАЖНО: раньше у тебя тут был 404 -> ломалось всё дальше
    u = await get_or_create_user(int(tg_id))
    return {"ok": True, **u}


@app.post("/api/chat")
async def api_chat(payload: Dict[str, Any] = Body(default={})):
    tg_id = int(payload.get("tg_id", 0))
    text = (payload.get("text") or "").strip()
    provider = (payload.get("provider") or "").strip().lower()
    model = (payload.get("model") or "").strip()

    if not tg_id or not text:
        raise HTTPException(status_code=400, detail="tg_id and text required")

    ok = await consume_credit(tg_id)
    if not ok:
        return JSONResponse({"ok": False, "error": "no_credits"}, status_code=402)

    if provider == "grok":
        model = model or GROK_CHAT_MODEL
    else:
        model = model or DEFAULT_CHAT_MODEL

    data = await apifree_post("/v1/chat/completions", {
        "model": model,
        "messages": [{"role": "user", "content": text}]
    })
    answer = None
    try:
        answer = data["choices"][0]["message"]["content"]
    except Exception:
        answer = json.dumps(data, ensure_ascii=False)

    return {"ok": True, "answer": answer, "model": model}


# ---- IMAGE (submit/result) ----
@app.post("/api/image/submit")
async def api_image_submit(payload: Dict[str, Any] = Body(default={})):
    tg_id = int(payload.get("tg_id", 0))
    prompt = (payload.get("prompt") or "").strip()
    model = (payload.get("model") or DEFAULT_IMAGE_MODEL).strip()

    if not tg_id or not prompt:
        raise HTTPException(status_code=400, detail="tg_id and prompt required")

    ok = await consume_credit(tg_id)
    if not ok:
        return JSONResponse({"ok": False, "error": "no_credits"}, status_code=402)

    create = await apifree_post("/v1/images/generations", {"model": model, "prompt": prompt})

    # В зависимости от провайдера это может быть url сразу или id/operation
    job_id = str(create.get("id") or create.get("job_id") or create.get("operation_id") or create.get("request_id") or "")
    url = create.get("url")

    if not job_id and url:
        job_id = f"img_{abs(hash(url))}"

    await save_job(job_id, tg_id, "image", "running", model, {"prompt": prompt}, create)

    return {"ok": True, "id": job_id, "status": "running", "url": url, "raw": create}


@app.get("/api/image/result/{job_id}")
async def api_image_result(job_id: str):
    job = await get_job(job_id)
    if not job:
        return {"ok": False, "status": "not_found"}

    # если url уже есть — готово
    raw = job["result"] or {}
    url = raw.get("url")
    if url:
        await save_job(job_id, job["tg_id"], "image", "done", job["model"], job["request"], raw)
        return {"ok": True, "status": "done", "url": url, "raw": raw}

    # иначе пробуем “подождать” через повторный запрос (если провайдер поддерживает)
    # тут универсально: просто возвращаем running
    return {"ok": True, "status": "running", "raw": raw}


# ---- VIDEO (submit/result) ----
@app.post("/api/video/submit")
async def api_video_submit(payload: Dict[str, Any] = Body(default={})):
    tg_id = int(payload.get("tg_id", 0))
    prompt = (payload.get("prompt") or "").strip()
    model = (payload.get("model") or DEFAULT_VIDEO_MODEL).strip()

    if not tg_id or not prompt:
        raise HTTPException(status_code=400, detail="tg_id and prompt required")

    ok = await consume_credit(tg_id)
    if not ok:
        return JSONResponse({"ok": False, "error": "no_credits"}, status_code=402)

    create = await apifree_post("/v1/videos/generations", {"model": model, "prompt": prompt})
    job_id = str(create.get("id") or create.get("job_id") or create.get("operation_id") or create.get("request_id") or "")
    url = create.get("url")
    if not job_id and url:
        job_id = f"vid_{abs(hash(url))}"

    await save_job(job_id, tg_id, "video", "running", model, {"prompt": prompt}, create)
    return {"ok": True, "id": job_id, "status": "running", "url": url, "raw": create}


@app.get("/api/video/result/{job_id}")
async def api_video_result(job_id: str):
    job = await get_job(job_id)
    if not job:
        return {"ok": False, "status": "not_found"}

    raw = job["result"] or {}
    url = raw.get("url")
    if url:
        await save_job(job_id, job["tg_id"], "video", "done", job["model"], job["request"], raw)
        return {"ok": True, "status": "done", "url": url, "raw": raw}
    return {"ok": True, "status": "running", "raw": raw}


# ---- MUSIC (submit/result) ----
@app.post("/api/music/submit")
async def api_music_submit(payload: Dict[str, Any] = Body(default={})):
    tg_id = int(payload.get("tg_id", 0))
    lyrics = (payload.get("lyrics") or "").strip()
    style = (payload.get("style") or "").strip()
    model = (payload.get("model") or DEFAULT_MUSIC_MODEL).strip()

    if not tg_id or not lyrics:
        raise HTTPException(status_code=400, detail="tg_id and lyrics required")

    ok = await consume_credit(tg_id)
    if not ok:
        return JSONResponse({"ok": False, "error": "no_credits"}, status_code=402)

    req = {"model": model, "lyrics": lyrics}
    if style:
        req["style"] = style

    create = await apifree_post("/v1/music/generations", req)

    job_id = str(create.get("id") or create.get("job_id") or create.get("operation_id") or create.get("request_id") or "")
    url = create.get("url")
    if not job_id and url:
        job_id = f"mus_{abs(hash(url))}"

    await save_job(job_id, tg_id, "music", "running", model, req, create)
    return {"ok": True, "id": job_id, "status": "running", "url": url, "raw": create}


@app.get("/api/music/result/{job_id}")
async def api_music_result(job_id: str):
    job = await get_job(job_id)
    if not job:
        return {"ok": False, "status": "not_found"}

    raw = job["result"] or {}
    url = raw.get("url")
    if url:
        await save_job(job_id, job["tg_id"], "music", "done", job["model"], job["request"], raw)
        return {"ok": True, "status": "done", "url": url, "raw": raw}
    return {"ok": True, "status": "running", "raw": raw}


# -----------------------------
# Telegram helpers
# -----------------------------
async def tg_send_message(chat_id: int, text: str, reply_markup: Optional[Dict[str, Any]] = None):
    if not BOT_TOKEN:
        return
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    async with httpx.AsyncClient(timeout=30) as client:
        await client.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json=payload)


async def tg_send_document(chat_id: int, file_url: str, caption: str = ""):
    if not BOT_TOKEN:
        return
    payload = {"chat_id": chat_id, "document": file_url}
    if caption:
        payload["caption"] = caption
    async with httpx.AsyncClient(timeout=30) as client:
        await client.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument", json=payload)


async def poll_and_send(chat_id: int, kind: str, job_id: str):
    # фоновой опрос, чтобы не ждать 690 сек в webhook
    timeout = {"image": IMAGE_TIMEOUT_SEC, "video": VIDEO_TIMEOUT_SEC, "music": MUSIC_TIMEOUT_SEC}.get(kind, 3600)
    poll = {"image": IMAGE_POLL_SEC, "video": VIDEO_POLL_SEC, "music": MUSIC_POLL_SEC}.get(kind, 5)

    start = asyncio.get_event_loop().time()
    while True:
        if asyncio.get_event_loop().time() - start > timeout:
            await tg_send_message(chat_id, "⏳ Не дождалась результата. Попробуй ещё раз или другую модель.")
            return

        job = await get_job(job_id)
        if job and (job["result"] or {}).get("url"):
            url = job["result"]["url"]
            # по твоей просьбе — отправляем как Document
            await tg_send_document(chat_id, url, caption="✅ Готово")
            return

        await asyncio.sleep(poll)


# -----------------------------
# Telegram webhook
# -----------------------------
@app.post(f"/telegram/webhook/{WEBHOOK_SECRET}")
async def telegram_webhook(req: Request, background: BackgroundTasks):
    update = await req.json()
    msg = update.get("message") or {}
    text = (msg.get("text") or "").strip()
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")

    if not chat_id:
        return {"ok": True}

    # /start -> кнопка MiniApp
    if text.startswith("/start"):
        miniapp_url = PUBLIC_BASE_URL or ""
        if not miniapp_url:
            # fallback — попытка взять из webhook url
            miniapp_url = "https://guurenko-ai.onrender.com"
        await tg_send_message(
            chat_id,
            "Привет! Открывай Mini App 👇",
            reply_markup={
                "inline_keyboard": [[
                    {"text": "Открыть Mini App", "web_app": {"url": f"{miniapp_url}/webapp/"}}
                ]]
            }
        )
        return {"ok": True}

    # (необязательно) если пользователь пишет прямо боту:
    # фото: ... / видео: ... / музыка: ...
    low = text.lower()
    if low.startswith("фото:"):
        prompt = text.split(":", 1)[1].strip()
        create = await api_image_submit({"tg_id": int(chat_id), "prompt": prompt, "model": DEFAULT_IMAGE_MODEL})
        job_id = create.get("id")
        await tg_send_message(chat_id, "🖼️ Приняла. Генерирую…")
        background.add_task(poll_and_send, chat_id, "image", job_id)
        return {"ok": True}

    if low.startswith("видео:"):
        prompt = text.split(":", 1)[1].strip()
        create = await api_video_submit({"tg_id": int(chat_id), "prompt": prompt, "model": DEFAULT_VIDEO_MODEL})
        job_id = create.get("id")
        await tg_send_message(chat_id, "🎬 Приняла. Генерирую…")
        background.add_task(poll_and_send, chat_id, "video", job_id)
        return {"ok": True}

    if low.startswith("музыка:"):
        lyrics = text.split(":", 1)[1].strip()
        create = await api_music_submit({"tg_id": int(chat_id), "lyrics": lyrics, "style": "", "model": DEFAULT_MUSIC_MODEL})
        job_id = create.get("id")
        await tg_send_message(chat_id, "🎵 Приняла. Генерирую…")
        background.add_task(poll_and_send, chat_id, "music", job_id)
        return {"ok": True}

    # иначе просто подсказка
    await tg_send_message(chat_id, "Открой Mini App через /start или напиши:\nфото: ...\nвидео: ...\nмузыка: ...")
    return {"ok": True}
