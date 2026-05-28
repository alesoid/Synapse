# ADR-004: Orchestration — LangGraph

**Статус:** Принято  
**Дата:** 11 мая 2026  
**Автор:** Алеся Мороз

---

## Контекст

Synapse реализует агентную архитектуру с циклами, условными переходами и Self-Reflection. Требования к оркестратору:

- Stateful агент — сохранение состояния между нодами (AgentState)
- Циклы и conditional edges — retry при низком качестве ответа
- Наблюдаемость — трейсинг каждой ноды через Langfuse
- Явное разделение Control Plane и Data Plane
- Не линейные цепочки (требование задания)
- Поддержка Self-Reflection паттерна (ReAct / Plan-and-Solve)

---

## Решение

**LangGraph 0.2+** — stateful граф выполнения на основе StateGraph.

**AgentState** (16 полей, `backend/agents/state.py`):
```python
class AgentState(TypedDict):
    query: str                          # исходный запрос пользователя
    access_level: int                   # уровень доступа 1–5 (из X-User-Role)
    entities: list[str]                 # онтологически нормализованные сущности (FR-41a)
    query_rewritten: str                # документо-ориентированная переформулировка (для vector search)
    vector_chunks: list[RetrievedChunk] # результаты Qdrant
    graph_results: list[GraphResult]    # результаты Neo4j
    sources: list[MergedSource]         # гибридный merge (α=0.7 vector + 0.3 graph)
    role_hint: str                      # ролевая подсказка для генератора
    answer: str
    quality_score: float                # оценка критика 1.0–4.0
    confidence_score: float             # актуальность источников 0–1
    iterations: int
    gap_detected: bool
    trace_id: str
```

**StateGraph топология** (11 узлов, `backend/agents/graph_agent.py`):
```
START
  → prepare_query          (strip + extract_entities)
  → query_rewriter         (LLM: вопрос → поисковые термины)
  → [dispatch_retrievers Send()] ──┬── vector_retriever (Qdrant, использует query_rewritten)
                                   └── graph_retriever  (Neo4j, использует entities)
                                             ↓
                                       merge_results    (α=0.7/0.3 hybrid)
                                             ↓
                                       role_context     (детерминированная ролевая подсказка)
                                             ↓
                                         generator
                                             ↓
                                           critic       (LLM-as-a-Judge, few-shot, 1.0–4.0)
                                             ↓
                                     confidence_score
                                    ↙        ↓          ↘
                    (retry) [Send()]   output_guard   knowledge_gap
                         ↓               → END           → END
                  vector_retriever
                + graph_retriever
```

> **Безопасность:** `input_guard` отсутствует как LangGraph-нода. Инъекции и PII маскируются в `QueryRequest.strip_and_guard_query` (FastAPI, `api/schemas.py`) **до** вызова `run_agent()`. `prepare_query` — preprocessing only (strip + entity extraction), не security gate.

**Conditional edge should_retry** (`backend/agents/nodes.py`):
```python
def should_retry(self, state: AgentState) -> str | list[Send]:
    quality = state["quality_score"]
    iterations = state["iterations"]
    if quality < self._s.agent_retry_quality_threshold and iterations < self._s.agent_max_iterations:
        return [Send("vector_retriever", state), Send("graph_retriever", state)]
    if quality < self._s.agent_gap_quality_threshold:
        return "knowledge_gap"
    return "output_guard"
```

---

## Альтернативы рассмотрены

| Вариант | Плюсы | Минусы | Решение |
|---|---|---|---|
| **LangChain LCEL (линейные цепочки)** | Простой синтаксис, богатая экосистема LangChain, низкий порог входа | Нет поддержки циклов и conditional edges, запрещены условием задания | **Отклонён** |
| **LlamaIndex Workflows** | Хорошая интеграция с LlamaIndex компонентами, event-driven подход | Менее гибкий State management, меньше контроль над графом выполнения | **Отклонён** |
| **AutoGen** | Мощные multi-agent сценарии, активное развитие Microsoft | Сложнее контролировать поток выполнения, избыточен для single-agent сценария | **Отклонён** |
| **Crew AI** | Удобная абстракция для командных агентов, декларативный DSL | Multi-agent фреймворк — избыточен, сложнее отлаживать для MVP | **Отклонён** |
| **Собственная реализация** | Полный контроль, нет внешних зависимостей | Высокие затраты времени, нет готовой интеграции с Langfuse, нет визуализации | **Отклонён** |
| **Haystack Pipelines** | Зрелый фреймворк, хорошая документация | Менее гибкий для циклических агентов, меньше community в РФ | **Отклонён** |

---

## Trade-offs

**Плюсы LangGraph:**
- Полный контроль над State и графом выполнения
- Нативная интеграция с Langfuse через CallbackHandler
- Визуализация графа: `agent.get_graph().print_ascii()`
- Conditional edges — retry логика без хаков
- Активное развитие (Anthropic, LangChain team)
- Совместимость с LangChain инструментами (embeddings, document loaders)

**Минусы LangGraph:**
- Более крутая кривая обучения чем LCEL
- API меняется между минорными версиями (фиксируем версию в requirements.txt)
- Меньше примеров на русском языке

---

## Последствия

- Агент реализован в `/backend/agents/` как StateGraph
- Каждая нода — отдельная функция с чётким input/output из AgentState
- Максимум 3 итерации retry — защита от бесконечного цикла
- ASCII граф агента выводится в логах при старте для верификации топологии
- Langfuse CallbackHandler добавляется при инициализации агента
- В Scale-этапе: переход на Multi-Agent архитектуру без смены фреймворка

---

## Compliance & Ethics

**Регуляторное соответствие:**
- LangGraph выполняется полностью локально, не обращается к внешним серверам LangChain — соответствие **ФЗ-152** и принципу Zero external APIs обеспечено
- Используется open source версия под лицензией **MIT** — коммерческое использование допустимо без ограничений
- Трейсинг через Langfuse развёртывается self-hosted (PostgreSQL) — данные о запросах пользователей не покидают периметр

**Этические риски и меры снижения:**
- Риск бесконечного цикла при нестабильной работе LLM. Мера: жёсткое ограничение `iterations < 3` в conditional edge, принудительный выход в `knowledge_gap` при исчерпании итераций
- Риск prompt injection через запрос пользователя, который может изменить поведение агента. Мера: `QueryRequest.strip_and_guard_query` (FastAPI `api/schemas.py`) блокирует инъекции на HTTP-уровне до вызова `run_agent()` — принцип Security enforced before inference. LangGraph-граф физически не получает вредоносные запросы.
- Все решения агента (quality_score, gap_detected, выбранные ноды) сохраняются в AgentState и логируются в Langfuse — обеспечивается полная объяснимость и аудируемость каждого ответа
