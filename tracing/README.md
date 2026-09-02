# Трейсы (наблюдаемость)

Файлы трейсов по компонентам, собранные 2026-09-02 (поток «создание тикета» через почту).

| Файл | Компонент | Источник |
|---|---|---|
| `email-poller.log` | Почтовый агент (inline Responses API) | `yc logging read` |
| `mcp-gateway.log` | MCP gateway `ydb-tickets-mcp` | `yc logging read` |
| `daily-escalation_execution.json` | Workflow `daily-escalation` | `yc serverless workflow execution get` |
| AI Studio UI | Сохранённый агент — вкладка **Traces**; для inline Responses API — массив `output[]` в ответе (`mcp_list_tools`, `mcp_call`, `message`) | консоль aistudio.yandex.ru (вручную) |

## Как снимать

**Email poller** (CF `email-poller`, id = `d4e4tudkcrg535jrnp0o`):
```bash
yc logging read --group-name default --resource-ids d4e4tudkcrg535jrnp0o --since 30m --limit 100
```
Видны диагностика Responses API: `mcp_list_tools`, `mcp_call name=create-ticket`, финальный текст с номером заявки.
(GOT_UNSEEN / MSG / AGENT_OK / SEND_OK — это INFO-логи поллера; в логах CF по умолчанию видны WARNING+.)

**Workflow `daily-escalation`**:
```bash
yc serverless workflow execution list --workflow-name daily-escalation
yc serverless workflow execution get <execution_id>          # result.result_json / error.message
```

**MCP gateway** (id = `db818p5vs9tr2fb1rdtj`):
```bash
yc logging read --group-name default --resource-ids db818p5vs9tr2fb1rdtj --since 30m
```
Видны: `MCP session started`, `Tools listed`, `Tool call started`, `Tool call finished`.

**AI Studio UI** — для сохранённого агента: вкладка **Traces** в профиле агента (путь workflow `aiStudioAgent`); для inline-вызовов поллера трейс = массив `output[]` из ответа Responses API (типы `mcp_list_tools`, `mcp_call` с `arguments` и `output`, `message`).
