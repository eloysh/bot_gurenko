from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import List

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Telegram
    BOT_TOKEN: str = Field(..., description="Telegram bot token from BotFather")
    PUBLIC_BASE_URL: str = Field(..., description="Public HTTPS base URL for webhooks, e.g. https://xxx.onrender.com")
    WEBHOOK_SECRET: str = Field(default="hook", description="Secret path segment for webhook")

    # ApiFree
    APIFREE_API_KEY: str = Field(..., description="ApiFree API key")
    # NOTE: must be HTTPS on Render, иначе часто ловится provider_error.
    APIFREE_BASE_URL: str = Field(default="https://api.apifree.ai", description="ApiFree base URL")

    # Defaults used when client does not pass a model.
    APIFREE_CHAT_MODEL: str = Field(default="openai/gpt-5.2")
    APIFREE_IMAGE_MODEL: str = Field(default="google/nano-banana-pro")
    APIFREE_VIDEO_MODEL: str = Field(default="klingai/kling-v2.5-turbo/standard/image-to-video")
    APIFREE_SONG_MODEL: str = Field(default="mureka-ai/mureka-v8/generate-song")

    # Model catalog shown in the Mini App.
    # IMPORTANT: `id` must match APIFree's model id exactly.
    # If the id is wrong APIFree returns: invalid_model / model schema not found.
    MODELS: list[dict] = [
        # LLM
        {"id": "openai/gpt-5.2", "label": "OpenAI • GPT 5.2", "kind": "llm"},
        {"id": "openai/gpt-5", "label": "OpenAI • GPT 5", "kind": "llm"},
        {"id": "openai/gpt-5-mini", "label": "OpenAI • GPT 5 mini", "kind": "llm"},
        {"id": "anthropic/claude-sonnet-4.5", "label": "Anthropic • Claude Sonnet 4.5", "kind": "llm"},
        {"id": "anthropic/claude-sonnet-4", "label": "Anthropic • Claude Sonnet 4", "kind": "llm"},
        {"id": "anthropic/claude-haiku-4.5", "label": "Anthropic • Claude Haiku 4.5", "kind": "llm"},
        {"id": "google/gemini-2.5-pro", "label": "Google • Gemini 2.5 Pro", "kind": "llm"},
        {"id": "google/gemini-2.5-flash", "label": "Google • Gemini 2.5 Flash", "kind": "llm"},
        {"id": "google/gemini-2.5-flash-lite", "label": "Google • Gemini 2.5 Flash Lite", "kind": "llm"},
        {"id": "google/gemini-3-pro-preview", "label": "Google • Gemini 3 Pro Preview", "kind": "llm"},
        {"id": "xai/grok-4", "label": "xAI • Grok 4", "kind": "llm"},
        {"id": "moonshot/kimi-k2.5", "label": "Moonshot • Kimi K2.5", "kind": "llm"},
        {"id": "deepseek/deepseek-v3.2", "label": "DeepSeek • V3.2", "kind": "llm"},
        {"id": "deepseek/deepseek-v3.2-thinking", "label": "DeepSeek • V3.2 (Thinking)", "kind": "llm"},
        {"id": "qwen/qwen3-235b-a22b-instruct-2507", "label": "Qwen • Qwen3 235B A22B Instruct", "kind": "llm"},
        {"id": "qwen/qwen3-coder-480b-a35b", "label": "Qwen • Qwen3 Coder 480B", "kind": "llm"},
        {"id": "qwen/qwen3-vl-235b-a22b-instruct", "label": "Qwen • Qwen3 VL 235B", "kind": "llm"},
        {"id": "qwen/qwen3-vl-30b-a3b-instruct", "label": "Qwen • Qwen3 VL 30B", "kind": "llm"},
        {"id": "qwen/qwen3-next-80b-a3b-instruct", "label": "Qwen • Qwen3 Next 80B", "kind": "llm"},
        {"id": "zai/glm-5", "label": "Z.ai • GLM 5", "kind": "llm"},
        {"id": "bytedance/seed-1.8", "label": "Bytedance • Seed 1.8", "kind": "llm"},
        {"id": "minimax/minimax-m2.5", "label": "MiniMax • M2.5", "kind": "llm"},

        # TEXT → IMAGE
        {"id": "google/nano-banana-pro", "label": "Google • Nano Banana PRO (text→image)", "kind": "t2i"},
        {"id": "google/nano-banana", "label": "Google • Nano Banana (text→image)", "kind": "t2i"},
        {"id": "bytedance/seedream-4.5", "label": "Bytedance • Seedream 4.5 (text→image)", "kind": "t2i"},
        {"id": "qwen/qwen-image-2512", "label": "Qwen • Qwen-Image 2512 (text→image)", "kind": "t2i"},
        {"id": "tongyi-mai/z-image-turbo", "label": "Tongyi-MAI • Z Image Turbo (text→image)", "kind": "t2i"},
        {"id": "black-forest-labs/flux-2-dev", "label": "Black Forest Labs • FLUX 2 DEV (text→image)", "kind": "t2i"},
        {"id": "stability-ai/fast-sdxl", "label": "Stability AI • Fast SDXL (text→image)", "kind": "t2i"},
        {"id": "hidream-ai/hidream-i1-fast", "label": "HiDream • I1 Fast (text→image)", "kind": "t2i"},

        # IMAGE → IMAGE (EDIT)
        {"id": "google/nano-banana-pro/edit", "label": "Google • Nano Banana PRO EDIT (image→image)", "kind": "i2i"},
        {"id": "google/nano-banana/edit", "label": "Google • Nano Banana EDIT (image→image)", "kind": "i2i"},
        {"id": "openai/gpt-image-1.5-edit", "label": "OpenAI • GPT Image 1.5 Edit (image→image)", "kind": "i2i"},
        {"id": "black-forest-labs/flux-2-dev-edit", "label": "Black Forest Labs • Flux 2 DEV Edit (image→image)", "kind": "i2i"},
        {"id": "bytedance/seedream-4.5-edit", "label": "Bytedance • Seedream 4.5 Edit (image→image)", "kind": "i2i"},
        {"id": "ideogram/ideogram-v3-edit", "label": "Ideogram • Ideogram V3 Edit (image→image)", "kind": "i2i"},
        {"id": "qwen/qwen-image-edit-2511", "label": "Qwen • Qwen Image Edit 2511 (image→image)", "kind": "i2i"},

        # IMAGE → VIDEO
        {"id": "klingai/kling-v2.6/pro/image-to-video", "label": "KlingAI • Kling 2.6 Pro (image→video)", "kind": "i2v"},
        {"id": "klingai/kling-v2.5-turbo/standard/image-to-video", "label": "KlingAI • Kling 2.5 Turbo Standard (image→video)", "kind": "i2v"},
        {"id": "klingai/kling-2.6-pro-motion-control", "label": "KlingAI • Kling 2.6 Pro Motion Control (image→video)", "kind": "i2v"},
        {"id": "klingai/kling-2.6-std-motion-control", "label": "KlingAI • Kling 2.6 Std Motion Control (image→video)", "kind": "i2v"},
        {"id": "openai/sora-2-i2v", "label": "OpenAI • Sora 2 I2V (image→video)", "kind": "i2v"},
        {"id": "openai/sora-2-pro-i2v", "label": "OpenAI • Sora 2 Pro I2V (image→video)", "kind": "i2v"},
        {"id": "google/veo-3.1-i2v", "label": "Google • Veo 3.1 I2V (image→video)", "kind": "i2v"},
        {"id": "google/veo-3.1-fast-i2v", "label": "Google • Veo 3.1 Fast I2V (image→video)", "kind": "i2v"},
        {"id": "google/veo-3.1-i2v-w-audio", "label": "Google • Veo 3.1 I2V w/ audio", "kind": "i2v"},
        {"id": "google/veo-3.1-fast-i2v-w-audio", "label": "Google • Veo 3.1 Fast I2V w/ audio", "kind": "i2v"},
        {"id": "bytedance/seedance-1.5-pro-i2v", "label": "Bytedance • Seedance 1.5 Pro I2V", "kind": "i2v"},
        {"id": "bytedance/seedance-1-pro-i2v", "label": "Bytedance • Seedance 1 Pro I2V", "kind": "i2v"},
        {"id": "wan-ai/wan-v2.2-a14b-i2v-turbo", "label": "Wan-AI • Wan V2.2 A14B I2V Turbo", "kind": "i2v"},

        # TEXT → VIDEO
        {"id": "wan-ai/wan-v2.2-a14b-t2v-turbo", "label": "Wan-AI • Wan V2.2 A14B T2V Turbo", "kind": "t2v"},
        {"id": "google/veo-3.1-t2v", "label": "Google • Veo 3.1 T2V", "kind": "t2v"},
        {"id": "google/veo-3.1-fast-t2v", "label": "Google • Veo 3.1 Fast T2V", "kind": "t2v"},
        {"id": "google/veo-3.1-t2v-w-audio", "label": "Google • Veo 3.1 T2V w/ audio", "kind": "t2v"},
        {"id": "google/veo-3.1-fast-t2v-w-audio", "label": "Google • Veo 3.1 Fast T2V w/ audio", "kind": "t2v"},
        {"id": "klingai/kling-2.6-pro-text-to-video", "label": "KlingAI • Kling 2.6 Pro (text→video)", "kind": "t2v"},
        {"id": "klingai/kling-2.6-pro-text-to-video-w-audio", "label": "KlingAI • Kling 2.6 Pro (text→video w/ audio)", "kind": "t2v"},

        # AUDIO → VIDEO
        {"id": "skywork/skyreels-v3-pro-single-avatar-1080p", "label": "Skywork • SkyReels V3 Pro Single Avatar (audio→video)", "kind": "a2v"},
        # MUSIC
        {"id": "mureka-ai/mureka-v8/generate-song", "label": "Mureka • V8 Generate Song", "kind": "music"},

    ]

    # Storage
    DB_PATH: str = Field(default="./data/app.db")

    # Credits / Referral
    FREE_CREDITS_ON_SIGNUP: int = Field(default=2)
    REF_BONUS_REFERRER: int = Field(default=1)
    REF_BONUS_NEW_USER: int = Field(default=1)

    # Security
    APP_SECRET: str = Field(default="change-me-very-long-random-string")

    # Stars / PRO (optional)
    PRICE_PRO_XTR: int = Field(default=0, description="Telegram Stars price (XTR). 0 disables purchase button.")
    ADMIN_IDS: str = Field(default="")

    def admin_ids(self) -> List[int]:
        if not self.ADMIN_IDS.strip():
            return []
        out = []
        for x in self.ADMIN_IDS.split(","):
            x = x.strip()
            if x:
                out.append(int(x))
        return out

settings = Settings()
