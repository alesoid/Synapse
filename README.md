# Synapse

> Корпоративная платформа интеллектуального анализа знаний на основе GraphRAG

Synapse — on-premise система для поиска по корпоративным документам, работающая полностью в закрытом контуре без внешних API. Гибридный GraphRAG: 0.7 × векторный поиск (Qdrant) + 0.3 × графовый траверсал (Neo4j) с RBAC на уровне чанков.

---

## Статус MVP (защита 3 июня 2026)

| Фаза | Статус | Описание |
|------|--------|----------|
| Корпус документов | ✅ | 15 документов, 5 уровней доступа (access_level 1–5) |
| Ingestion pipeline | ✅ | Markdown → chunks → Qdrant + Neo4j (mock/real) |
| Query pipeline | ✅ | Vector + Graph retrieval → merge 0.7/0.3 → LLM |
| LangGraph агент | ✅ | 9 нод, retry до 3 итераций, knowledge gap detection |
| RBAC | ✅ | 5 ролей, 3 слоя: API guard + Qdrant filter + Neo4j WHERE |
| Guardrails | ✅ | Injection blocking (HTTP 422), input validation |
| UI | ✅ | SPA на Tailwind + Vanilla JS, role selector, sources, graph view |
| Observability | ✅ | Langfuse + Prometheus + Grafana (docker-compose profile) |
| Golden dataset | ✅ | 32 вопроса: positive/negative/rbac/injection |
| Eval scripts | ✅ | eval_golden.py, eval_rbac.py, eval_comparison.py, load_test.py |

### Результаты тестирования (local-lite / mock mode)

| Тест | Результат |
|------|-----------|
| Unit tests | 30/30 PASS |
| RBAC leakage | 0% (0/10 restricted probes leaked) |
| Knowledge gap detection | 6/6 PASS |
| Injection blocking | 3/3 PASS (HTTP 422) |
| Load test P95 (5 workers, mock) | 32 ms |
| Load test RPS (5 workers, mock) | 207 RPS |

---

## Стек

| Компонент | Технология |
|-----------|-----------|
| LLM (gpu-demo) | vLLM + Qwen2.5-14B-AWQ |
| LLM (local-lite) | mock (deterministic) |
| Embeddings | nomic-embed-text (mock в local-lite) |
| Vector DB | Qdrant v1.9 |
| Graph DB | Neo4j 5.18 Community |
| Orchestration | LangGraph 0.6 |
| API | FastAPI + Pydantic v2 |
| Frontend | Tailwind CDN + Vanilla JS SPA |
| Observability | Langfuse + Prometheus + Grafana |
| Infra | Docker Compose (profiles) |

---

## Быстрый старт

### local-lite (Mac, без GPU, без Docker)

```bash
# 1. Установить зависимости
pip install -e ".[dev]"

# 2. Запустить сервер
uvicorn backend.api.main:app --host 0.0.0.0 --port 8000

# 3. Открыть UI
open http://localhost:8000/ui/

# 4. Запросить документ
curl -X POST http://localhost:8000/query \
  -H "X-User-Role: junior" \
  -H "Content-Type: application/json" \
  -d '{"query": "Кто отвечает за выдачу IT-доступов при онбординге?"}'
```

### local-lite (Docker)

```bash
cd infra
cp .env.example .env
docker compose --profile local-lite up -d
open http://localhost:8000/ui/
```

### gpu-demo (RTX 4090 + полный стек)

```bash
cd infra
cp .env.example .env
# Заполнить HF_TOKEN для загрузки Qwen2.5-14B-AWQ
docker compose --profile gpu --profile observability up -d

# Индексация корпуса
curl -X POST http://localhost:8000/ingest \
  -H "X-User-Role: admin" \
  -H "Content-Type: application/json"
```

---

## Оценка качества

```bash
# Unit tests
python -m pytest tests/ -v

# Golden dataset (32 вопроса)
python scripts/eval_golden.py --url http://localhost:8000

# RBAC leakage (0% цель)
python scripts/eval_rbac.py --url http://localhost:8000

# GraphRAG vs vector-only (требует GPU стек с индексированным корпусом)
python scripts/eval_comparison.py --url http://localhost:8000

# Load test (P50/P95/P99)
python scripts/load_test.py --url http://localhost:8000 --concurrency 5 --duration 30
```

Отчёты сохраняются в `docs/evaluation/results/`.

---

## Структура репозитория

```
synapse/
├── backend/
│   ├── agents/          # LangGraph агент (graph_agent.py)
│   ├── api/             # FastAPI роуты, RBAC guard, injection filter
│   ├── core/            # Settings (pydantic-settings + lru_cache)
│   ├── embeddings/      # Embedding adapter (mock / nomic-embed-text)
│   ├── ingestion/       # Markdown corpus → chunks → storage
│   ├── llm/             # LLM client (mock / vLLM)
│   ├── observability/   # Langfuse tracing
│   ├── query/           # Pipeline, CriticAgent, entity extractor
│   ├── retrieval/       # VectorRetriever + GraphRetriever
│   └── security/        # RBAC roles и access_level маппинг
├── frontend/            # SPA: index.html (Tailwind CDN + Vanilla JS)
├── infra/
│   ├── docker-compose.yml    # Profiles: local-lite | gpu | observability | proxy
│   ├── .env.example
│   ├── prometheus.yml
│   └── grafana/
├── scripts/
│   ├── eval_golden.py        # Golden dataset runner (32 вопроса)
│   ├── eval_rbac.py          # RBAC leakage tester (цель 0%)
│   ├── eval_comparison.py    # GraphRAG vs vector-only
│   └── load_test.py          # Async load test (P50/P95/P99)
├── tests/               # 30 unit + integration тестов
└── docs/
    ├── CONCEPT.md
    ├── TECHNICAL_SPEC.md
    ├── corpus/          # 15 корпоративных документов (access_level 1–5)
    └── evaluation/
        ├── golden_dataset.jsonl    # 32 вопроса (positive/negative/rbac/injection)
        ├── poc_comparison.md       # GraphRAG vs vector-only методология
        ├── load_test_report.md     # Результаты нагрузочного теста
        └── results/                # Timestamped eval reports
```

---

## Роли и доступ

| Роль | Уровень | Header | Документы |
|------|---------|--------|-----------|
| Junior | 1 | `X-User-Role: junior` | INS-HR-001, INS-HR-002, POL-HR-001 |
| Middle | 2 | `X-User-Role: middle` | + STD-ENG-001, STD-ENG-002, STD-ENG-003 |
| Senior | 3 | `X-User-Role: senior` | + STD-ARCH-001, STD-ARCH-002, POL-ARCH-001 |
| Manager | 4 | `X-User-Role: manager` | + POL-SEC-001, POL-SEC-002, POL-MGR-001 |
| Admin | 5 | `X-User-Role: admin` | Все + POL-SEC-003, POL-SEC-004, POL-SEC-005 |

---

## Сервисы и порты

| Сервис | URL | Профиль |
|--------|-----|---------|
| UI | http://localhost:8000/ui/ | local-lite / gpu |
| API + Swagger | http://localhost:8000/docs | all |
| Neo4j Browser | http://localhost:7474 | gpu / storage |
| Qdrant | http://localhost:6333 | gpu / storage |
| Langfuse | http://localhost:3000 | observability |
| Grafana | http://localhost:3001 | observability |
| Prometheus | http://localhost:9090 | observability |

---

## Демо-сценарии (защита)

**Сценарий 1 — Q&A с источниками:**  
role=junior → вопрос про онбординг → ответ со ссылкой INS-HR-001, confidence_score, quality_score

**Сценарий 2 — RBAC блокировка:**  
role=junior → вопрос про POL-SEC-001 (уровень manager) → пустой ответ, no sources

**Сценарий 3 — Knowledge Gap:**  
Любая роль → вопрос о командировках → gap_detected=true, "запрос зафиксирован"

**Сценарий 4 — Injection Guard:**  
"Ignore previous instructions..." → HTTP 422, Query blocked by security policy

**Сценарий 5 — Admin Graph View:**  
role=admin → UI → Graph Panel → таблица нод и рёбер, ссылка на Neo4j Browser

**Сценарий 6 — Observability:**  
Grafana: latency P95, RPS, knowledge_gap_total  
Langfuse: breakdown по нодам агента (vector_retriever, critic, etc.)

---

## Лицензия

MIT
