# Print Cafe — AI-бот первого контакта

MVP бэкенда AI-ассистента для компании Print Cafe (печать на одежде, кружках, шопперах и т. п.). Принимает сообщения из мессенджеров через **Wazzup24**, отвечает на вопросы первой линии с помощью **YandexGPT 5.1 Pro** (OpenAI-совместимый эндпоинт), сохраняет полную историю диалогов в PostgreSQL и помечает чат для передачи оператору, когда без человека не обойтись.

> На этом этапе сделан **только MVP**: webhook → очередь → LLM → ответ. RAG (Qdrant + эмбеддинги Yandex), tool-calls (расчёт цены, сбор брифа, handoff в CRM) и админка — следующие этапы по плану в `print-cafe-bot-architecture`.

## Архитектура (упрощённо)

```
Wazzup24 ── webhook ──▶ FastAPI (POST /webhooks/wazzup)
                            │
                            ▼
                    Redis Stream (wazzup:incoming)
                            │
                            ▼
            Dialog Worker (asyncio consumer)
                ├── Redis: короткое окно диалога + флаг takeover
                ├── PostgreSQL: полная история, лиды
                ├── YandexGPT 5.1 Pro: ответ + маркер handoff
                └── Wazzup24 API: отправка сообщения, тег
```

Сервисы в `docker-compose.yml`: `app` (FastAPI), `worker` (тот же образ, другой entrypoint), `postgres:16`, `redis:7`, `qdrant/qdrant:latest` (поднят впрок для RAG-этапа).

## Структура проекта

```
print_cafe/
├── app/
│   ├── main.py                  # FastAPI: lifespan, /health, /ready
│   ├── config.py                # Pydantic Settings из .env
│   ├── logging_config.py        # structlog + JSON-логи
│   ├── wazzup/
│   │   ├── client.py            # async httpx-клиент Wazzup24 v3
│   │   ├── schemas.py           # Pydantic-схемы вебхуков и API
│   │   └── webhooks.py          # роутер POST /webhooks/wazzup
│   ├── llm/
│   │   ├── client.py            # AsyncOpenAI -> Yandex AI Studio
│   │   ├── prompts.py           # системный промпт + временная заглушка KB
│   │   └── dialog.py            # обработчик одного хода диалога
│   ├── dialog/
│   │   ├── state.py             # Redis: окно сообщений + takeover + дедуп
│   │   └── history.py           # PostgreSQL: dialogs / messages / leads
│   ├── db/
│   │   ├── base.py              # DeclarativeBase
│   │   ├── session.py           # AsyncEngine + async_sessionmaker
│   │   └── models.py            # ORM: Dialog, Message, Lead
│   └── workers/
│       └── dialog_worker.py     # потребитель Redis Stream
├── alembic/                     # миграции (initial: dialogs/messages/leads)
├── scripts/
│   ├── subscribe_webhook.py     # PATCH /v3/webhooks
│   └── send_test_message.py     # ручной smoke-test
├── tests/                       # pytest: webhook, state, dialog
├── docker-compose.yml
├── Dockerfile                   # multi-stage (builder + slim runtime)
├── pyproject.toml               # ruff/black/mypy + зависимости
├── alembic.ini
└── .env.example
```

## Что сделано в MVP

- **Webhook Wazzup24 v3** (`POST /webhooks/wazzup`)
  - Проверка токена через заголовок `Authorization: Bearer <secret>` или query-параметр `?secret=...`.
  - Поддержка тестового запроса `{"test": true}` → 200 OK (нужно при подписке: иначе Wazzup ответит `testPostNotPassed`).
  - **Двухуровневая идемпотентность по `messageId`**: на webhook-стороне быстрый `SETNX` в Redis (TTL 24 ч), в воркере — `INSERT` в `processed_messages` с уникальным PK; при конфликте — пропуск без побочных эффектов. Это переживает рестарт Redis и многосуточные ретраи.
  - Сообщения и статусы кладутся в Redis Stream `wazzup:incoming` с указанием `kind` (`message` / `status`); endpoint отвечает почти мгновенно.
- **Async-клиент Wazzup24** (`app/wazzup/client.py`): `send_message`, `set_webhook`, `add_tag` (best-effort, см. TODO ниже). Тенasити-ретраи на 3 попытки с экспоненциальной задержкой при 429/5xx и сетевых ошибках.
- **Клиент YandexGPT** через OpenAI-совместимый эндпоинт `https://llm.api.cloud.yandex.net/v1` (Yandex AI Studio, доступно с марта 2026). Передаёт `x-folder-id` и `x-data-logging-enabled: false` в заголовках, `model = gpt://<folder_id>/yandexgpt/rc` (ветка RC = 5.1 Pro).
- **Системный промпт** (`app/llm/prompts.py`) фиксирует тон («вы», без эмодзи), запрещает выдумывать цены/сроки/скидки, дробит ответы на 1–3 коротких сообщения через маркер `\n---\n`, требует ставить служебный маркер `[HANDOFF: <reason>]` в конце ответа, когда нужен оператор. KB пока вшита в промпт как заглушка (на следующем этапе — RAG).
- **Agent + Tool registry** (`app/llm/agent.py`, `app/tools/handoff.py`):
  - Класс `Agent` держит реестр инструментов. На MVP зарегистрирован один — `handoff_to_human(reason)` со схемой в OpenAI tool-calling формате (готова к подключению нативных tool calls в следующей фазе).
  - Триггер инструмента в MVP — маркер `[HANDOFF: <reason>]` в ответе LLM. Это надёжно работает с YandexGPT 5.1 Pro: native function calling в OpenAI-compat слое Yandex меняется и ведёт себя нестабильно, маркер же контролируется системным промптом.
  - `execute_handoff` делает все побочные эффекты разом: `Dialog.status='human'` в БД, `set_human_takeover` в Redis, `WazzupClient.add_tag(human_needed:<reason>)` (best-effort).
- **Dialog handler** (`app/llm/dialog.py`):
  - Тонкий backwards-compatible адаптер над `Agent`. Берёт историю из Redis (окно N=20), добавляет system prompt, отправляет в LLM, парсит маркер.
  - Ключевые слова «менеджер / оператор / человек / живой / сотрудник» — короткое замыкание без обращения к LLM.
- **Dialog state**:
  - `Redis`: `dialog:{chat_id}:messages` (последние 20, TTL 7 дней), `dialog:{chat_id}:human_takeover` (флаг с TTL).
  - `PostgreSQL`: таблицы `dialogs`, `messages`, `leads`, `processed_messages` (alembic-миграция `0001_initial`).
- **Worker** (`app/workers/dialog_worker.py`):
  - Создаёт Redis consumer group `dialog_workers`, читает поток `wazzup:incoming`.
  - Outgoing-сообщения от оператора (`isEcho=true`) → выставляют `human_takeover`, бот молчит.
  - Incoming → персистится в БД, идёт через `handle_message`, ответ отправляется обратно по `WazzupClient.send_message`, при `[HANDOFF]` ставится тег и `human_takeover`.
  - Ошибка на одном сообщении не валит весь воркер: `xack` + `logger.exception`.
- **Health/Ready**: `/health` всегда 200, `/ready` пингует Redis и PostgreSQL.
- **Логирование**: structlog, JSON в проде (контролируется `LOG_JSON`).
- **Тесты** (`pytest -xvs`):
  - `test_wazzup_webhook.py` — тест-проба, неверный токен, query-секрет, нормальное сообщение в стрим, дедуп.
  - `test_dialog_state.py` — append/read/trim, TTL, takeover, dedup setnx.
  - `test_llm_dialog.py` — мок LLM, проверка истории/блокировки/ключевых слов/парсинга `[HANDOFF]`.
  - `test_handoff_tool.py` — схема инструмента, нормализация reason, real-side-effects через in-memory SQLite, deduplication ProcessedMessage.

## Чего НЕТ в MVP (следующие этапы)

| Этап | Что подключаем |
|---|---|
| RAG | Парсер сайта/прайса, эмбеддинги Yandex (`text-search-doc/query`), Qdrant, гибридный поиск, `tool: search_knowledge` |
| Tools | Native function calling YandexGPT (когда стабилизируется в OpenAI-compat) + `calculate_price`, `collect_brief` |
| CRM | amoCRM / Bitrix24: создание лида, смена ответственного, теги |
| Админка | FastAPI + HTMX: список диалогов, разметка, метрики, ручной реиндекс KB |
| Деплой | TLS Caddy, Sentry, мониторинг, продовый канал Wazzup |

## Что нужно от заказчика для запуска

1. **Wazzup24**
   - API-ключ (Личный кабинет → Интеграции → API).
   - `channelId` тестового канала (WhatsApp / Telegram / Avito и т.д.).
   - Публичный HTTPS-URL, на который Wazzup будет слать вебхуки (например, через ngrok / Caddy).
2. **Yandex Cloud / AI Studio**
   - Сервисный аккаунт с ролью `ai.languageModels.user` (для RAG позже также `ai.embeddings.user`).
   - API-ключ сервисного аккаунта.
   - `folder_id` каталога с привязанным платёжным аккаунтом.
3. **Инфраструктура**
   - VPS (минимум 4 CPU / 8 GB / 80 GB) или локальная машина с Docker.
   - Доменное имя для вебхука (например, `bot.printcafe.ru`).

Все переменные см. в `.env.example`, ниже — обязательные:

| Переменная | Назначение |
|---|---|
| `WAZZUP_API_KEY` | Bearer-токен для Wazzup24 v3 API |
| `WAZZUP_WEBHOOK_SECRET` | Секрет, который мы проверяем во входящих вебхуках (обычно равен `WAZZUP_API_KEY`, см. ниже) |
| `WAZZUP_PUBLIC_WEBHOOK_URL` | Куда Wazzup шлёт POST (нужен только для скрипта подписки) |
| `YANDEX_API_KEY` | API-ключ сервисного аккаунта Yandex Cloud |
| `YANDEX_FOLDER_ID` | ID каталога; подставляется в `YANDEX_MODEL`, если в значении есть `<folder_id>` |
| `YANDEX_MODEL` | По умолчанию `gpt://<folder_id>/yandexgpt/rc` (5.1 Pro) |
| `POSTGRES_*`, `REDIS_URL`, `QDRANT_URL` | Параметры БД, кэша, Qdrant |

> **Примечание про `WAZZUP_WEBHOOK_SECRET`.** По документации Wazzup, если у нашего приложения зарегистрирован `crmKey` в личном кабинете, Wazzup добавит к каждому вебхуку заголовок `Authorization: Bearer ${crmKey}`. Мы сравниваем это значение со своим `WAZZUP_WEBHOOK_SECRET`. Если в кабинете `crmKey` не задан, Wazzup отправит вебхук без заголовка — тогда оставьте `WAZZUP_WEBHOOK_SECRET` пустым (тогда endpoint принимает всё, лог пишет warning), либо проверяйте секрет через query-параметр `?secret=...` (URL подписки придётся прописать с этим параметром).

## Чек-лист первого запуска

```bash
# 1. Подготовить .env
cp .env.example .env
$EDITOR .env  # заполнить WAZZUP_*, YANDEX_*

# 2. Поднять инфраструктуру и приложение
docker compose up -d --build

# 3. Применить миграции БД
docker compose exec app alembic upgrade head

# 4. (Опционально) проверить /ready
curl -s http://localhost:8000/ready

# 5. Опубликовать вебхук-эндпоинт наружу (например, через Caddy / ngrok)
#    URL должен совпадать с WAZZUP_PUBLIC_WEBHOOK_URL в .env

# 6. Подписаться на вебхуки Wazzup
docker compose exec app python -m scripts.subscribe_webhook

# 7. Проверить отправку (опционально)
docker compose exec app python -m scripts.send_test_message \
    --channel <channelId> --chat-id 79991234567 \
    --chat-type whatsapp --text "Привет, это тест"
```

Worker запускается тем же `docker compose up -d` (отдельный сервис `worker`).

## Локальная разработка без Docker

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Поднять только PG и Redis (Qdrant пока не нужен)
docker compose up -d postgres redis

# Применить миграции
alembic upgrade head

# Запустить API
uvicorn app.main:app --reload

# В другом окне — worker
python -m app.workers.dialog_worker

# Тесты
pytest -xvs
ruff check .
black --check .
mypy app/
```

## Открытые вопросы / TODO

- **Тегирование чата в Wazzup.** В публичной документации v3 нет первичной сущности «тег». Метод `WazzupClient.add_tag` сделан как best-effort (не падает, если эндпоинт не отвечает). На реальном аккаунте Wazzup нужно подтвердить, как именно у заказчика реализован handoff: через смену ответственного в CRM, через `responsibleUserId` в чате или через теги. Пока в БД мы пишем `status='human'` и в Redis выставляем флаг — этого достаточно, чтобы бот молчал.
- **Точный URI модели.** `gpt://<folder_id>/yandexgpt/rc` — это ветка release-candidate, которая на момент марта 2026 указывает на 5.1 Pro. Если Yandex переименует ветку, поправьте `YANDEX_MODEL` в `.env` без изменений в коде.
- **Стиль ответов.** Промпт пока без few-shot примеров и без архива реальных диалогов менеджеров — после получения архива из Wazzup стоит добавить 5–10 эталонных пар «вопрос — ответ» в `app/llm/prompts.py`.
- **Webhook-секрет.** Точное имя поля в Wazzup, через которое настраивается `crmKey`, и как именно он попадает в заголовок Authorization, нужно подтвердить на реальном аккаунте — у документации немного расходятся «Bearer ${crmKey}» и «равен API-ключу».

## Линтеры и стандарты

- `ruff check .` — стиль (E, F, I, B, UP, N, S).
- `black --check .` — форматирование (line-length 100).
- `mypy app/` — статическая типизация (strict).
- `pytest -xvs` — тесты (asyncio_mode = "auto").
