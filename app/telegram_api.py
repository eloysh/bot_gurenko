from __future__ import annotations
import httpx
from typing import Any, Dict, Optional

class TelegramAPI:
    def __init__(self, bot_token: str):
        self.bot_token = bot_token
        self.base = f"https://api.telegram.org/bot{bot_token}"

    async def _post(self, method: str, json: Dict[str, Any]) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(f"{self.base}/{method}", json=json)
            data = r.json()
            if not data.get("ok"):
                raise RuntimeError(f"Telegram API error: {data}")
            return data

    async def _get(self, method: str, params: Optional[Dict[str, Any]]=None) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.get(f"{self.base}/{method}", params=params)
            data = r.json()
            if not data.get("ok"):
                raise RuntimeError(f"Telegram API error: {data}")
            return data

    async def set_webhook(self, url: str):
        return await self._post("setWebhook", {"url": url})

    async def send_message(self, chat_id: int, text: str, reply_markup: Optional[Dict[str, Any]]=None, disable_web_page_preview: bool=True):
        payload: Dict[str, Any] = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": disable_web_page_preview}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return await self._post("sendMessage", payload)

    async def send_photo(self, chat_id: int, photo_url: str, caption: Optional[str]=None, reply_markup: Optional[Dict[str, Any]]=None):
        payload: Dict[str, Any] = {"chat_id": chat_id, "photo": photo_url, "parse_mode": "HTML"}
        if caption:
            payload["caption"] = caption
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return await self._post("sendPhoto", payload)

    async def send_video(self, chat_id: int, video_url: str, caption: Optional[str]=None, reply_markup: Optional[Dict[str, Any]]=None):
        payload: Dict[str, Any] = {"chat_id": chat_id, "video": video_url, "parse_mode": "HTML"}
        if caption:
            payload["caption"] = caption
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return await self._post("sendVideo", payload)

    async def answer_callback_query(self, callback_query_id: str, text: Optional[str]=None, show_alert: bool=False):
        payload: Dict[str, Any] = {"callback_query_id": callback_query_id, "show_alert": show_alert}
        if text:
            payload["text"] = text
        return await self._post("answerCallbackQuery", payload)

    async def send_invoice_stars(self, chat_id: int, title: str, description: str, payload: str, prices: list, start_parameter: str="pro"):
        # Telegram Stars uses currency "XTR" and provider_token empty string
        req = {
            "chat_id": chat_id,
            "title": title,
            "description": description,
            "payload": payload,
            "provider_token": "",
            "currency": "XTR",
            "prices": prices,
            "start_parameter": start_parameter
        }
        return await self._post("sendInvoice", req)

    async def send_document(self, chat_id: int, document_url: str, caption: Optional[str]=None, reply_markup: Optional[Dict[str, Any]]=None):
        payload: Dict[str, Any] = {"chat_id": chat_id, "document": document_url, "parse_mode": "HTML"}
        if caption:
            payload["caption"] = caption
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return await self._post("sendDocument", payload)
