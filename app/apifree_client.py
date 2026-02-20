from __future__ import annotations

import httpx
from typing import Any, Dict, List


def _normalize_base_url(base_url: str) -> str:
    """Ensure base_url is absolute (httpx requires scheme)."""
    base_url = (base_url or "").strip()
    if base_url and not base_url.startswith(("http://", "https://")):
        base_url = "https://" + base_url
    return base_url.rstrip("/")


class ApiFreeClient:
    def __init__(self, base_url: str, api_key: str, timeout_s: float = 120.0):
        self.base_url = _normalize_base_url(base_url)
        self.api_key = api_key
        self.timeout_s = timeout_s

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def chat(self, model: str, messages: List[Dict[str, str]], temperature: float = 0.7) -> str:
        url = f"{self.base_url}/v1/chat/completions"
        payload: Dict[str, Any] = {"model": model, "messages": messages, "temperature": temperature}
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            r = await client.post(url, headers=self._headers(), json=payload)
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"]["content"]

    async def image_submit(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Submit an image job.

        Payload is passed through to ApiFree as-is.
        This supports different schemas (txt2img/img2img) like:
        - {model, prompt, negative_prompt, width, height, num_images}
        - {prompt, image, image_url, aspect_ratio, resolution, ...}
        """
        url = f"{self.base_url}/v1/image/submit"
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            r = await client.post(url, headers=self._headers(), json=payload)
            r.raise_for_status()
            return r.json()

    async def image_result(self, request_id: str) -> Dict[str, Any]:
        url = f"{self.base_url}/v1/image/{request_id}/result"
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            r = await client.get(url, headers=self._headers())
            r.raise_for_status()
            return r.json()

    async def video_submit(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Submit a video job (payload passed through as-is)."""
        url = f"{self.base_url}/v1/video/submit"
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            r = await client.post(url, headers=self._headers(), json=payload)
            r.raise_for_status()
            return r.json()

    async def video_result(self, request_id: str) -> Dict[str, Any]:
        url = f"{self.base_url}/v1/video/{request_id}/result"
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            r = await client.get(url, headers=self._headers())
            r.raise_for_status()
            return r.json()


    async def song_submit(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Submit a music/song job.

        ApiFree provider implementations differ. We try the common endpoints in order:
        - POST /v1/song/submit (async job -> request_id)
        - POST /v1/music/generations (may return url immediately)
        """
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            # 1) async submit
            url1 = f"{self.base_url}/v1/song/submit"
            r = await client.post(url1, headers=self._headers(), json=payload)
            if r.status_code < 400:
                return r.json()

            # 2) openai-style generations
            url2 = f"{self.base_url}/v1/music/generations"
            r2 = await client.post(url2, headers=self._headers(), json=payload)
            r2.raise_for_status()
            return r2.json()

    async def song_result(self, request_id: str) -> Dict[str, Any]:
        """Fetch song result for async jobs."""
        url = f"{self.base_url}/v1/song/{request_id}/result"
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            r = await client.get(url, headers=self._headers())
            r.raise_for_status()
            return r.json()
