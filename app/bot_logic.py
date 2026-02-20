from __future__ import annotations

import re
from typing import Any, Dict, Optional, List
from .storage import Storage
from .telegram_api import TelegramAPI
from .apifree_client import ApiFreeClient
from .config import settings

START_RE = re.compile(r"^/start(?:\s+(.+))?$")

def _main_menu(webapp_url: str) -> Dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "💬 ChatGPT", "callback_data": "mode:chat"},
                {"text": "🖼 Фото", "callback_data": "mode:image"},
            ],
            [
                {"text": "🎬 Видео", "callback_data": "mode:video"},
                {"text": "🎵 Музыка", "callback_data": "mode:music"},
            ],
            [
                {"text": "⚡ Mini‑App", "web_app": {"url": webapp_url}},
            ],
            [
                {"text": "🎁 Пригласить друга", "callback_data": "ref:share"},
                {"text": "⭐ PRO (Stars)", "callback_data": "pro:buy"},
            ],
            [
                {"text": "ℹ️ Баланс", "callback_data": "me:balance"},
                {"text": "🛟 Помощь", "callback_data": "help"},
            ],
        ]
    }

def _share_keyboard(ref_link: str) -> Dict[str, Any]:
    return {
        "inline_keyboard": [
            [{"text": "🔗 Поделиться ссылкой", "switch_inline_query": ref_link}],
            [{"text": "⬅️ Назад", "callback_data": "back:menu"}],
        ]
    }

def _webapp_url() -> str:
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/webapp/"

async def ensure_user(storage: Storage, tg_user: Dict[str, Any], start_payload: Optional[str]):
    tg_id = tg_user["id"]
    username = tg_user.get("username")
    first_name = tg_user.get("first_name")

    u = await storage.get_user(tg_id)
    if u:
        return

    referred_by: Optional[int] = None
    if start_payload and start_payload.startswith("ref_"):
        try:
            referred_by = int(start_payload.replace("ref_", ""))
        except Exception:
            referred_by = None

    # create user
    await storage.upsert_user(
        tg_id=tg_id,
        username=username,
        first_name=first_name,
        credits_free=settings.FREE_CREDITS_ON_SIGNUP,
        referred_by=referred_by,
    )

    # apply referral bonuses only on first signup
    if referred_by and referred_by != tg_id:
        # give referrer +1, new user +1 (extra)
        await storage.add_credits(referred_by, free_delta=settings.REF_BONUS_REFERRER)
        await storage.add_credits(tg_id, free_delta=settings.REF_BONUS_NEW_USER)

async def handle_update(storage: Storage, tg: TelegramAPI, apifree: ApiFreeClient, update: Dict[str, Any]):
    # message
    if "message" in update:
        msg = update["message"]
        chat_id = msg["chat"]["id"]
        text = msg.get("text", "")

        m = START_RE.match(text or "")
        if m:
            payload = m.group(1)
            await ensure_user(storage, msg["from"], payload)
            await tg.send_message(
                chat_id,
                "<b>Привет! Я Creator_Kristina.ai 🤍</b>\n\n"                "Я умею: <b>ChatGPT</b>, <b>генерация фото</b>, <b>генерация видео</b> — через ApiFree.\n\n"                "Выбирай режим ниже 👇",
                reply_markup=_main_menu(_webapp_url()),
            )
            return

        # plain text -> chat (quick mode)
        if text:
            await ensure_user(storage, msg["from"], None)
            ok = await storage.consume_credit(chat_id)
            if not ok:
                await tg.send_message(chat_id, "⚠️ У тебя закончились кредиты. Нажми ⭐ PRO или пригласи друга 🎁", reply_markup=_main_menu(_webapp_url()))
                return

            await tg.send_message(chat_id, "⌛ Думаю...")
            answer = await apifree.chat(
                model=settings.APIFREE_CHAT_MODEL,
                messages=[{"role": "user", "content": text}],
            )
            await tg.send_message(chat_id, answer, reply_markup=_main_menu(_webapp_url()))
            return

    # callback query
    if "callback_query" in update:
        cq = update["callback_query"]
        data = cq.get("data", "")
        chat_id = cq["message"]["chat"]["id"]
        from_user = cq["from"]
        await ensure_user(storage, from_user, None)

        if data == "back:menu":
            await tg.answer_callback_query(cq["id"])
            await tg.send_message(chat_id, "Меню 👇", reply_markup=_main_menu(_webapp_url()))
            return

        if data.startswith("ref:"):
            ref_link = f"https://t.me/{cq['message']['chat'].get('username','')}?start=ref_{from_user['id']}"
            # if bot username unknown in message, use placeholder; miniapp uses proper link.
            ref_link = f"https://t.me/{update.get('bot_username','your_bot')}?start=ref_{from_user['id']}"
            await tg.answer_callback_query(cq["id"])
            await tg.send_message(
                chat_id,
                "🎁 <b>Приглашай друзей</b> и получай бесплатные генерации!\n\n"                f"Твоя ссылка:\n<code>{ref_link}</code>\n\n"                "Друг запускает бота по ссылке → вам обоим начисляются кредиты.",
                reply_markup=_share_keyboard(ref_link),
            )
            return

        if data == "me:balance":
            u = await storage.get_user(from_user["id"])
            await tg.answer_callback_query(cq["id"])
            await tg.send_message(
                chat_id,
                f"💳 <b>Баланс</b>\n"                f"• Free: <b>{u.credits_free}</b>\n"                f"• PRO: <b>{u.credits_pro}</b>",
                reply_markup=_main_menu(_webapp_url()),
            )
            return

        if data == "help":
            await tg.answer_callback_query(cq["id"])
            await tg.send_message(
                chat_id,
                "🛟 <b>Как пользоваться</b>\n\n"                "1) Напиши текст — получишь ответ ChatGPT\n"                "2) Для фото/видео удобнее через Mini‑App (⚡)\n"                "3) Хочешь больше бесплатных генераций — нажми 🎁 и пригласи друга\n\n"                "Если что-то не работает — проверь токены и домен (Render env vars).",

                reply_markup=_main_menu(_webapp_url()),
            )
            return

        if data == "pro:buy":
            await tg.answer_callback_query(cq["id"])
            if settings.PRICE_PRO_XTR <= 0:
                await tg.send_message(chat_id, "⭐ PRO сейчас выключен. Напиши мне — включу оплату.", reply_markup=_main_menu(_webapp_url()))
                return
            prices = [{"label": "PRO пакет", "amount": settings.PRICE_PRO_XTR}]
            await tg.send_invoice_stars(
                chat_id=chat_id,
                title="Creator_Kristina.ai PRO",
                description="Больше генераций + приоритет.",
                payload=f"pro:{from_user['id']}",
                prices=prices,
            )
            return

        if data.startswith("mode:"):
            await tg.answer_callback_query(cq["id"], text="Открой Mini‑App для этого режима ⚡")
            return

        await tg.answer_callback_query(cq["id"])
