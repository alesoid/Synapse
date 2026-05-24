# Synapse — Статус реализации MVP

**Последнее обновление:** 21 мая 2026  
**Целевая дата защиты:** 3 июня 2026  
**Целевой срок готовности gpu-demo:** 30 мая 2026  
**Этап:** MVP implementation

> **Статусы:**
> - ✅ Готово — реализовано и проверено smoke/unit/integration тестом или ручной проверкой
> - 🔄 В работе — начато, не завершено
> - ⏳ Не начато — запланировано
> - ❌ Заблокировано — есть зависимость или проблема
> - 🚫 Отложено — перенесено в Scale

---

## MVP Strategy

Проект реализуется в двух режимах:

| Режим | Среда | Цель |
|---|---|---|
| `local-lite` | Mac M3 8 GB RAM | Разработка, mock LLM, mock/lightweight embeddings, smoke-тесты, unit/integration tests |
| `gpu-demo` | Docker на RTX 4090 24 GB VRAM | Финальное демо с vLLM, Qdrant, Neo4j, Langfuse, Prometheus/Grafana, evaluation и load test |

Главный приоритет MVP — стабильный End-to-End GraphRAG pipeline: ingestion → retrieval → RBAC → generation → sources → observability → evaluation.

---

## Прогресс по фазам

| Фаза | Готово | Всего | % |
|---|---:|---:|---:|
| Phase 1 — Local-lite skeleton | 5 | 6 | 83% |
| Phase 2 — Ingestion и данные | 6 | 7 | 86% |
| Phase 3 — Query pipeline | 0 | 9 | 0% |
| Phase 4 — LangGraph | 0 | 4 | 0% |
| Phase 5 — UI | 0 | 4 | 0% |
| Phase 6 — Docker и GPU demo | 2 | 8 | 25% |
| Phase 7 — Evidence для защиты | 0 | 5 | 0% |
| **Итого** | **13** | **43** | **30%** |

---

## MVP Critical Path Checklist

### Phase 1 — Local-lite skeleton на Mac M3

| ID | Задача | Статус | Проверка |
|---|---|---|---|
| L1 | Создать FastAPI app | ✅ Готово | `GET /health` возвращает `ok`; `pytest tests/test_health.py` |
| L2 | Добавить env-переключатели `LLM_BACKEND=mock`, `EMBEDDINGS_BACKEND=mock` | ✅ Готово | backend стартует без LLM; `/health` показывает backends |
| L3 | Реализовать role mapping `X-User-Role -> access_level` | ✅ Готово | role guard добавлен для `/query`, `/ingest`, `/graph`, `/knowledge-gaps`, `/ontology` |
| L4 | Реализовать mock LLM client | ✅ Готово | `/query` возвращает deterministic skeleton response через mock backend |
| L5 | Реализовать mock/легковесные embeddings | ✅ Готово | deterministic SHA-256 embeddings; `pytest tests/test_local_lite.py` |
| L6 | Добавить console/noop tracing mode | ⏳ Не начато | spans печатаются в console |

### Phase 2 — Ingestion и данные

| ID | Задача | Статус | Проверка |
|---|---|---|---|
| D1 | Читать `docs/corpus/corpus_manifest.json` | ✅ Готово | `load_markdown_corpus` загружает 15 документов; `pytest tests/test_ingestion.py` |
| D2 | Читать Markdown из `docs/corpus/adapted` | ✅ Готово | Markdown-файлы читаются по `filename` из manifest |
| D3 | Chunking 500/50 | ✅ Готово | chunks содержат `doc_id`, `doc_type`, `access_level`, `last_updated`, `section_title`, `text` |
| D4 | Запись chunks в Qdrant | ✅ Готово | Qdrant collection `chunks` содержит 262 points |
| D5 | Запись Document/Section в Neo4j | ✅ Готово | Neo4j содержит 349 nodes |
| D6 | Создание связей для графа | ✅ Готово | Neo4j содержит 1656 edges (`HAS_SECTION`, `REFERENCES`) |
| D7 | Загрузка `ontology.json` | ⏳ Не начато | canonical entities доступны в коде |

### Phase 3 — Query pipeline

| ID | Задача | Статус | Проверка |
|---|---|---|---|
| Q1 | Input Guardrails | ⏳ Не начато | q-030 возвращает HTTP 400 |
| Q2 | VectorRetrieverAgent | 🔄 В работе | Qdrant RBAC filter реализован; подключение к `/query` впереди |
| Q3 | GraphRetrieverAgent | 🔄 В работе | Neo4j traversal wrapper реализован; подключение к `/query` впереди |
| Q4 | Merge `0.7 vector + 0.3 graph` | ⏳ Не начато | sources отсортированы по score |
| Q5 | GeneratorAgent mock/vLLM adapter | ⏳ Не начато | один интерфейс для mock и vLLM |
| Q6 | CriticAgent mock/vLLM adapter | ⏳ Не начато | возвращает `quality_score` |
| Q7 | `confidence_score` | ⏳ Не начато | вычисляется по `last_updated` |
| Q8 | Knowledge Gap Detection | ⏳ Не начато | negative question попадает в `/knowledge-gaps` |
| Q9 | Output Guardrails | ⏳ Не начато | PII редактируется в ответе |

### Phase 4 — LangGraph

| ID | Задача | Статус | Проверка |
|---|---|---|---|
| G1 | Собрать StateGraph | ⏳ Не начато | pipeline проходит один запрос |
| G2 | Именованные ноды: `input_guard`, `vector_retriever`, `graph_retriever`, `merge_results`, `generator`, `critic`, `confidence_score`, `output_guard` | ⏳ Не начато | spans/logs содержат node names |
| G3 | Retry до 3 итераций | ⏳ Не начато | low quality вызывает retry |
| G4 | Knowledge Gap branch | ⏳ Не начато | `quality_score < 2` ведёт в gap |

### Phase 5 — UI

| ID | Задача | Статус | Проверка |
|---|---|---|---|
| U1 | Минимальный Q&A UI | ⏳ Не начато | роль + вопрос + ответ |
| U2 | Отображение sources | ⏳ Не начато | видны doc_id/section |
| U3 | Отображение `confidence_score` | ⏳ Не начато | score виден в UI |
| U4 | Минимальный Graph view или ссылка на Neo4j Browser | ⏳ Не начато | admin видит граф |

### Phase 6 — Docker и GPU demo

| ID | Задача | Статус | Проверка |
|---|---|---|---|
| INF1 | Backend Dockerfile | ✅ Готово | backend image собран через Docker Compose |
| INF2 | Compose profile `local-lite` | ✅ Готово | `docker compose --profile local-lite up backend`; `/health` вернул `ok` |
| INF3 | Compose profile `gpu` | ⏳ Не начато | vLLM доступен на порту 8001 |
| INF4 | Compose profile `observability` | ⏳ Не начато | Langfuse/Grafana открываются |
| GPU1 | vLLM + Qwen2.5-14B-AWQ | ⏳ Не начато | `/v1/models` отвечает |
| GPU2 | Full E2E query на vLLM | ⏳ Не начато | ответ с источниками |
| OBS1 | Langfuse traces | ⏳ Не начато | видны ноды pipeline |
| OBS2 | Prometheus/Grafana metrics | ⏳ Не начато | latency/RPS/tokens/sec |


### Phase 7 — Evidence для защиты

| ID | Задача | Статус | Проверка |
|---|---|---|---|
| E1 | Golden dataset run | ⏳ Не начато | `eval_report.md` создан |
| E2 | GraphRAG vs vector-only comparison | ⏳ Не начато | `poc_comparison.md` создан |
| E3 | RBAC/security eval | ⏳ Не начато | leakage rate = 0% |
| E4 | Load test на 4090 | ⏳ Не начато | `load_test_report.md` создан |
| E5 | Demo video 5-7 минут | ⏳ Не начато | видео записано |

---

## Синхронизация документации

| Документ | Статус | Комментарий |
|---|---|---|
| `docs/TECHNICAL_SPEC.md` | 🔄 В работе | Осталось убрать противоречия OCR/Explorer/форматы ingestion |
| `docs/CONCEPT.md` | 🔄 В работе | Остались точечные правки PoC/Scale/ограничения |
| `README.md` | ⏳ Не начато | Привести Quick Start и структуру репозитория к фактическому MVP |
| `docs/api/openapi.yaml` | ⏳ Не начато | Сверить с реализованными endpoint-ами |
| `docs/evaluation_plan.md` | ⏳ Не начато | Сверить команды запуска eval с фактическими scripts |
| `docs/demo_script.md` | ⏳ Не начато | Обновить под реальные demo-сценарии |
| `docs/load_test_report.md` | ⏳ Не начато | Создать после тестов на RTX 4090 |

---

## MVP Acceptance Tracker

| AC | Критерий | Статус | Evidence |
|---|---|---|---|
| AC-01 | `local-lite` запускается без GPU; `gpu-demo` запускается на RTX 4090 | ⏳ Не проверено | compose logs / screenshots |
| AC-02 | Вопрос на русском → ответ с источниками | ⏳ Не проверено | golden dataset run |
| AC-03 | RBAC leakage = 0% | 🔄 В работе | `tests/test_rbac.py`; нужна интеграционная проверка retrieval |
| AC-04 | Knowledge Graph содержит >50 узлов и >100 рёбер или зафиксировано обоснованное MVP-значение | ⏳ Не проверено | Neo4j query result |
| AC-05 | Langfuse показывает trace с нодами pipeline | ⏳ Не проверено | screenshot / trace_id |
| AC-06 | Нет обращений к внешним API в runtime | ⏳ Не проверено | network logs / config review |
| AC-07 | Диаграммы и ADR синхронизированы с MVP | ⏳ Не проверено | docs review |
| AC-08 | ADR-пакет содержит trade-off analysis | ✅ Готово | `docs/ADR/` |
| AC-09 | Load test report с P95/RPS/error rate | ⏳ Не проверено | `docs/load_test_report.md` |
| AC-10 | Demo video 5-7 минут | ⏳ Не проверено | video artifact |
| AC-11 | Knowledge Gap фиксируется | ⏳ Не проверено | `/knowledge-gaps` response |
| AC-12 | `confidence_score` и предупреждение при старых источниках | ⏳ Не проверено | API response |
| AC-13 | Онтология загружена, дубли canonical name отсутствуют | ⏳ Не проверено | Neo4j query result |

---

## Заблокированные задачи

| Задача | Причина | Зависимость |
|---|---|---|
| — | — | — |

---

## Журнал изменений

| Дата | Что изменилось |
|---|---|
| 17.05.2026 | Создан файл, baseline статус |
| 21.05.2026 | Зафиксирована MVP-стратегия: `local-lite` на Mac M3 8 GB и `gpu-demo` на RTX 4090; добавлен Critical Path checklist |
| 21.05.2026 | Добавлен backend skeleton: FastAPI routes, env settings, backend Dockerfile, smoke-тест `/health` |
| 21.05.2026 | Добавлен local-lite режим: mock LLM, mock embeddings, `STORAGE_BACKEND=mock`, compose profile `local-lite` |
| 21.05.2026 | Добавлен Markdown corpus ingestion: manifest loader, chunking 500/50, mock graph projection, Qdrant/Neo4j writer skeleton |
| 21.05.2026 | Добавлен RBAC слой: role mapping, endpoint guards, Qdrant RBAC filter, Neo4j graph retriever wrapper, unit-тесты RBAC |
