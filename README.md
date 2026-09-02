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

- Разное

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
