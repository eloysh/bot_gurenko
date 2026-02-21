import os
import json
import time
import asyncio
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
import aiosqlite
from fastapi import FastAPI, HTTPException, Request, Body
from fastapi.responses import RedirectResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

load_dotenv()

# ---------------- ENV ----------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/").strip()

APIFREE_API_KEY = os.getenv("APIFREE_API_KEY", "").strip()
APIFREE_BASE_URL = os.getenv("APIFREE_BASE_URL", "https://api.skycoding.ai").rstrip("/").strip()
APIFREE_HTTP_TIMEOUT_SEC = int(os.getenv("APIFREE_HTTP_TIMEOUT_SEC", "180"))

IMAGE_TIMEOUT_SEC = int(os.getenv("IMAGE_TIMEOUT_SEC", "3600"))   # 1 hour
IMAGE_POLL_SEC = int(os.getenv("IMAGE_POLL_SEC", "5"))

VIDEO_TIMEOUT_SEC = int(os.getenv("VIDEO_TIMEOUT_SEC", "7200"))   # 2 hours
VIDEO_POLL_SEC = int(os.getenv("VIDEO_POLL_SEC", "8"))

MUSIC_TIMEOUT_SEC = int(os.getenv("MUSIC_TIMEOUT_SEC", "7200"))
MUSIC_POLL_SEC = int(os.getenv("MUSIC_POLL_SEC", "8"))

DEFAULT_CHAT_MODEL = os.getenv("DEFAULT_CHAT_MODEL", "openai/gpt-5.2")
GROK_CHAT_MODEL = os.getenv("GROK_CHAT_MODEL", "xai/grok-4")
DEFAULT_IMAGE_MODEL = os.getenv("DEFAULT_IMAGE_MODEL", "google/nano-banana-pro")
DEFAULT_VIDEO_MODEL = os.getenv("DEFAULT_VIDEO_MODEL", "klingai/kling-v2.6/pro/image-to-video")
DEFAULT_MUSIC_MODEL = os.getenv("DEFAULT_MUSIC_MODEL", "mureka-ai/mureka-v8/generate-song")  # можно поменять на свою

DB_PATH = os.getenv("DB_PATH", "/var/data/app.db").strip()

# ---------------- APP ----------------
app = FastAPI(title="Creator Mini App Backend", version="1.0.0")

# ---- webapp static mounting (не падаем если нет папки) ----
BASE_DIR = Path(__file__).resolve().parent          # .../app
PROJECT_ROOT = BASE_DIR.parent                      # .../

CANDIDATES = [
    BASE_DIR / "webapp",
    PROJECT_ROOT / "webapp",
    PROJECT_ROOT / "web",
]
WEBAPP_DIR = next((p for p in CANDIDATES if p.exists() and p.is_dir()), None)

if WEBAPP_DIR:
    app.mount("/webapp", StaticFiles(directory=str(WEBAPP_DIR), html=True), name="webapp")

    @app.get("/", include_in_schema=False)
    async def root():
        return RedirectResponse(url="/webapp/")
else:
    @app.get("/", include_in_schema=False)
    async def root_missing():
        return PlainTextResponse(
            "WEBAPP folder not found. Create webapp/index.html (or app/webapp/index.html).",
            status_code=500
        )

# ---------------- DB ----------------
async def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,              -- image|video|music
            status TEXT NOT NULL,            -- queued|running|done|error
            tg_chat_id TEXT,
            tg_user_id TEXT,
            model TEXT,
            prompt TEXT,
            apifree_id TEXT,
            result_url TEXT,
            error TEXT,
            created_at INTEGER,
            updated_at INTEGER
        )
        """)
        await db.commit()

async def db_exec(sql: str, args: tuple = ()):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(sql, args)
        await db.commit()

async def db_fetchone(sql: str, args: tuple = ()):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(sql, args)
        row = await cur.fetchone()
        await cur.close()
        return row

# ---------------- HELPERS ----------------
def now_ts() -> int:
    return int(time.time())

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

    # ВАЖНО: 402 Payment Required — это не “ошибка кода”, а платная модель/лимит
    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail=data)

    return data

async def apifree_get(endpoint: str) -> Dict[str, Any]:
    if not APIFREE_API_KEY:
        raise HTTPException(status_code=500, detail="APIFREE_API_KEY не задан")

    url = f"{APIFREE_BASE_URL}{endpoint}"
    headers = {"Authorization": f"Bearer {APIFREE_API_KEY}"}
    timeout = httpx.Timeout(APIFREE_HTTP_TIMEOUT_SEC)

    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.get(url, headers=headers)

    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text}

    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail=data)

    return data

async def tg_call(method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if not BOT_TOKEN:
        return {"ok": False, "error": "BOT_TOKEN missing"}

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(url, json=payload)
    try:
        return r.json()
    except Exception:
        return {"ok": False, "raw": r.text}

async def tg_send_text(chat_id: str, text: str):
    await tg_call("sendMessage", {"chat_id": chat_id, "text": text})

async def tg_send_photo(chat_id: str, photo_url: str, caption: Optional[str] = None):
    payload = {"chat_id": chat_id, "photo": photo_url}
    if caption:
        payload["caption"] = caption
    await tg_call("sendPhoto", payload)

async def tg_send_video(chat_id: str, video_url: str, caption: Optional[str] = None):
    payload = {"chat_id": chat_id, "video": video_url}
    if caption:
        payload["caption"] = caption
    await tg_call("sendVideo", payload)

async def tg_send_audio(chat_id: str, audio_url: str, caption: Optional[str] = None):
    payload = {"chat_id": chat_id, "audio": audio_url}
    if caption:
        payload["caption"] = caption
    await tg_call("sendAudio", payload)

# ---------------- POLLING LOGIC ----------------
def extract_url_from_apifree_response(data: Dict[str, Any]) -> Optional[str]:
    # Поддерживаем разные форматы
    if isinstance(data.get("url"), str) and data["url"].startswith("http"):
        return data["url"]

    d = data.get("data")
    if isinstance(d, list) and d:
        u = d[0].get("url")
        if isinstance(u, str) and u.startswith("http"):
            return u

    # Иногда result лежит глубже
    for k in ["result", "output", "file", "media"]:
        v = data.get(k)
        if isinstance(v, dict):
            u = v.get("url")
            if isinstance(u, str) and u.startswith("http"):
                return u
        if isinstance(v, str) and v.startswith("http"):
            return v

    return None

def extract_id_from_apifree_response(data: Dict[str, Any]) -> Optional[str]:
    # Самые частые варианты: id / job_id
    for k in ["id", "job_id", "task_id"]:
        v = data.get(k)
        if isinstance(v, (str, int)):
            return str(v)
    # Иногда "data":[{"id":...}]
    d = data.get("data")
    if isinstance(d, list) and d:
        v = d[0].get("id")
        if isinstance(v, (str, int)):
            return str(v)
    return None

async def poll_job_to_telegram(job_id: int):
    # Достаём job
    row = await db_fetchone(
        "SELECT kind, tg_chat_id, model, prompt, apifree_id, created_at FROM jobs WHERE id=?",
        (job_id,)
    )
    if not row:
        return

    kind, tg_chat_id, model, prompt, apifree_id, created_at = row
    if not tg_chat_id:
        return

    if kind == "image":
        timeout_sec, poll_sec = IMAGE_TIMEOUT_SEC, IMAGE_POLL_SEC
        result_endpoint = f"/api/image/result/{apifree_id}"
    elif kind == "video":
        timeout_sec, poll_sec = VIDEO_TIMEOUT_SEC, VIDEO_POLL_SEC
        result_endpoint = f"/api/video/result/{apifree_id}"
    else:
        timeout_sec, poll_sec = MUSIC_TIMEOUT_SEC, MUSIC_POLL_SEC
        result_endpoint = f"/api/music/result/{apifree_id}"

    await tg_send_text(tg_chat_id, f"⏳ Запрос принят. Генерирую {kind}…")

    deadline = created_at + timeout_sec
    last_status_msg = 0

    while now_ts() < deadline:
        try:
            # Мы вызываем НАШ endpoint, который внизу оборачивает apifree result
            # но можно и напрямую apifree — так проще держать одну логику
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.get(f"{PUBLIC_BASE_URL}{result_endpoint}")
            data = r.json() if "application/json" in r.headers.get("content-type", "") else {"raw": r.text}

            # Ожидаем готовность: ищем url
            url = None
            if isinstance(data, dict):
                url = data.get("url") or extract_url_from_apifree_response(data)

            if url and isinstance(url, str) and url.startswith("http"):
                await db_exec(
                    "UPDATE jobs SET status=?, result_url=?, updated_at=? WHERE id=?",
                    ("done", url, now_ts(), job_id)
                )

                if kind == "image":
                    await tg_send_photo(tg_chat_id, url, caption="✅ Готово (Фото)")
                elif kind == "video":
                    await tg_send_video(tg_chat_id, url, caption="✅ Готово (Видео)")
                else:
                    await tg_send_audio(tg_chat_id, url, caption="✅ Готово (Музыка)")

                return

            # Периодически пингуем статус в чат, чтобы “не молчало”
            if now_ts() - last_status_msg > 120:
                last_status_msg = now_ts()
                await tg_send_text(tg_chat_id, "⏳ Всё ещё генерирую… (это может занять время)")

        except Exception as e:
            # Не валим процесс — подождём и продолжим
            await asyncio.sleep(poll_sec)
            continue

        await asyncio.sleep(poll_sec)

    # timeout
    await db_exec(
        "UPDATE jobs SET status=?, error=?, updated_at=? WHERE id=?",
        ("error", f"timeout after {timeout_sec}s", now_ts(), job_id)
    )
    await tg_send_text(
        tg_chat_id,
        f"⚠️ Не дождалась результата за {timeout_sec} сек.\n"
        f"Причины: длинная генерация / платная модель / лимиты.\n"
        f"Попробуй другую модель или повтори позже."
    )

# ---------------- TELEGRAM WEBHOOK ----------------
@app.post("/telegram/webhook/hook")
async def telegram_webhook(req: Request):
    update = await req.json()
    message = (update.get("message") or {})
    text = (message.get("text") or "").strip()
    chat = message.get("chat") or {}
    chat_id = chat.get("id")

    if not chat_id:
        return {"ok": True}

    # /start -> кнопка Mini App
    if text.startswith("/start"):
        miniapp_url = PUBLIC_BASE_URL + "/webapp/" if PUBLIC_BASE_URL else "https://guurenko-ai.onrender.com/webapp/"
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

    return {"ok": True}

# ---------------- API (Mini App) ----------------
@app.get("/health")
async def health():
    return {"ok": True}

@app.get("/api/models")
async def models():
    # Можно расширить список (и дальше он появится в UI)
    return {
        "chat": [DEFAULT_CHAT_MODEL, GROK_CHAT_MODEL],
        "image": [DEFAULT_IMAGE_MODEL, "google/nano-banana-pro", "google/nano-banana"],
        "video": [DEFAULT_VIDEO_MODEL, "klingai/kling-v2.6/pro/image-to-video"],
        "music": [DEFAULT_MUSIC_MODEL, "suno/suno-v4", "suno/suno-v3.5"]
    }

@app.post("/api/chat")
async def api_chat(body: Dict[str, Any]):
    message = (body or {}).get("message", "").strip()
    provider = (body or {}).get("provider")
    model = (body or {}).get("model") or DEFAULT_CHAT_MODEL
    if provider == "grok":
        model = GROK_CHAT_MODEL
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

# --- IMAGE submit/result ---
@app.post("/api/image/submit")
async def image_submit(body: Dict[str, Any]):
    prompt = (body or {}).get("prompt", "").strip()
    model = (body or {}).get("model") or DEFAULT_IMAGE_MODEL
    tg_chat_id = (body or {}).get("tg_chat_id")  # важно: Mini App должен передавать chat_id

    if not prompt:
        raise HTTPException(status_code=400, detail="prompt пустой")

    # 1) создать задачу в apifree
    create = await apifree_post("/v1/images/generations", {"model": model, "prompt": prompt})
    url = extract_url_from_apifree_response(create)
    apifree_id = extract_id_from_apifree_response(create) or create.get("id") or create.get("job") or ""

    # 2) сохранить job
    await db_exec(
        "INSERT INTO jobs(kind,status,tg_chat_id,model,prompt,apifree_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
        ("image", "queued", str(tg_chat_id) if tg_chat_id else None, model, prompt, str(apifree_id), now_ts(), now_ts())
    )
    row = await db_fetchone("SELECT last_insert_rowid()")
    job_id = int(row[0]) if row else 0

    # 3) если url уже есть — сразу в tg (если chat_id есть)
    if url and tg_chat_id:
        await db_exec("UPDATE jobs SET status=?, result_url=?, updated_at=? WHERE id=?",
                      ("done", url, now_ts(), job_id))
        await tg_send_photo(str(tg_chat_id), url, caption="✅ Готово (Фото)")
        return {"job_id": job_id, "status": "done", "url": url}

    # 4) иначе — в фоне ждём
    if tg_chat_id:
        asyncio.create_task(poll_job_to_telegram(job_id))

    return {"job_id": job_id, "status": "queued", "apifree_id": apifree_id}

@app.get("/api/image/result/{apifree_id}")
async def image_result(apifree_id: str):
    # Если у apifree есть специальный endpoint результата — укажи его тут.
    # Я оставляю универсально: часто это /v1/images/generations/{id}
    data = await apifree_get(f"/v1/images/generations/{apifree_id}")
    url = extract_url_from_apifree_response(data)
    return {"url": url, "raw": data}

# --- VIDEO submit/result ---
@app.post("/api/video/submit")
async def video_submit(body: Dict[str, Any]):
    prompt = (body or {}).get("prompt", "").strip()
    model = (body or {}).get("model") or DEFAULT_VIDEO_MODEL
    tg_chat_id = (body or {}).get("tg_chat_id")

    if not prompt:
        raise HTTPException(status_code=400, detail="prompt пустой")

    create = await apifree_post("/v1/videos/generations", {"model": model, "prompt": prompt})
    url = extract_url_from_apifree_response(create)
    apifree_id = extract_id_from_apifree_response(create) or ""

    await db_exec(
        "INSERT INTO jobs(kind,status,tg_chat_id,model,prompt,apifree_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
        ("video", "queued", str(tg_chat_id) if tg_chat_id else None, model, prompt, str(apifree_id), now_ts(), now_ts())
    )
    row = await db_fetchone("SELECT last_insert_rowid()")
    job_id = int(row[0]) if row else 0

    if url and tg_chat_id:
        await db_exec("UPDATE jobs SET status=?, result_url=?, updated_at=? WHERE id=?",
                      ("done", url, now_ts(), job_id))
        await tg_send_video(str(tg_chat_id), url, caption="✅ Готово (Видео)")
        return {"job_id": job_id, "status": "done", "url": url}

    if tg_chat_id:
        asyncio.create_task(poll_job_to_telegram(job_id))

    return {"job_id": job_id, "status": "queued", "apifree_id": apifree_id}

@app.get("/api/video/result/{apifree_id}")
async def video_result(apifree_id: str):
    data = await apifree_get(f"/v1/videos/generations/{apifree_id}")
    url = extract_url_from_apifree_response(data)
    return {"url": url, "raw": data}

# --- MUSIC submit/result ---
@app.post("/api/music/submit")
async def music_submit(body: Dict[str, Any]):
    lyrics = (body or {}).get("lyrics", "").strip()
    style = (body or {}).get("style", "").strip()
    model = (body or {}).get("model") or DEFAULT_MUSIC_MODEL
    tg_chat_id = (body or {}).get("tg_chat_id")

    if not lyrics:
        raise HTTPException(status_code=400, detail="lyrics пустой")

    payload = {"model": model, "lyrics": lyrics}
    if style:
        payload["style"] = style

    create = await apifree_post("/v1/music/generations", payload)
    url = extract_url_from_apifree_response(create)
    apifree_id = extract_id_from_apifree_response(create) or ""

    await db_exec(
        "INSERT INTO jobs(kind,status,tg_chat_id,model,prompt,apifree_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
        ("music", "queued", str(tg_chat_id) if tg_chat_id else None, model, lyrics[:5000], str(apifree_id), now_ts(), now_ts())
    )
    row = await db_fetchone("SELECT last_insert_rowid()")
    job_id = int(row[0]) if row else 0

    if url and tg_chat_id:
        await db_exec("UPDATE jobs SET status=?, result_url=?, updated_at=? WHERE id=?",
                      ("done", url, now_ts(), job_id))
        await tg_send_audio(str(tg_chat_id), url, caption="✅ Готово (Музыка)")
        return {"job_id": job_id, "status": "done", "url": url}

    if tg_chat_id:
        asyncio.create_task(poll_job_to_telegram(job_id))

    return {"job_id": job_id, "status": "queued", "apifree_id": apifree_id}

@app.get("/api/music/result/{apifree_id}")
async def music_result(apifree_id: str):
    data = await apifree_get(f"/v1/music/generations/{apifree_id}")
    url = extract_url_from_apifree_response(data)
    return {"url": url, "raw": data}

# ---------------- STARTUP ----------------
@app.on_event("startup")
async def startup():
    await init_db()

    # setWebhook (если задан PUBLIC_BASE_URL)
    if BOT_TOKEN and PUBLIC_BASE_URL:
        try:
            await tg_call("setWebhook", {"url": f"{PUBLIC_BASE_URL}/telegram/webhook/hook"})
        except Exception:
            pass
            from fastapi import Body

@app.get("/api/me")
async def api_me(tg_id: str):
    # Минимально — чтобы фронт не падал.
    # Если хочешь баланс/PRO — добавим позже.
    return {"tg_id": tg_id, "free": 2, "pro": 0}

@app.post("/api/chat")
async def api_chat_compat(body: Dict[str, Any] = Body(default={})):
    # Совместимость: фронт может слать message/text/prompt
    message = (body.get("message") or body.get("text") or body.get("prompt") or "").strip()
    provider = body.get("provider")
    model = body.get("model") or DEFAULT_CHAT_MODEL
    if provider == "grok":
        model = GROK_CHAT_MODEL

    if not message:
        # Чтобы было понятно в UI, почему 400
        raise HTTPException(status_code=400, detail="Пустое сообщение: ожидаю поле message (или text/prompt)")

    payload = {"model": model, "messages": [{"role": "user", "content": message}]}
    data = await apifree_post("/v1/chat/completions", payload)

    text = None
    try:
        text = data["choices"][0]["message"]["content"]
    except Exception:
        pass

    return {"model": model, "text": text, "raw": data}

@app.post("/api/image/submit")
async def image_submit_compat(body: Dict[str, Any] = Body(default={})):
    # Совместимость: фронт может слать prompt/text
    prompt = (body.get("prompt") or body.get("text") or body.get("message") or "").strip()
    model = body.get("model") or DEFAULT_IMAGE_MODEL

    # chat_id может не приходить — тогда только вернуть job_id/url в UI
    tg_chat_id = body.get("tg_chat_id") or body.get("chat_id")

    if not prompt:
        raise HTTPException(status_code=400, detail="prompt пустой")

    create = await apifree_post("/v1/images/generations", {"model": model, "prompt": prompt})

    # быстрый вариант: если апи сразу отдаёт url — вернём его в UI
    url = extract_url_from_apifree_response(create)
    apifree_id = extract_id_from_apifree_response(create) or ""

    # сохраним job
    await db_exec(
        "INSERT INTO jobs(kind,status,tg_chat_id,model,prompt,apifree_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
        ("image", "queued", str(tg_chat_id) if tg_chat_id else None, model, prompt, str(apifree_id), now_ts(), now_ts())
    )
    row = await db_fetchone("SELECT last_insert_rowid()")
    job_id = int(row[0]) if row else 0

    # если url уже есть — сразу ок
    if url:
        await db_exec("UPDATE jobs SET status=?, result_url=?, updated_at=? WHERE id=?",
                      ("done", url, now_ts(), job_id))
        # если есть tg_chat_id — отправим в телеграм
        if tg_chat_id:
            await tg_send_photo(str(tg_chat_id), url, caption="✅ Готово (Фото)")
        return {"job_id": job_id, "status": "done", "url": url}

    # иначе — фоновой поллинг и отправка в телеграм
    if tg_chat_id:
        asyncio.create_task(poll_job_to_telegram(job_id))

    return {"job_id": job_id, "status": "queued", "apifree_id": apifree_id}
