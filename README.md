# mcp-server-for-memory

MCP-сервер долговременной памяти и экономии контекста для локальных LLM (внутреннее имя — **ContextSaver**).

## Возможности

- **Долговременная память** — хранение фактов/решений/фрагментов кода в SQLite с полнотекстовым поиском FTS5.
- **Сжатие контекста** — урезание текста под бюджет токенов, удаление дубликатов, фильтрация фрагментов по релевантности.

## Инструменты

| Инструмент | Назначение |
|---|---|
| `save_fact(content, category, tags)` | Сохранить факт в память |
| `recall_facts(keyword, limit=3)` | Быстрый поиск по ключевому слову (LIKE) |
| `search_facts(query, limit=5)` | Полнотекстовый поиск FTS5 + BM25-ранжирование |
| `list_recent(limit=10)` | Последние сохранённые факты |
| `forget_fact(fact_id)` | Удалить факт по ID |
| `get_stats()` | Статистика памяти (кол-во фактов, категории, размер БД) |
| `compress_text(text, max_tokens=500)` | Урезать текст под бюджет токенов (head + tail) |
| `dedupe_texts(texts)` | Удалить точные дубликаты из списка фрагментов |
| `filter_relevant(chunks, query, max_chunks=3)` | Отобрать top-N фрагментов по релевантности |

## Запуск (stdio)

```bash
python server.py
```

База данных создаётся автоматически в `~/.context-saver/memory.db`. Путь можно переопределить переменной окружения `CONTEXT_SAVER_DB`.

## Подключение к MCP-клиенту

Пример конфигурации (stdio-транспорт):

```json
{
  "mcpServers": {
    "memory": {
      "command": "python",
      "args": ["/абсолютный/путь/to/server.py"]
    }
  }
}
```

## Требования

- Python 3.9+ (используются `from __future__ import annotations`)
- Пакет `mcp` с FastMCP: `pip install mcp`
