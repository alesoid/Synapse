# ADR-012: Multi-Agent Architecture — Orchestrator + Parallel Retrievers + Critic

**Статус:** Принято  
**Дата:** 11 мая 2026  
**Автор:** Алеся Мороз

---

## Scope

| Этап | Что реализовано | Статус |
|---|---|---|
| **MVP** | `prepare_query`, параллельный fan-out через `dispatch_retrievers` + `Send()`, `vector_retriever`, `graph_retriever`, `generator`, `critic` (LLM-as-a-Judge), retry через `should_retry` | ✅ Текущее решение |
| **Scale** | Добавление специализированных агентов по типу документа (PolicyAgent, TechnicalAgent, HRAgent); SupervisorAgent для маршрутизации по доменам | 🔜 Вне скоупа MVP |

---

## Контекст

Исходная архитектура Synapse — single-agent StateGraph, где один агент последовательно выполняет векторный поиск, граф-траверсал, генерацию и self-reflection. Это порождает два системных ограничения:

1. **Последовательный retrieval** — векторный поиск и граф-траверсал выполняются один за другим, хотя они независимы. Суммарная latency = latency(Qdrant) + latency(Neo4j).
2. **Self-assessment bias** — агент оценивает качество собственного ответа. Модель склонна завышать оценку своей же генерации, что снижает эффективность Self-Reflection и retry-логики.

Задание явно требует реализации паттерна **Multi-Agent Collaboration** и **LLM-as-a-Judge** (unit-тесты на промпты). Переход на мультиагентную архитектуру закрывает оба требования без замены фреймворка (LangGraph поддерживает `Send()` API для параллельного запуска субагентов).

---

## Решение

**Четыре специализированных агента**, координируемых через LangGraph `Send()` API:

| Нода / Компонент | Роль | Входные данные | Выходные данные |
|---|---|---|---|
| `prepare_query` | Preprocessing: strip, нормализация, извлечение сущностей | `query`, `access_level` | `entities` |
| `query_rewriter` | LLM-переформулировка запроса в документо-ориентированный стиль (улучшение recall) | `query` | `query_rewritten` |
| `dispatch_retrievers` (conditional edge) | Fan-out: запускает ретриверы параллельно через `Send()` | `state` | `[Send("vector_retriever", ...), Send("graph_retriever", ...)]` |
| `vector_retriever` | Семантический поиск в Qdrant с RBAC фильтром | `query_rewritten`, `access_level` | `vector_chunks` |
| `graph_retriever` | Traversal в Neo4j по сущностям запроса с RBAC фильтром | `entities`, `access_level` | `graph_results` |
| `merge_results` | Hybrid merge RRF (α=0.7 вектор, 0.3 граф, k=60) | `vector_chunks`, `graph_results` | `sources` |
| `role_context` | Детерминированная ролевая подсказка для генератора (L1–L5) | `access_level` | `role_hint` |
| `generator` | Генерация ответа с контекстом и ролевым фокусом | `query`, `sources`, `role_hint` | `answer`, `trace_id` |
| `critic` | Независимая оценка качества (LLM-as-a-Judge, few-shot) | `query`, `answer`, `sources` | `quality_score`, `critic_feedback`, `iterations` |
| `confidence_score` | Вычисление актуальности источников по дате | `sources` | `confidence_score` |
| `should_retry` (conditional edge) | Маршрутизация после оценки | `quality_score`, `iterations` | `list[Send]` (retry) / `"knowledge_gap"` / `"output_guard"` |
| `output_guard` | PII маскирование ответа (FR-27) | `answer` | очищенный `answer` |
| `knowledge_gap` | Фиксация Knowledge Gap в SQLite | `query`, `quality_score` | `gap_detected=True` |

### Топология StateGraph

```
START
  └→ prepare_query          (strip + extract_entities → entities)
       └→ query_rewriter     (LLM: вопрос → поисковые термины → query_rewritten)
            └→ [dispatch_retrievers Send()] ──┬── vector_retriever ──┐  (использует query_rewritten)
                                              └── graph_retriever  ──┴→ merge_results  (использует entities)
                                                                              └→ role_context    (детерминированный → role_hint)
                                                                                   └→ generator
                                                                                        └→ critic (few-shot LLM-as-a-Judge)
                                                                                             └→ confidence_score
                                                                                                  ├─ (quality ≥ threshold)             → output_guard → END
                                                                                                  ├─ (quality < threshold, iter < max)  → [should_retry Send()] → generator (generator-only retry)
                                                                                                  └─ (quality < gap_threshold)          → knowledge_gap → END
```

> Безопасность на входе (PII маскирование, injection блок) реализована в FastAPI слое (`QueryRequest.strip_and_guard_query`), до вызова агента — не как отдельная LangGraph нода.

### Реализация параллельного retrieval через Send()

В LangGraph fan-out через `Send()` реализуется как **conditional edge function** — не как отдельный узел (`add_node`). Функция `dispatch_retrievers` регистрируется через `add_conditional_edges` и возвращает список `Send` объектов:

```python
from langgraph.constants import Send

# dispatch_retrievers — conditional edge от prepare_query (не нода графа)
def dispatch_retrievers(self, state: AgentState) -> list[Send]:
    """Fan-out: запускает vector_retriever и graph_retriever параллельно (FR-45)."""
    return [
        Send("vector_retriever", state),
        Send("graph_retriever", state),
    ]

def merge_results(self, state: AgentState) -> dict:
    """Объединяет результаты обоих ретриверов (RRF: alpha=0.7 вектор, 0.3 граф, k=60)."""
    sources = _merge(
        state["vector_chunks"],
        state["graph_results"],
        alpha=self._s.hybrid_alpha,
    )
    return {"sources": sources}
```

### CriticAgent — LLM-as-a-Judge

Промпт критика использует **few-shot** технику для стабильности оценок (`backend/query/critic.py`):

```python
_SYSTEM_PROMPT = (
    "Ты оцениваешь качество ответа корпоративного AI-ассистента. "
    "Верни ответ строго в формате: ЧИСЛО | ПОЯСНЕНИЕ\n"
    "где ЧИСЛО — оценка от 1.0 до 4.0, ПОЯСНЕНИЕ — одно предложение на русском.\n\n"
    "Шкала:\n"
    "4.0 — полный конкретный ответ, цитирует документы, все ключевые детали есть\n"
    "3.0 — частичный ответ, упоминает документы, но не все детали раскрыты\n"
    "2.0 — слабый ответ, общие слова без ссылок на источники\n"
    "1.0 — нет ответа, «информация не найдена» или источников 0\n\n"
    "Пример:\n"
    "→ 4.0 | Конкретный ответ с указанием документа и ответственного лица"
)
```

Парсинг ответа через `_parse_score_and_feedback()` — извлекает число и пояснение из формата `ЧИСЛО | ПОЯСНЕНИЕ`. Fallback: если пояснение отсутствует — генерируется синтетическое `"Оценка X.X / 4.0 (N источн.)"`. Невалидный ответ → fallback на `MockCriticAgent` (source-count heuristic).

### Conditional edge should_retry

`should_retry` также является conditional edge function (от `confidence_score`). При retry она возвращает `list[Send]` прямо в `generator`, пропуская retrieval-ноды:

```python
def should_retry(self, state: AgentState) -> str | list[Send]:
    quality = state["quality_score"]
    iterations = state["iterations"]
    if quality < retry_threshold and iterations < max_iterations:
        # Generator-only retry: источники уже в state, critic_feedback передаётся как retry_feedback
        # Retrieval пропускается — экономия ~1-2 с latency на повторный запрос к Qdrant/Neo4j
        return [Send("generator", state)]
    if quality < gap_threshold:
        return "knowledge_gap"
    return "output_guard"
```

**Стратегия retry:** при низком качестве перезапускается только `generator`, не ретриверы. Источники уже в `state["sources"]`; `critic_feedback` передаётся как `retry_feedback` в промпт генератора. Re-retrieval полезен только если retrieval изначально не нашёл релевантных чанков — этот случай обрабатывается ветвью `knowledge_gap`.

### Сборка графа

Ключевой момент: `dispatch_retrievers` и `should_retry` регистрируются через `add_conditional_edges`, а **не** через `add_node`. Они не являются узлами — это routing functions, выполняемые на рёбрах графа.

```python
workflow = StateGraph(AgentState)

# Узлы (11 нод)
workflow.add_node("prepare_query",    nodes.prepare_query)   # strip + entities
workflow.add_node("query_rewriter",   nodes.query_rewriter)  # LLM: query → search terms
workflow.add_node("vector_retriever", nodes.vector_retriever)
workflow.add_node("graph_retriever",  nodes.graph_retriever)
workflow.add_node("merge_results",    nodes.merge_results)
workflow.add_node("role_context",     nodes.role_context)    # детерминированный role_hint
workflow.add_node("generator",        nodes.generator)
workflow.add_node("critic",           nodes.critic)
workflow.add_node("confidence_score", nodes.confidence_score)
workflow.add_node("output_guard",     nodes.output_guard)
workflow.add_node("knowledge_gap",    nodes.knowledge_gap)

# Рёбра
workflow.add_edge(START, "prepare_query")
workflow.add_edge("prepare_query", "query_rewriter")
workflow.add_conditional_edges("query_rewriter", nodes.dispatch_retrievers)  # fan-out Send()
workflow.add_edge("vector_retriever", "merge_results")                       # fan-in
workflow.add_edge("graph_retriever",  "merge_results")                       # fan-in
workflow.add_edge("merge_results",    "role_context")
workflow.add_edge("role_context",     "generator")
workflow.add_edge("generator",        "critic")
workflow.add_edge("critic",           "confidence_score")
workflow.add_conditional_edges(
    "confidence_score",
    nodes.should_retry,
    {"knowledge_gap": "knowledge_gap", "output_guard": "output_guard"},
)
workflow.add_edge("output_guard",  END)
workflow.add_edge("knowledge_gap", END)
```

> Безопасность на входе (injection + PII) — в `QueryRequest.strip_and_guard_query` (FastAPI layer, до вызова `run_agent()`). Output guard — нода `output_guard` в конце pipeline.

---

## Альтернативы рассмотрены

| Вариант | Плюсы | Минусы | Решение |
|---|---|---|---|
| **Single-agent (исходный)** | Проще реализация и отладка, меньше точек отказа | Последовательный retrieval (+latency), self-assessment bias в оценке качества | **Заменён** |
| **Supervisor + доменные агенты (PolicyAgent, TechnicalAgent, HRAgent)** | Специализация промптов под тип документа | Требует классификатора запросов, 3 отдельных LLM-вызова, избыточно для MVP корпуса | **Отклонён для MVP**, приоритет Scale |
| **AutoGen Multi-Agent** | Готовый фреймворк для агентного взаимодействия | Смена фреймворка с LangGraph, сложнее интеграция с Langfuse и существующим стеком | **Отклонён** |
| **Crew AI** | Декларативный DSL для команд агентов | Смена фреймворка, избыточен для 4 агентов с простой топологией | **Отклонён** |
| **Параллельный retrieval без отдельных агентов (asyncio.gather)** | Проще реализация, нет overhead LangGraph Send() | Не является мультиагентной архитектурой — не закрывает требование задания | **Отклонён** |

---

## Trade-offs

**Плюсы мультиагентной архитектуры:**
- Параллельный retrieval: latency = max(Qdrant, Neo4j) вместо sum — ожидаемый выигрыш ~30-40% на retrieval шаге
- CriticAgent устраняет self-assessment bias: независимая модель оценивает ответ объективнее
- CriticAgent = LLM-as-a-Judge: закрывает требование задания на unit-тесты промптов
- Разделение ответственности: каждый агент имеет один чёткий промпт, проще тестировать и заменять
- Без смены фреймворка: LangGraph `Send()` API — нативная поддержка параллельных субагентов

**Минусы:**
- +1 LLM-вызов на каждый запрос (CriticAgent) — увеличивает latency и потребление токенов
- Сложнее отладка: при ошибке нужно определить в каком из 4 агентов сбой
- `Send()` API требует аккуратной обработки состояния: оба ретривера пишут в один AgentState, нужна защита от race condition при merge

---

## Последствия

- `/backend/agents/` разбит на `graph_agent.py` (топология), `nodes.py` (все ноды + routing functions), `state.py` (AgentState)
- AgentState содержит 16 полей: добавлены `entities`, `query_rewritten`, `role_hint`, `trace_id`, `critic_feedback` (объяснение оценки от CriticAgent, передаётся через `QueryResult` → `QueryResponse` → UI)
- Langfuse трейсы теперь показывают 4 отдельных агента — более детальная наблюдаемость latency каждого
- Метрика `tokens_per_request` увеличивается на ~200-400 токенов (CriticAgent промпт + ответ)
- В Scale: добавление SupervisorAgent и доменных агентов без изменения топологии — новые ноды в существующем графе

---

## Compliance & Ethics

**Регуляторное соответствие:**
- Все агенты выполняются локально в одном Python процессе — данные не покидают периметр, **ФЗ-152** соблюдён
- RBAC применяется в каждом ретривере независимо: `vector_retriever` и `graph_retriever` оба получают `access_level` и применяют фильтр до передачи результатов в `merge_results`

**Этические риски и меры снижения:**
- Риск противоречия между нодами `generator` и `critic`: `generator` выдаёт ответ, `critic` его отклоняет — пользователь может получить сообщение о низком качестве без полезного контента. Мера: при `quality_score < gap_threshold` после max итераций система явно сообщает о Knowledge Gap (FR-34), а не возвращает пустой ответ
- Риск того что CriticAgent сам галлюцинирует при оценке. Мера: Critic работает в JSON mode с ограниченным форматом ответа; невалидный JSON → fallback на `quality_score=2.5` (нейтральная оценка, без retry)
- Все решения CriticAgent (score, feedback) логируются в Langfuse — полная аудируемость оценки качества каждого ответа
