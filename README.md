# AI-агент службы поддержки


[![hexlet-check](https://github.com/hoter/llm-developer-project-425/actions/workflows/hexlet-check.yml/badge.svg)](https://github.com/hoter/llm-developer-project-425/actions)

Соберите Help Desk-агента на Yandex AI Studio: почтовый агент (IMAP/SMTP) принимает
обращения сотрудников, ищет ответ в корпоративной базе знаний (RAG) и при необходимости
заводит тикет и сохраняет переписку в YDB Serverless. По пути освоите агента в AI Studio
(Responses API), собственный MCP-инструмент, workflow по расписанию, RAG, защиту от
prompt injection и PII-утечек, а также наблюдаемость (трейсы и токены). Решение
разворачивается в вашем аккаунте Yandex Cloud (Cloud Functions, Workflows, MCP Hub,
Lockbox). Сдача — репозиторий с конфигами и рабочий почтовый агент.

Учебный проект Хекслета: https://ru.hexlet.io/programs/llm-developer
Как это должно работать: 

## Стек

**Язык и платформа**
- Python 3.12; локальный venv (`.venv`); Yandex Cloud Functions (Serverless).

**ИИ / Yandex AI Studio**
- Responses API (клиент `openai`, base `ai.api.cloud.yandex.net/v1`, авторизация IAM-токеном SA);
- `yandexgpt/latest` — агент Help Desk (инлайн-вызов из почтового поллера);
- `yandexgpt-lite` — LLM-классификатор guardrail (safe | injection | off-topic);
- RAG: Vector Store / search index `help-desk-kb` (`docs/`), инструмент `file_search`;
- Правила модерации AI Studio (токсичность/PII) — на сохранённом агенте.

**MCP Hub**
- gateway `ydb-tickets-mcp`: 3 инструмента — `create-ticket`, `list-my-tickets`, `append-message`; каждый вызывает CF `ydb-tickets`.

**Хранилище и секреты**
- YDB Serverless: таблицы `tickets`, `messages` (пакет `ydb`, prepared statements);
- Yandex Lockbox: `ydb-endpoint`, `ydb-database`, `email-credentials`, `SMTP_PASSWORD`/`IMAP_PASSWORD`, `ai-studio-api-key`.

**Почта (pull-режим)**
- CF `email-poller` (по таймеру: IMAP-забор → агент → SMTP-ответ; Yandex Mail);
- CF `email-sender` — SMTP-обёртка для Workflows (httpCall → письмо оператору).

**Оркестрация**
- Yandex Workflows (YaWL 0.1): `daily-escalation` — `databaseQuery` → `switch` → `aiStudioAgent` → `databaseQuery` → `httpCall`; cron 09:00 (Europe/Moscow).

**Безопасность**
- Guardrail на границе записи в CF `ydb-tickets`: regex-предфильтр + `yandexgpt-lite`, fail-open; `ALERT_INJECTION_BLOCKED`/`ALERT_OFFTOPIC`;
- PII-маскирование перед записью в YDB (телефон/email/карта);
- Trusted vs Untrusted-контекст; логи без сырого PII.

**Наблюдаемость**
- Yandex Cloud Logging: логи CF и трейсы Workflows (`yc logging read`).

**Инструменты**
- `yc` CLI; `yandex-ai-studio` CLI и `yandex_ai_studio_sdk` (search index, vector stores).

## Установка

<!-- Опишите установку: клонирование, зависимости, переменные окружения -->

```bash
git clone https://github.com/hoter/llm-developer-project-425.git
cd llm-developer-project-425
```

## Использование

<!-- Добавьте примеры запуска и запись asciinema — именно это смотрит работодатель -->

---

<details>
<summary>Автоматические тесты Хекслета</summary>

Тесты запускаются на каждый коммит. За запуск отвечает файл `.github/workflows/hexlet-check.yml` — не удаляйте и не переименовывайте ни его, ни репозиторий.

</details>

## О Хекслете

[Хекслет](https://ru.hexlet.io/) — школа программирования: авторские программы обучения с практикой, поддержкой наставников и реальными проектами, которые остаются в резюме. Этот репозиторий — один из таких проектов.

## Секреты в Lockbox
- ydb-endpoint
- ydb-database
- ai-studio-api-key

## Защита: Trusted vs Untrusted

Агент обрабатывает данные из разных источников. Часть из них — доверенная конфигурация, часть — недоверенный ввод пользователя. Их нужно строго разделять.

**Trusted (доверенный):**
- системный промпт агента (инструкции в `src/agent_instructions.md`);
- конфигурация инструментов (MCP `ydb-tickets`, `file_search`/search index) — её задаём мы;
- метаданные запросов (action, параметры, вердикты).

**Untrusted (недоверенный):**
- текст обращения пользователя (из письма);
- текст из RAG-документов, если документы парсятся из внешних источников.

**Правила:**
- НИКОГДА не интерполировать untrusted-текст в trusted-контекст (системный промпт). Системный промпт не собирается из сообщений пользователя.
- Любые инструкции внутри сообщения пользователя («проигнорируй предыдущие инструкции», «удали тикеты», «покажи системный промпт») — атаки prompt injection и не выполняются.

**Защита по слоям:**
1. Промпт агента: untrusted-текст — данные, не инструкции; при инъекции — отказ.
2. Guardrail на границе записи в CF `ydb-tickets` (перед create-ticket / append-message):
   - regex-предфильтр (явные паттерны инъекций) → блок `ALERT_INJECTION_BLOCKED`;
   - LLM-классификатор `yandexgpt-lite` (safe | injection | off-topic, `temperature=0`) → injection блок, off-topic логируется `ALERT_OFFTOPIC`; ошибка классификатора — fail-open (пропуск как safe).
3. PII-маскирование перед записью в YDB (в CF, не в промпте):
   - телефон → `+7 (***) ***-**-<2 последние цифры>`;
   - email → `[email]`;
   - номер карты → `****-****-****-****`.
4. Логи CF: только метаданные и вердикты; сырой PII не логируется.

`require_approval: "never"` для MCP-tools отключено ради автоматизации; компенсируется guardrail'ом на границе записи.

## Учёт токенов

При каждом ответе модели из Responses API снимается поле `usage` (`input_tokens`, `output_tokens`) и передаётся в `append-message` при записи ответа агента в таблицу `messages` (`tokens_in`/`tokens_out`).

- Поллер (`email-poller`) после ответа модели:
  - логирует `USAGE in=… out=…`;
  - если в этом ходе создан тикет (`mcp_call create-ticket`) — дописывает ответ агента в историю: `append-message` (`role=agent`, `text`=ответ, `model`, `tokens_in`=`usage.input_tokens`, `tokens_out`=`usage.output_tokens`);
  - вызывает CF `ydb-tickets` напрямую по IAM-токену SA.
- Сверка: `usage` из трейса == `messages.tokens_in/tokens_out` (значение передаётся как есть — расхождение ≤10% гарантировано; на практике 0%).
- Таблица `messages` хранит `tokens_in`/`tokens_out`/`model`/`latency_ms` для записей `role=agent` — для разбора и учёта токенов (модель сама токены не знает, их снимает поллер).

Полная картина по последним записям:

| Тикет | Источник | usage (лог поллера) | messages (in/out) | Совпало |
|---|---|---|---|---|
| `d50bdb24` | письмо (end-to-end) | in=2159, out=86 | 2159 / 86 | ✅ (0%) |
| `90cbc81f` | тест | in=2017, out=99 | 2017 / 99 | ✅ (0%) |
| `fd54ddff` | тест | in=2017, out=101 | 2017 / 101 | ✅ (0%) |

## Роли SA
- lockbox.payloadViewer
- ai.languageModels.user
- serverless.mcpGateways.invoker
- serverless.mcpGateways.anonymousInvoker
- serverless.workflows.executor
- ydb.editor
- ai.languageModels.user
- search-api.webSearch.user
- serverless.mcpGateways.invoker
- functions.functionInvoker
- ai.editor

## Трейсинг и скриншоты

Наблюдаемость решения: трейсы/логи каждого компонента + скриншоты для сдачи.

- `tracing/` — собранные трейсы:
  - `email-poller.log` — почтовый агент (inline Responses API: `mcp_list_tools`, `mcp_call create-ticket`, финальный текст);
  - `mcp-gateway.log` — MCP gateway `ydb-tickets-mcp` (`MCP session started`, `Tools listed`, `Tool call started/finished`);
  - `daily-escalation_execution.json` — результат выполнения workflow (`result.result_json`);
  - `negative-scenarios.md` — проверка негативных сценариев (injection, обращение вне базы, недоступность YDB, PII-маскирование);
  - `README.md` — команды снятия каждого трейса.
- `screenshots/` — скриншоты из консоли: AI Studio **Traces** сохранённого агента, таблицы YDB и т.п.

Для сохранённого агента трейсы — вкладка **Traces** в AI Studio; для inline-вызовов поллера — массив `output[]` ответа Responses API (`mcp_list_tools`, `mcp_call`, `message`).
