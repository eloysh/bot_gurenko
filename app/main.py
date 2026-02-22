import os
import json
import asyncio
import aiosqlite
from typing import Dict, Any, Optional

from fastapi import FastAPI, Request, Body
from fastapi.responses import JSONResponse, PlainTextResponse, FileResponse
from fastapi.staticfiles import StaticFiles

# =========================
# CONFIG
# =========================

DATABASE = "bot.db"
WEBAPP_DIR = "app/webapp"
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# =========================
# APP
# =========================

app = FastAPI()

# =========================
# STATIC WEBAPP
# =========================

if os.path.isdir(WEBAPP_DIR):
    app.mount("/webapp", StaticFiles(directory=WEBAPP_DIR), name="webapp")

# =========================
# DATABASE INIT
# =========================

async def init_db():
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            tg_id INTEGER PRIMARY KEY,
            free_credits INTEGER DEFAULT 50,
            pro_credits INTEGER DEFAULT 0
        )
        """)
        await db.commit()

@app.on_event("startup")
async def startup():
    await init_db()

# =========================
# DB HELPERS
# =========================

async def db_fetchone(db, sql, params=()):
    cur = await db.execute(sql, params)
    row = await cur.fetchone()
    return row

async def get_or_create_user(tg_id: int):
    async with aiosqlite.connect(DATABASE) as db:
        row = await db_fetchone(db,
            "SELECT tg_id, free_credits, pro_credits FROM users WHERE tg_id=?",
            (tg_id,)
        )
        if row:
            return {"tg_id": row[0], "free": row[1], "pro": row[2]}

        await db.execute(
            "INSERT INTO users (tg_id, free_credits, pro_credits) VALUES (?, 50, 0)",
            (tg_id,)
        )
        await db.commit()
        return {"tg_id": tg_id, "free": 50, "pro": 0}

async def consume_credit(tg_id: int):
    async with aiosqlite.connect(DATABASE) as db:
        row = await db_fetchone(db,
            "SELECT free_credits FROM users WHERE tg_id=?",
            (tg_id,)
        )
        if not row:
            return False

        free = row[0]
        if free <= 0:
            return False

        await db.execute(
            "UPDATE users SET free_credits = free_credits - 1 WHERE tg_id=?",
            (tg_id,)
        )
        await db.commit()
        return True

# =========================
# ROOT
# =========================

@app.get("/", response_class=PlainTextResponse)
async def root():
    return "Backend OK"

@app.get("/favicon.ico", response_class=PlainTextResponse)
async def favicon():
    return ""

# =========================
# API MODELS
# =========================

@app.get("/api/models")
async def api_models():
    return JSONResponse({
        "chat": ["gpt", "grok"],
        "image": ["nano-banana"],
        "video": ["kling", "veo"],
        "music": ["mureka"]
    })

# =========================
# API ME
# =========================

@app.get("/api/me")
async def api_me(tg_id: int):
    user = await get_or_create_user(tg_id)
    return JSONResponse(user)

# =========================
# API CHAT
# =========================

@app.post("/api/chat")
async def api_chat(body: Dict[str, Any] = Body(...)):
    tg_id = body.get("tg_id")
    prompt = body.get("prompt")

    if not tg_id or not prompt:
        return JSONResponse({"error": "bad request"}, status_code=400)

    ok = await consume_credit(int(tg_id))
    if not ok:
        return JSONResponse({"error": "no credits"}, status_code=403)

    # MOCK RESPONSE (здесь потом подключим API)
    answer = f"Ответ модели на: {prompt}"

    return JSONResponse({
        "status": "ok",
        "reply": answer
    })

# =========================
# TELEGRAM WEBHOOK
# =========================

@app.post("/telegram/webhook/hook")
async def telegram_webhook(req: Request):
    try:
        data = await req.json()
    except:
        return JSONResponse({"ok": True})

    message = data.get("message", {})
    chat = message.get("chat", {})
    text = message.get("text", "")

    chat_id = chat.get("id")

    if not chat_id:
        return JSONResponse({"ok": True})

    if text == "/start":
        await send_telegram(chat_id, "Бот работает 🚀")

    return JSONResponse({"ok": True})

# =========================
# TELEGRAM SEND
# =========================

async def send_telegram(chat_id, text):
    if not BOT_TOKEN:
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text
    }

    import httpx
    async with httpx.AsyncClient() as client:
        await client.post(url, json=payload)

