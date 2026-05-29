# Synapse — Статус реализации MVP

**Последнее обновление:** 29 мая 2026  
**Целевая дата защиты:** 3 июня 2026  
**Этап:** MVP завершён

> **Статусы:**
> - ✅ Готово — реализовано и проверено smoke/unit/integration тестом или ручной проверкой
> - 🔄 В работе — начато, не завершено
> - ⏳ Не начато — запланировано
> - 🚫 Отложено — перенесено в Scale

---

## MVP Strategy

Проект реализуется в двух режимах:

| Режим | Среда | Цель |
|---|---|---|
| `local-lite` | Mac, без GPU | Разработка, mock LLM, mock embeddings, unit/integration tests |
| `gpu-demo` | RTX 4090 24 GB VRAM | Финальное демо с vLLM, Qdrant, Neo4j, Langfuse, evaluation и load test |

Главный приоритет MVP — стабильный End-to-End GraphRAG pipeline: ingestion → retrieval → RBAC → generation → sources → observability → evaluation.

---

## Прогресс по фазам

| Фаза | Готово | Всего | % |
|---|---:|---:|---:|
| Phase 1 — Local-lite skeleton | 5 | 6 | 83% |
| Phase 2 — Ingestion и данные | 6 | 7 | 86% |
| Phase 3 — Query pipeline | 9 | 9 | 100% |
| Phase 4 — LangGraph | 4 | 4 | 100% |
| Phase 5 — UI | 4 | 4 | 100% |
| Phase 6 — GPU demo | 7 | 8 | 88% |
| Phase 7 — Evidence для защиты | 4 | 5 | 80% |
| **Итого** | **39** | **43** | **91%** |

---

## MVP Critical Path Checklist

### Phase 1 — Local-lite skeleton

| ID | Задача | Статус | Проверка |
|---|---|---|---|
| L1 | Создать FastAPI app | ✅ Готово | `GET /health` возвращает `ok` |
| L2 | Env-переключатели `LLM_BACKEND=mock`, `EMBEDDINGS_BACKEND=mock` | ✅ Готово | `/health` показывает backends |
| L3 | Role mapping `X-User-Role → access_level` | ✅ Готово | role guard на `/query`, `/ingest`, `/graph`, `/knowledge-gaps`, `/ontology` |
| L4 | Mock LLM client | ✅ Готово | `/query` возвращает deterministic skeleton response |
| L5 | Mock/легковесные embeddings | ✅ Готово | deterministic SHA-256 embeddings |
| L6 | Console/noop tracing mode | ✅ Готово | OTel + Langfuse Cloud: трейсы видны в cloud.langfuse.com |

### Phase 2 — Ingestion и данные

| ID | Задача | Статус | Проверка |
|---|---|---|---|
| D1 | Читать `corpus_manifest.json` | ✅ Готово | `load_markdown_corpus` загружает 15 документов |
| D2 | Читать Markdown из `docs/corpus/` | ✅ Готово | Markdown-файлы читаются по `filename` из manifest |
| D3 | Chunking 500/50 | ✅ Готово | chunks содержат `doc_id`, `access_level`, `section_title`, `text` |
| D4 | Запись chunks в Qdrant | ✅ Готово | Qdrant collection `chunks` содержит 262 points |
| D5 | Запись Document/Section в Neo4j | ✅ Готово | Neo4j содержит 346 nodes |
| D6 | Создание связей для графа | ✅ Готово | Neo4j содержит 1654 edges (`HAS_SECTION`, `REFERENCES`) |
| D7 | Загрузка `ontology.json` | 🚫 Отложено | canonical entities — Scale-этап |

### Phase 3 — Query pipeline

| ID | Задача | Статус | Проверка |
|---|---|---|---|
| Q1 | Input Guardrails | ✅ Готово | HTTP 422 через Pydantic validator; injection pattern заблокирован до агента |
| Q2 | VectorRetrieverAgent | ✅ Готово | Qdrant RBAC filter; нода `vector_retriever` в трейсе |
| Q3 | GraphRetrieverAgent | ✅ Готово | Neo4j traversal; нода `graph_retriever` в трейсе |
| Q4 | RRF merge (alpha=0.7, k=60) | ✅ Готово | нода `merge_results`; sources отсортированы по score |
| Q5 | GeneratorAgent mock/vLLM | ✅ Готово | нода `generator`; единый интерфейс для mock и vLLM |
| Q6 | CriticAgent | ✅ Готово | нода `critic`; возвращает `quality_score` (1.0–4.0) |
| Q7 | `confidence_score` | ✅ Готово | нода `confidence_score`; вычисляется по `last_updated` |
| Q8 | Knowledge Gap Detection | ✅ Готово | `quality_score < 2` → запись в SQLite; `GET /knowledge-gaps` |
| Q9 | Output Guardrails | ✅ Готово | нода `output_guard` |

### Phase 4 — LangGraph

| ID | Задача | Статус | Проверка |
|---|---|---|---|
| G1 | Собрать StateGraph | ✅ Готово | 11 нод; pipeline проходит E2E |
| G2 | Именованные ноды: `prepare_query`, `query_rewriter`, `vector_retriever`, `graph_retriever`, `role_context`, `merge_results`, `generator`, `critic`, `confidence_score`, `output_guard` | ✅ Готово | spans видны в Langfuse |
| G3 | Retry до 3 итераций | ✅ Готово | `quality_score < 3` вызывает retry |
| G4 | Knowledge Gap branch | ✅ Готово | `quality_score < 2` ведёт в gap detection |

### Phase 5 — UI

| ID | Задача | Статус | Проверка |
|---|---|---|---|
| U1 | Q&A UI | ✅ Готово | SPA: Tailwind CSS + Vanilla JS; смонтирован на `/ui` |
| U2 | Отображение sources | ✅ Готово | `doc_id`, `section`, `retrieval_score` видны в UI |
| U3 | Отображение `confidence_score` | ✅ Готово | score и предупреждение об устаревании |
| U4 | Graph view | ✅ Готово | вкладка Explorer: таблица нод/рёбер + ссылка на Neo4j Browser |

### Phase 6 — GPU demo

| ID | Задача | Статус | Проверка |
|---|---|---|---|
| INF1 | Makefile для нативного запуска без Docker/sudo | ✅ Готово | `make start-gpu`, `make restart-gpu`, `make status` |
| INF2 | local-lite режим (без GPU) | ✅ Готово | `uvicorn backend.api.main:app`; mock mode |
| INF3 | Docker Compose профили | 🔄 Частично | `local-lite` ✅; `gpu`/`observability` — Docker не используется на сервере |
| INF4 | Observability stack | ✅ Готово | Langfuse Cloud (OTel + CallbackHandler); `/metrics` (Prometheus-формат) |
| GPU1 | vLLM + Qwen2.5-14B-AWQ | ✅ Готово | `/v1/models` отвечает; `make start-vllm` |
| GPU2 | Full E2E query на vLLM | ✅ Готово | streaming ответ с источниками; latency ~8s |
| OBS1 | Langfuse traces | ✅ Готово | ноды pipeline видны в cloud.langfuse.com |
| OBS2 | Prometheus metrics | ✅ Готово | `http_requests_total`, LLM-метрики на `/metrics` |

### Phase 7 — Evidence для защиты

| ID | Задача | Статус | Проверка |
|---|---|---|---|
| E1 | Golden dataset run (32 вопроса) | ✅ Готово | `docs/evaluation/results/` |
| E2 | GraphRAG vs vector-only comparison | ✅ Готово | `docs/evaluation/poc_comparison.md` |
| E3 | RBAC/security eval | ✅ Готово | leakage rate = 0%; 0/10 restricted probes leaked |
| E4 | Load test (P50/P95/P99) | ✅ Готово | `docs/evaluation/load_test_report.md`; P95 = 32ms (mock) |
| E5 | Demo video 5–6 минут | 🔄 В работе | сценарий готов: `docs/demo_script_v2.md` |

---

## MVP Acceptance Tracker

| AC | Критерий | Статус | Evidence |
|---|---|---|---|
| AC-01 | `local-lite` запускается без GPU; `gpu-demo` на RTX 4090 | ✅ Готово | `make status` показывает все ✅ |
| AC-02 | Вопрос на русском → ответ с источниками | ✅ Готово | 46/46 unit tests PASS; golden dataset |
| AC-03 | RBAC leakage = 0% | ✅ Готово | `eval_rbac.py`; 0/10 restricted probes leaked |
| AC-04 | Knowledge Graph > 50 узлов и > 100 рёбер | ✅ Готово | 346 nodes, 1654 edges |
| AC-05 | Langfuse показывает trace с нодами pipeline | ✅ Готово | cloud.langfuse.com → Tracing |
| AC-06 | Нет обращений к внешним API в runtime | ✅ Готово | vLLM локально; Langfuse Cloud только для observability |
| AC-07 | Диаграммы и ADR синхронизированы с MVP | 🔄 В работе | openapi.yaml и ADR-011/013 требуют обновления |
| AC-08 | ADR-пакет содержит trade-off analysis | ✅ Готово | `docs/ADR/` |
| AC-09 | Load test report с P95/RPS/error rate | ✅ Готово | `docs/evaluation/load_test_report.md` |
| AC-10 | Demo video 5–7 минут | 🔄 В работе | сценарий: `docs/demo_script_v2.md` |
| AC-11 | Knowledge Gap фиксируется | ✅ Готово | `GET /knowledge-gaps` → status: open |
| AC-12 | `confidence_score` и предупреждение при старых источниках | ✅ Готово | API response |
| AC-13 | Онтология загружена, дубли canonical name отсутствуют | 🔄 Частично | граф нормализован; `ontology.json` — Scale |

---

## Журнал изменений

| Дата | Что изменилось |
|---|---|
| 17.05.2026 | Создан файл, baseline статус |
| 21.05.2026 | MVP-стратегия: `local-lite` на Mac + `gpu-demo` на RTX 4090 |
| 29.05.2026 | Полное обновление статусов: Phase 3–7 завершены; injection guard HTTP 422; Langfuse Cloud; нативный запуск через Makefile |
