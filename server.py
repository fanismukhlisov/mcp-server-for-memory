"""MCP-сервер: экономия контекста и VRAM для локальных LLM.

Запуск (stdio):
    python -m context_saver_mcp.server
или:
    context-saver-mcp
"""
from __future__ import annotations

import re
from typing import Iterable

from mcp.server.fastmcp import FastMCP

try:
    from .storage import MemoryStorage       # когда запущено как модуль
except ImportError:
    from storage import MemoryStorage       # когда запущено как скрипт

mcp = FastMCP("ContextSaver")
storage = MemoryStorage()


# =========================================================
# 💾 ДОЛГОВРЕМЕННАЯ ПАМЯТЬ
# =========================================================

@mcp.tool()
def save_fact(content: str, category: str = "", tags: str = "") -> str:
    """Сохранить факт / решение / фрагмент кода в долговременную память.

    Args:
        content: Текст факта (до 100 КБ).
        category: Категория (например, 'architecture', 'bug', 'decision').
        tags: Теги через запятую (например, 'api,db,migration').
    """
    if not content.strip():
        return "Ошибка: пустой content."
    if len(content) > 100_000:
        return "Ошибка: content > 100 КБ. Сожмите через compress_text()."

    fact_id = storage.save(content, category, tags)
    preview = content[:80].replace("\n", " ")
    return f"✅ Сохранено (id={fact_id}): {preview}…"


@mcp.tool()
def recall_facts(keyword: str, limit: int = 3) -> str:
    """Найти факты по ключевому слову (LIKE-поиск, быстрый).

    Args:
        keyword: Ключевое слово или подстрока.
        limit: Максимум результатов (1–10).
    """
    limit = max(1, min(limit, 10))
    rows = storage.recall(keyword, limit)
    if not rows:
        return f"Ничего не найдено по '{keyword}'."
    return _format_rows(rows)


@mcp.tool()
def search_facts(query: str, limit: int = 5) -> str:
    """Полнотекстовый поиск (FTS5 + BM25-ранжирование).

    Args:
        query: Поисковый запрос (поддерживает синтаксис FTS5:
               'error AND handling', 'auth*', 'json OR yaml').
        limit: Максимум результатов (1–20).
    """
    limit = max(1, min(limit, 20))
    try:
        rows = storage.search(query, limit)
    except Exception as e:
        return f"Ошибка поиска: {e}. Попробуйте простой запрос без спецсимволов."
    if not rows:
        return f"Ничего не найдено по '{query}'."
    return _format_rows(rows)


@mcp.tool()
def list_recent(limit: int = 10) -> str:
    """Показать последние сохранённые факты.

    Args:
        limit: Сколько показать (1–50).
    """
    limit = max(1, min(limit, 50))
    rows = storage.recent(limit)
    if not rows:
        return "Память пуста."
    return _format_rows(rows)


@mcp.tool()
def forget_fact(fact_id: int) -> str:
    """Удалить факт по ID.

    Args:
        fact_id: ID факта (из get_stats / recall_facts / list_recent).
    """
    ok = storage.forget(fact_id)
    return f"🗑️ Удалён факт id={fact_id}." if ok else f"Факт id={fact_id} не найден."


@mcp.tool()
def get_stats() -> str:
    """Статистика памяти: количество фактов, категории, размер БД."""
    s = storage.stats()
    lines = [
        f"📊 Всего фактов: {s['total_facts']}",
        f"💾 БД: {s['db_path']} ({s['db_size_bytes']:,} байт)",
    ]
    if s["by_category"]:
        lines.append("📂 По категориям:")
        for cat, n in s["by_category"].items():
            lines.append(f"   • {cat}: {n}")
    return "\n".join(lines)


# =========================================================
# 🗜️ СЖАТИЕ КОНТЕКСТА
# =========================================================

@mcp.tool()
def compress_text(text: str, max_tokens: int = 500) -> str:
    """Умное усечение текста под бюджет токенов (head + tail).

    Сохраняет начало (контекст задачи) и конец (вывод/результат),
    вырезая середину. Грубая оценка: 1 токен ≈ 4 символа.

    Args:
        text: Исходный текст (лог, файл, вывод инструмента).
        max_tokens: Целевой бюджет в токенах (50–8000).
    """
    max_tokens = max(50, min(max_tokens, 8000))
    budget_chars = max_tokens * 4

    if len(text) <= budget_chars:
        return text

    head_chars = int(budget_chars * 0.6)
    tail_chars = budget_chars - head_chars

    head = text[:head_chars]
    tail = text[-tail_chars:]

    omitted_chars = len(text) - len(head) - len(tail)
    marker = (
        f"\n\n... [сжато {omitted_chars:,} символов "
        f"(~{omitted_chars // 4:,} токенов)] ...\n\n"
    )
    return head + marker + tail


@mcp.tool()
def dedupe_texts(texts: list[str]) -> str:
    """Удалить дубликаты из списка фрагментов (точное совпадение).

    Args:
        texts: Список фрагментов.
    """
    seen: set[str] = set()
    unique: list[str] = []
    for t in texts:
        key = t.strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(t)
    removed = len(texts) - len(unique)
    if removed:
        header = f"[удалено дубликатов: {removed}]\n\n"
    else:
        header = "[дубликатов не найдено]\n\n"
    return header + "\n---\n".join(unique)


@mcp.tool()
def filter_relevant(
    chunks: list[str],
    query: str,
    max_chunks: int = 3,
) -> str:
    """Фильтрация фрагментов по релевантности (простой BM25-подобный скоринг).

    Каждый фрагмент оценивается по частоте терминов запроса с учётом
    длины фрагмента. Возвращаются top-N.

    Args:
        chunks: Список фрагментов (например, результаты поиска, файлы).
        query: Запрос, по которому фильтруем.
        max_chunks: Сколько оставить (1–20).
    """
    if not chunks:
        return "Пустой список фрагментов."

    max_chunks = max(1, min(max_chunks, 20))
    terms = [t.lower() for t in re.findall(r"\w+", query) if len(t) > 2]
    if not terms:
        return "\n---\n".join(chunks[:max_chunks])

    scored: list[tuple[float, str]] = []
    for ch in chunks:
        low = ch.lower()
        length_norm = max(len(low), 1) ** 0.5
        score = sum(low.count(t) for t in terms) / length_norm
        scored.append((score, ch))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = [ch for s, ch in scored[:max_chunks] if s > 0] or [ch for _, ch in scored[:max_chunks]]

    header = f"[отобрано {len(top)} из {len(chunks)} по запросу '{query}']\n\n"
    return header + "\n---\n".join(top)


# =========================================================
# helpers
# =========================================================

def _format_rows(rows: Iterable) -> str:
    blocks = []
    for r in rows:
        meta_parts = [f"id={r['id']}"]
        if r["category"]:
            meta_parts.append(f"cat={r['category']}")
        if r["tags"]:
            meta_parts.append(f"tags={r['tags']}")
        meta_parts.append(r["created_at"])
        meta = " | ".join(meta_parts)
        blocks.append(f"[{meta}]\n{r['content']}")
    return "\n\n---\n\n".join(blocks)


def main() -> None:
    """Точка входа (stdio-транспорт — то, что нужно LM Studio Bionic)."""
    mcp.run()


if __name__ == "__main__":
    main()
