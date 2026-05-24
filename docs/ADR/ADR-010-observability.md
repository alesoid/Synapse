# ADR-010: Observability — OpenTelemetry + Langfuse + Prometheus + Grafana

**Статус:** Принято  
**Дата:** 11 мая 2026  
**Автор:** Алеся Мороз

---

## Scope

| Этап | Что реализовано | Статус |
|---|---|---|
| **MVP** | OpenTelemetry SDK (инструментирование FastAPI + LangGraph), Langfuse как OTel-совместимый backend (LLM трейсы + Knowledge Gaps), Prometheus (метрики), Grafana (дашборд) — все self-hosted | ✅ Текущее решение |
| **Scale** | OTel Collector как централизованный роутер трейсов (→ Langfuse, → Jaeger, → любой backend); alerting через Grafana Alertmanager; distributed tracing при переходе на микросервисы | 🔜 Вне скоупа MVP |

---

## Контекст

Synapse требует наблюдаемости на двух уровнях:

1. **LLM-уровень** — трейсинг каждой ноды LangGraph агента: latency, токены, качество ответа, knowledge gaps. Стандартный APM (Prometheus/Grafana) не понимает семантику LLM-пайплайнов.
2. **Инфраструктурный уровень** — RPS, latency P95, error rate, tokens/sec. Нужны метрики для нагрузочного отчёта (AC-09) и видео-демо (AC-10).

Задание явно требует **OpenTelemetry** для трейсинга запросов. Единый инструмент, закрывающий оба уровня, не существует — требуется комбинация. OpenTelemetry выступает единым стандартом инструментирования, не привязывая систему к конкретному backend.

---

## Решение

**OpenTelemetry как стандарт инструментирования** + специализированные backend-инструменты:

| Инструмент | Роль |
|---|---|
| **OpenTelemetry SDK** | Стандартное инструментирование: трейсы и метрики экспортируются в едином формате |
| **Langfuse** | OTel-совместимый LLM backend: принимает трейсы через OTLP, добавляет LLM-семантику (токены, quality_score, Knowledge Gaps) |
| **Prometheus** | Сбор числовых метрик: `request_latency_seconds`, `request_count_total`, `tokens_per_second` |
| **Grafana** | Визуализация метрик Prometheus, дашборд для демо и нагрузочного отчёта |

### Инструментирование через OpenTelemetry

```python
# /backend/observability/tracing.py
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

def setup_tracing(app):
    """Настройка OTel трейсинга — экспорт в Langfuse через OTLP."""
    provider = TracerProvider()

    # Langfuse принимает трейсы через OTLP endpoint
    otlp_exporter = OTLPSpanExporter(
        endpoint=os.getenv("LANGFUSE_OTLP_ENDPOINT",
                           "http://langfuse:3000/api/public/otel/v1/traces"),
        headers={
            "Authorization": f"Basic {os.getenv('LANGFUSE_PUBLIC_KEY')}"
        }
    )
    provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
    trace.set_tracer_provider(provider)

    # Автоматическое инструментирование FastAPI
    FastAPIInstrumentor.instrument_app(app)

tracer = trace.get_tracer("synapse.agent")
```

```python
# Ручная инструментация LangGraph нод
from opentelemetry import trace

tracer = trace.get_tracer("synapse.agent")

def vector_retriever(state: AgentState) -> AgentState:
    with tracer.start_as_current_span("vector_retriever") as span:
        span.set_attribute("user.access_level", state["access_level"])
        span.set_attribute("query.length", len(state["query"]))

        results = qdrant_search(state["query"], state["access_level"])

        span.set_attribute("retrieval.results_count", len(results))
        return {**state, "vector_results": results}

def critic_agent(state: AgentState) -> AgentState:
    with tracer.start_as_current_span("critic_agent") as span:
        # LLM-вызов через Langfuse CallbackHandler (дополняет OTel трейс)
        result = llm.invoke(CRITIC_PROMPT, callbacks=[langfuse_handler])

        span.set_attribute("critic.quality_score", result["score"])
        span.set_attribute("critic.iterations", state["iterations"])
        return {**state, "quality_score": result["score"]}
```

```python
# Prometheus метрики (параллельно с OTel — для Grafana дашборда)
from prometheus_client import Histogram, Counter

request_latency = Histogram(
    "synapse_request_latency_seconds",
    "E2E latency запроса",
    buckets=[1, 2, 5, 10, 30, 60]
)
request_counter = Counter(
    "synapse_requests_total",
    "Количество запросов",
    ["role", "status"]
)
tokens_per_second = Histogram(
    "synapse_tokens_per_second",
    "Скорость генерации токенов"
)
```

### Итоговая схема потоков данных

```
FastAPI запрос
    │
    ├─ OTel SDK автоинструментация → OTLP → Langfuse (трейсы нод, LLM метаданные)
    │
    ├─ LangGraph ноды (ручные spans) → OTLP → Langfuse
    │
    └─ prometheus_client → /metrics → Prometheus → Grafana (RPS, latency, tokens/sec)
```

---

## Альтернативы рассмотрены

| Вариант | Плюсы | Минусы | Решение |
|---|---|---|---|
| **Только Prometheus + Grafana (без OTel)** | Один стек, проще администрировать | Не понимает семантику LLM; не выполняет требование задания по OTel | **Отклонён** |
| **OTel Collector + Jaeger** | Полный distributed tracing стандарт, визуализация трейсов | Нет LLM-специфичных концепций (токены, quality_score); лишний сервис для MVP | **Отклонён для MVP**, Jaeger заменяется Langfuse как OTel backend |
| **LangSmith (LangChain)** | Нативная интеграция с LangGraph, богатый UI | Облачный сервис — данные покидают периметр, нарушает ФЗ-152 | **Отклонён** (блокер по безопасности) |
| **Arize Phoenix** | Self-hosted, OTel-совместимый LLM observability | Менее зрелый чем Langfuse, меньше примеров интеграции с LangGraph | **Отклонён** |
| **ELK Stack** | Мощный поиск по логам | Тяжёлый стек, избыточен для MVP | **Отклонён** |

---

## Trade-offs

**Плюсы OTel + Langfuse + Prometheus + Grafana:**
- OpenTelemetry — vendor-neutral стандарт: при смене backend (Langfuse → Jaeger → любой) меняется только конфигурация экспортёра, не код инструментирования
- Langfuse принимает трейсы через OTLP — выполняет требование задания по OTel без отдельного OTel Collector сервиса
- FastAPIInstrumentor автоматически инструментирует все HTTP-запросы без изменения кода роутеров
- Langfuse self-hosted на PostgreSQL — данные не покидают периметр
- Langfuse хранит Knowledge Gaps (FR-32) — двойное использование одного сервиса
- Prometheus + Grafana — industry standard для инфраструктурных метрик

**Минусы:**
- Два канала данных параллельно: OTel → Langfuse (трейсы) и prometheus_client → Prometheus (метрики) — нет единого UI
- Langfuse требует PostgreSQL — добавляет сервис в стек
- Ручная инструментация LangGraph нод (OTel spans) требует дополнительного кода в каждой ноде агента

---

## Последствия

- Новые зависимости: `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`, `opentelemetry-instrumentation-fastapi`
- `setup_tracing(app)` вызывается при старте FastAPI в `main.py`
- Каждая LangGraph нода оборачивается в `tracer.start_as_current_span()`
- `docker-compose.yml` включает: langfuse, langfuse-worker, postgres, prometheus, grafana
- Prometheus scrape config настроен на `/metrics` эндпоинт FastAPI
- Grafana дашборд преднастроен и хранится в `docs/grafana_dashboard.json`
- Knowledge Gaps сохраняются в Langfuse PostgreSQL и читаются через `GET /knowledge-gaps`
- В Scale: добавление OTel Collector контейнера позволяет роутить трейсы в несколько backend одновременно без изменения кода

---

## Compliance & Ethics

**Регуляторное соответствие:**
- Langfuse развёртывается self-hosted — трейсы запросов (включая тексты пользователей) хранятся локально, не передаются в Langfuse Cloud
- Prometheus и Grafana — open source (Apache 2.0) без телеметрии
- Трейсы содержат тексты запросов пользователей — хранение регулируется политикой retention (рекомендуется 90 дней для MVP)

**Этические риски и меры снижения:**
- Риск хранения PII в трейсах Langfuse (имена, контакты из запросов). Мера: Input Guardrail маскирует PII до передачи в агент — в трейс попадает уже обезличенный запрос
- Риск доступа к трейсам (история запросов всех пользователей) через Langfuse UI. Мера: Langfuse UI защищён паролем; в Scale — интеграция с корпоративным SSO
