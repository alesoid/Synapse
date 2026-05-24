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

**AgentState:**
```python
class AgentState(TypedDict):
    query: str
    access_level: int
    documents: list[dict]
    answer: str
    quality_score: float
    confidence_score: float
    iterations: int
    sources: list[dict]
    gap_detected: bool
```

**StateGraph топология:**
```
START
  → input_guard
  → retrieve
  → grade_documents
  → generate
  → confidence_score
  → self_reflection
  ↙ (quality >= 3)    ↘ (quality < 3, iterations < 3)
output_guard         retrieve (retry)
  → END              
  
self_reflection → knowledge_gap (quality < 2, max iterations)
  → END
```

**Conditional edge:**
```python
def should_retry(state: AgentState) -> str:
    if state["quality_score"] < 3 and state["iterations"] < 3:
        return "retrieve"
    elif state["quality_score"] < 2:
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
- Риск prompt injection через запрос пользователя, который может изменить поведение агента. Мера: нода `input_guard` выполняется первой в графе — до передачи запроса в retrieval и LLM (принцип Security enforced before inference)
- Все решения агента (quality_score, gap_detected, выбранные ноды) сохраняются в AgentState и логируются в Langfuse — обеспечивается полная объяснимость и аудируемость каждого ответа
