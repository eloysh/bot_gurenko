# Creator Kristina — Telegram Bot + Mini App (ApiFree)

Это готовый шаблон: Telegram-бот с красивым меню (как у VeoSeeBot-стиля) + мини‑приложение (WebApp) + генерация **Chat / Image / Video** через **ApiFree**.

## Что внутри
- `/start` — красивое приветствие + кнопки (Chat / Фото / Видео / Mini App / Подписка PRO / Рефералка)
- Реферальная ссылка: `https://t.me/<username>?start=ref_<tg_user_id>`
- Лимит бесплатных генераций (кредиты) + начисление за приглашённого друга
- Мини‑приложение (WebApp): чат + генерации, кнопка «Поделиться» (в друзья/в сториз)
- Backend на FastAPI: Telegram webhook + API для мини‑аппа
- Хранилище: SQLite по умолчанию (можно Postgres позже)

---

## 1) Что нужно заранее
1) Создать бота в @BotFather и получить **BOT_TOKEN**
2) В ApiFree создать **API Key**
3) Деплой на Render (Web Service)

Важно: для работы генерации **картинок/видео** укажите правильный `APIFREE_BASE_URL` и точные ID моделей.

---

## 2) Переменные окружения (Render → Environment)
Обязательные:
- `BOT_TOKEN` — токен Telegram бота (BotFather)
- `APIFREE_API_KEY` — ключ ApiFree
- `PUBLIC_BASE_URL` — ваш публичный домен Render, например `https://ai-kristina.onrender.com`

Рекомендуемые:
- `WEBHOOK_SECRET` — любой случайный секрет (например 32 символа)
- `APP_SECRET` — любой случайный секрет (для подписи сессий/рефералок)
- `DB_PATH` — путь к sqlite (по умолчанию `./data/app.db`)

Провайдер:
- `APIFREE_BASE_URL` — базовый URL API (должен начинаться с `https://`).
  - обычно: `https://api.apifree.ai`
  - если вы используете другой домен (например SkyCoding) — ставьте его, но он тоже должен быть `https://...`

Модели (можно менять в env, а также выбирать в мини‑приложении):
- `APIFREE_CHAT_MODEL` — дефолт для чата
- `APIFREE_IMAGE_MODEL` — дефолт для картинок
- `APIFREE_VIDEO_MODEL` — дефолт для видео

Если ловите ошибку `invalid_model` / `model schema not found` — это **не про ожидание**, а про неверный ID модели.
Нужно взять точные ID из провайдера.

Быстрая проверка моделей (в Render Shell / локально):
```bash
curl -sS -H "Authorization: Bearer $APIFREE_API_KEY" "$APIFREE_BASE_URL/v1/openai/models" | head
curl -sS -H "Authorization: Bearer $APIFREE_API_KEY" "$APIFREE_BASE_URL/v1/models" | head
```
Один из этих эндпоинтов у провайдера обычно вернёт список моделей.

Кредиты:
- `FREE_CREDITS_ON_SIGNUP` (по умолчанию 2)
- `REF_BONUS_REFERRER` (по умолчанию 1)
- `REF_BONUS_NEW_USER` (по умолчанию 1)

PRO через Telegram Stars (опционально):
- `PRICE_PRO_XTR` — цена в Stars (XTR), например `50`
- `ADMIN_IDS` — ваши TG id через запятую (для админ-команд)

---

## 3) Локальный запуск (проверка)
```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export BOT_TOKEN="..."
export APIFREE_API_KEY="..."
export PUBLIC_BASE_URL="https://example.ngrok.app"
export WEBHOOK_SECRET="mysecret"
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

---

## 4) Деплой на Render (самое простое)
### Шаги
1) Залейте этот проект в GitHub
2) Render → **New** → **Web Service** → выберите репозиторий
3) **Runtime**: Python
4) **Build Command**: `pip install -r requirements.txt`
5) **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
6) Добавьте Env variables (см. выше)
7) Deploy

После деплоя откройте:
- `https://<ваш-домен>/health` → должно вернуть `{"ok": true}`
- В логах увидите строку про setWebhook (если `WEBHOOK_SECRET` задан)

---

## 5) Если /start «ничего не делает»
Самые частые причины:
1) **не тот BOT_TOKEN** (в BotFather вы пересоздали токен) → ставьте новый токен и redeploy
2) webhook не поставился (нет `PUBLIC_BASE_URL` или неверный домен)
3) бот не получает обновления, потому что webhook URL неверный

Проверка токена:
```bash
curl "https://api.telegram.org/bot<ВАШ_ТОКЕН>/getMe"
```
Если ответ `{"ok":false,"error_code":401,"description":"Unauthorized"}` — токен неверный.

---

## 6) Структура проекта
- `app/` — backend + логика
- `webapp/` — мини‑приложение (отдаётся как статика)
- `scripts/` — вспомогательные утилиты
