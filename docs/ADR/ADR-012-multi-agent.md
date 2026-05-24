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
| `prepare_query` | Preprocessing: strip, нормализация, извлечение сущностей | `query`, `access_level` | обогащённый `state` |
| `dispatch_retrievers` (conditional edge) | Fan-out: запускает ретриверы параллельно через `Send()` | `state` | `[Send("vector_retriever", ...), Send("graph_retriever", ...)]` |
| `vector_retriever` | Семантический поиск в Qdrant с RBAC фильтром | `query`, `access_level` | `vector_chunks` |
| `graph_retriever` | Traversal в Neo4j по сущностям запроса с RBAC фильтром | `query`, `access_level` | `graph_results` |
| `merge_results` | Hybrid merge 0.7/0.3 | `vector_chunks`, `graph_results` | `documents` |
| `generator` | Генерация ответа на основе контекста | `query`, `documents` | `answer`, `sources` |
| `critic` | Независимая оценка качества ответа (LLM-as-a-Judge) | `query`, `answer`, `documents` | `quality_score`, `critic_feedback` |
| `confidence_score` | Вычисление актуальности источников | `sources` | `confidence_score` |
| `should_retry` (conditional edge) | Маршрутизация после оценки | `quality_score`, `iterations` | `list[Send]` (retry) / `"knowledge_gap"` / `"output_guard"` |
| `output_guard` | PII маскирование ответа | `answer` | очищенный `answer` |
| `knowledge_gap` | Фиксация Knowledge Gap в SQLite | `query`, `quality_score` | — |

### Топология StateGraph

```
START
  └→ prepare_query
       └→ [dispatch_retrievers Send()] ──┬── vector_retriever ──┐
                                         └── graph_retriever  ──┴→ merge_results
                                                                        └→ generator
                                                                             └→ critic
                                                                                  └→ confidence_score
                                                                                       ├─ (quality ≥ threshold)            → output_guard → END
                                                                                       ├─ (quality < threshold, iter < max) → [should_retry Send()] → vector_retriever
                                                                                       │                                                            → graph_retriever
                                                                                       └─ (quality < gap_threshold)         → knowledge_gap → END
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
    """Объединяет результаты обоих ретриверов (hybrid merge 0.7/0.3)."""
    return {
        "documents": hybrid_merge(
            state["vector_chunks"],
            state["graph_results"],
            alpha=float(os.getenv("HYBRID_ALPHA", "0.7"))
        )
    }
```

### CriticAgent — LLM-as-a-Judge

```python
CRITIC_PROMPT = """Ты независимый эксперт по оценке качества ответов.

Вопрос: {query}
Ответ: {answer}
Источники: {sources}

Оцени ответ по критериям (каждый от 1 до 5):
1. Релевантность: насколько ответ соответствует вопросу
2. Полнота: все ли аспекты вопроса раскрыты
3. Обоснованность: подтверждён ли каждый факт источником

Верни JSON: {{"score": float, "feedback": str, "missing": list[str]}}
"""

def critic_agent(state: AgentState) -> AgentState:
    response = llm.invoke(CRITIC_PROMPT.format(
        query=state["query"],
        answer=state["answer"],
        sources=state["sources"]
    ))
    result = json.loads(response.content)
    return {
        **state,
        "quality_score": result["score"],
        "critic_feedback": result["feedback"],
        "iterations": state["iterations"] + 1
    }
```

### Conditional edge should_retry

`should_retry` также является conditional edge function (от `confidence_score`). При retry она возвращает `list[Send]` для повторного fan-out прямо в `vector_retriever` / `graph_retriever`, минуя `prepare_query`:

```python
def should_retry(self, state: AgentState) -> str | list[Send]:
    quality = state["quality_score"]
    iterations = state["iterations"]
    if quality < retry_threshold and iterations < max_iterations:
        return [                             # retry — повторный параллельный retrieval
            Send("vector_retriever", state),
            Send("graph_retriever", state),
        ]
    if quality < gap_threshold:
        return "knowledge_gap"
    return "output_guard"
```

### Сборка графа

Ключевой момент: `dispatch_retrievers` и `should_retry` регистрируются через `add_conditional_edges`, а **не** через `add_node`. Они не являются узлами — это routing functions, выполняемые на рёбрах графа.

```python
workflow = StateGraph(AgentState)

# Узлы (ноды) графа
workflow.add_node("prepare_query",    nodes.prepare_query)
workflow.add_node("vector_retriever", nodes.vector_retriever)
workflow.add_node("graph_retriever",  nodes.graph_retriever)
workflow.add_node("merge_results",    nodes.merge_results)
workflow.add_node("generator",        nodes.generator)
workflow.add_node("critic",           nodes.critic)
workflow.add_node("confidence_score", nodes.confidence_score)
workflow.add_node("output_guard",     nodes.output_guard)
workflow.add_node("knowledge_gap",    nodes.knowledge_gap)

# Рёбра
workflow.add_edge(START, "prepare_query")
workflow.add_conditional_edges("prepare_query", nodes.dispatch_retrievers)  # fan-out Send()
workflow.add_edge("vector_retriever", "merge_results")                      # fan-in
workflow.add_edge("graph_retriever",  "merge_results")                      # fan-in
workflow.add_edge("merge_results",    "generator")
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
- AgentState расширяется полями `vector_results`, `graph_results`, `critic_feedback`
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
