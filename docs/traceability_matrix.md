# Traceability Matrix — Synapse GraphRAG Knowledge Platform

**Версия:** 1.0  
**Дата:** 17 мая 2026  
**Автор:** Алеся Мороз  
**Статус:** Baseline

---

## 1. Назначение

Матрица трассируемости связывает требования из `TECHNICAL_SPEC.md` с архитектурными решениями, API-контрактами, планируемыми модулями реализации, проверками и критериями приёмки.

Цель документа — показать, что каждое ключевое требование MVP имеет:

- архитектурное покрытие;
- решение или ADR;
- точку реализации;
- способ проверки;
- критерий приёмки.

---

## 2. Статусы

| Статус | Значение |
|---|---|
| `Designed` | Требование покрыто архитектурой, ADR/API/диаграммами; реализация ещё не подтверждена |
| `Planned` | Требование требует реализации и/или отчёта после MVP |
| `Optional` | Should Have / опциональный MVP scope |
| `Post-MVP Evidence` | Документальное подтверждение возможно только после запуска тестов |

---

## 3. Functional / AI / Security Requirements

| ID | Requirement | Architecture / Design Source | ADR | API / Module | Verification | AC | Status |
|---|---|---|---|---|---|---|---|
| FR-01 | Запрос на русском языке от пользователя | `ADD.md` §3, `api/openapi.yaml` `/query` | ADR-009, ADR-012 | `POST /query`, `AgentState.query` | Golden dataset positive questions | AC-02 | Designed |
| FR-02a | Векторный поиск в Qdrant с RBAC | `ADD.md` §3, §5; `security_architecture.md` §2.3 | ADR-002, ADR-005, ADR-007 | `vector_retriever`, Qdrant payload filter | RBAC eval, retrieval test | AC-02, AC-03 | Designed |
| FR-02b | Графовый traversal в Neo4j с RBAC | `ADD.md` §3, §5; `security_architecture.md` §2.4 | ADR-003, ADR-005, ADR-007 | `graph_retriever`, Cypher `WHERE access_level` | RBAC eval, graph traversal test | AC-02, AC-03 | Designed |
| FR-02c | Merge `0.7 vector + 0.3 graph` | `ADD.md` §3; `data_flow_query.md` | ADR-007 | `merge_results` | GraphRAG vs vector-only comparison | AC-02 | Designed |
| FR-03 | Ответ с источниками | `ADD.md` §3; `api/openapi.yaml` `QueryResponse` | ADR-009, ADR-012 | `QueryResponse.sources` | Golden dataset expected sources | AC-02 | Designed |
| FR-04 | Фильтрация до передачи контекста в LLM | `security_architecture.md` §2; `ADD.md` §5 | ADR-005 | Qdrant filter, Neo4j filter, `generator` context | RBAC leakage rate = 0% | AC-03 | Designed |
| FR-06 | Streaming-ответ | `api/openapi.yaml` `/query`, SSE response | ADR-009 | `POST /query?stream=true` | Manual API test / browser test | — | Optional |
| FR-07 | Graph Explorer для Admin | `ADD.md` §1.2; `workspace.dsl` | ADR-011 | `GET /graph`, React Explorer | UI demo, Neo4j graph count | AC-04 | Designed |
| FR-08 | Клик по узлу показывает связи | `ADD.md` §1.2; `api/openapi.yaml` `/graph` | ADR-011 | React Explorer, `GraphResponse.nodes/edges` | UI demo | AC-04 | Designed |
| FR-09 | Explorer доступен только Admin | `security_architecture.md` §2; OpenAPI `/graph` | ADR-005, ADR-011 | `GET /graph`, role guard | RBAC test for non-admin | AC-03 | Designed |
| FR-10 / FR-10a | Парсинг PDF/MD/CSV/DOCX/XLSX и OCR сканов | `ADD.md` §6; `data_flow_ingestion.md` | ADR-008, ADR-013 | `Document Preparation Pipeline` | Ingestion smoke test | AC-01 | Designed |
| FR-10b | Vision preprocessing через Qwen2.5-VL | `ADD.md` §6; `model_card.md` §3 | ADR-013 | `VISION_ENABLED=true`, ingest profile | Optional ingestion test | — | Optional |
| FR-11 | Разделы документа становятся `Section` в Neo4j | `data_architecture.md` §5; `er.md` | ADR-003, ADR-008 | `Ingestion Pipeline`, Neo4j writer | Graph count / Section query | AC-04 | Designed |
| FR-12 | Нормализация терминов через онтологию | `ADD.md` §6; `data_architecture.md` §5 | ADR-013 | `ontology.json`, entity normalizer | Duplicate canonical name test | AC-13 | Designed |
| FR-13 | Метаданные при загрузке | `data_architecture.md` §3; OpenAPI `IngestRequest` | ADR-005, ADR-008 | `POST /ingest` | Request validation test | AC-03 | Designed |
| FR-14a/b/c | Валидация пустого текста, access_level, min tokens | `ADD.md` §6; OpenAPI 422 | ADR-009, ADR-013 | `POST /ingest`, validators | 422 API tests | AC-01, AC-03 | Designed |
| FR-15 | Логирование результата подготовки документа | `ADD.md` §6; `data_architecture.md` §6 | ADR-010, ADR-013 | ingestion log / trace span | Ingestion trace check | — | Optional |
| FR-16 | Приём PDF/MD/CSV/DOCX/XLSX | `TECHNICAL_SPEC.md` §5.4; OpenAPI `/ingest` | ADR-013 | `POST /ingest` | Ingestion tests by format | AC-01 | Designed |
| FR-17a/b | Chunking 500 / overlap 50 | `ADD.md` §6; `data_architecture.md` §4 | ADR-008 | chunker | Chunk metadata test | AC-04 | Designed |
| FR-18a/b | Извлечение сущностей и связей через LLM JSON | `ADD.md` §6; `prompt_library.md` §3 | ADR-004, ADR-013 | entity extraction prompt, graph writer | Graph count / JSON validation | AC-04 | Designed |
| FR-19a | Запись чанков с embeddings в Qdrant | `data_architecture.md` §4 | ADR-002, ADR-006 | Qdrant client, embedding adapter | Qdrant collection count | AC-02 | Designed |
| FR-19b | Запись графа сущностей в Neo4j | `data_architecture.md` §5 | ADR-003 | Neo4j client / graph writer | Neo4j nodes/edges count | AC-04 | Designed |
| FR-20 | `access_level` на чанках и узлах | `security_architecture.md` §2.5; `data_architecture.md` §3 | ADR-005 | Qdrant payload, Neo4j properties | RBAC data validation | AC-03 | Designed |
| FR-21 | 5 ролей доступа | `security_architecture.md` §2.1; OpenAPI security scheme | ADR-005 | `X-User-Role`, role mapping | Role mapping unit test | AC-03 | Designed |
| FR-22a/b | Qdrant и Neo4j возвращают только разрешённые данные | `security_architecture.md` §2.3-2.4 | ADR-005 | retrievers | RBAC eval q-027..q-029 | AC-03 | Designed |
| FR-23 | HTTP 403 при закрытом доступе | OpenAPI common responses; `security_architecture.md` | ADR-005, ADR-009 | API role guard | API 403 tests | AC-03 | Designed |
| FR-25a/b/c | PII detection / masking | `security_architecture.md` §3.1 | ADR-005, ADR-010 | `InputGuard` | PII test cases | AC-03 | Designed |
| FR-26 | Prompt injection blocking | `security_architecture.md` §3.1; `golden_dataset` q-030 | ADR-004, ADR-005 | `InputGuard` | Injection block rate | AC-03 | Designed |
| FR-27 | Output PII guard | `security_architecture.md` §3.2 | ADR-005 | `OutputGuard` | Output PII test cases | AC-03 | Designed |
| FR-28a/b | OpenTelemetry + Langfuse traces | `ADD.md` §7; `ADR-010` | ADR-010 | tracing setup, node spans | 5 traces in Langfuse | AC-05 | Designed |
| FR-29a/b/c | Prometheus metrics | `ADD.md` §7.3; `capacity_planning.md` §7 | ADR-010 | `/metrics` | Metrics scrape test | AC-09 | Designed |
| FR-30 | Grafana dashboard | `ADD.md` §7.4 | ADR-010 | Grafana dashboard | Dashboard screenshot / demo | AC-09 | Planned |
| FR-31 | Knowledge Gap при низком quality_score | `ADD.md` §7.5; OpenAPI `/knowledge-gaps` | ADR-012 | `knowledge_gap` node | Golden dataset negative questions | AC-11 | Designed |
| FR-32a/b | Сохранение Knowledge Gap в PostgreSQL | `data_architecture.md` §6.2 | ADR-010, ADR-012 | `knowledge_gaps` table | DB/API test | AC-11 | Designed |
| FR-33 | `GET /knowledge-gaps` только для Admin | OpenAPI `/knowledge-gaps`; `security_architecture.md` | ADR-005, ADR-009 | API endpoint | Role-based API test | AC-11 | Designed |
| FR-34 | Сообщение пользователю при Knowledge Gap | `prompt_library.md` §6; OpenAPI `QueryResponse` | ADR-012 | `knowledge_gap_response` | Negative question test | AC-11 | Designed |
| FR-35 | `last_updated` в Qdrant payload | `data_architecture.md` §3-4 | ADR-008 | Qdrant payload | Payload validation | AC-12 | Designed |
| FR-36a/b | Расчёт `confidence_score` | `ADD.md` §3; `evaluation_plan.md` §6 | ADR-012 | `confidence_score` node | Old-source test | AC-12 | Designed |
| FR-37 | Ответ содержит `confidence_score` и даты источников | OpenAPI `QueryResponse`, `SourceReference` | ADR-009 | `/query` response | API response validation | AC-12 | Designed |
| FR-38 | Предупреждение при `confidence_score < 0.5` | `ADD.md` §3; `evaluation_plan.md` §6 | ADR-012 | response formatter | Old document scenario | AC-12 | Designed |
| FR-39 | Загрузка `ontology.json` | `data_architecture.md` §5; `ontology.json` | ADR-013 | ontology loader | Startup / ingestion test | AC-13 | Designed |
| FR-40a/b | Canonical names, types, aliases | `ontology.json`; `data_architecture.md` §5 | ADR-013 | ontology schema | Schema validation | AC-13 | Designed |
| FR-41a/b | Fuzzy match и создание новых узлов только при отсутствии совпадения | `ADD.md` §6; `data_architecture.md` §5 | ADR-013 | entity normalizer | Duplicate check in Neo4j | AC-13 | Designed |
| FR-42 | `GET/POST /ontology` | OpenAPI `/ontology` | ADR-009, ADR-013 | ontology API | API tests | — | Optional |
| FR-43 | Web UI на порту 3000 | `ADD.md` §8; `workspace.dsl` | ADR-011 | React UI | Browser smoke test | AC-01 | Designed |
| FR-44 | API Gateway не зависит от канала | `ADD.md` §4; `workspace.dsl` | ADR-009 | FastAPI Gateway | Architecture review | AC-07 | Designed |
| FR-45 | Parallel retrieval через LangGraph `Send()` | `ADD.md` §3; `ADR-012` | ADR-012 | `dispatch_retrievers` (conditional edge) | Trace / integration test | AC-02 | Designed |
| FR-46a/b | Retriever agents применяют RBAC независимо | `ADD.md` §3; `security_architecture.md` §2 | ADR-005, ADR-012 | `vector_retriever`, `graph_retriever` | RBAC eval | AC-03 | Designed |
| FR-47a/b | CriticAgent JSON score + feedback | `ADD.md` §3.4; `prompt_library.md` §4 | ADR-012 | `critic` | Prompt unit test / eval | AC-02 | Designed |
| FR-48a/b | Retry при score < 3, максимум 3 итерации | `ADD.md` §3.2; sequence diagram | ADR-012 | `should_retry` edge | LangGraph integration test | AC-02 | Designed |
| FR-49 | OTel span на каждого агента | `ADD.md` §7; `ADR-010` | ADR-010, ADR-012 | tracing wrapper | Langfuse trace inspection | AC-05 | Optional |

---

## 4. Non-Functional Requirements

| ID | Requirement | Architecture / Design Source | ADR | API / Module | Verification | AC | Status |
|---|---|---|---|---|---|---|---|
| NFR-01 | P95 latency на GPU сервере < 10 сек | `capacity_planning.md`, `ADD.md` §9 | ADR-001, ADR-010, ADR-012 | vLLM, retrievers, `/metrics` | Load test | AC-09 | Post-MVP Evidence |
| NFR-02 | P95 latency на GPU Dev VM < 10 сек | `capacity_planning.md` §2.2 | ADR-001 | GPU Dev stack | Load test on RTX 4090 | AC-09 | Post-MVP Evidence |
| NFR-02a | Mac 8 GB только local-lite | `capacity_planning.md` §2.1; `README.md` | ADR-001 | mock/Ollama fallback | Documentation review | — | Designed |
| NFR-03 | 0 внешних API | `security_architecture.md` §5; `CONCEPT.md` §2.2 | ADR-001, ADR-006, ADR-010 | local LLM, local DBs | Network log check | AC-06 | Designed |
| NFR-04 | RU/EN support | `model_card.md` §5 | ADR-001, ADR-006 | Qwen2.5, nomic-embed-text | Golden dataset RU/EN cases | AC-02 | Designed |
| NFR-05 | `docker compose up` < 3 минут | `ADD.md` §8; `capacity_planning.md` | — | Docker Compose profiles | Fresh machine startup test | AC-01 | Planned |
| NFR-06 | Только open source модели | `model_card.md`, `ADR-001`, `ADR-006` | ADR-001, ADR-006 | vLLM/Qwen/nomic | License review | AC-06 | Designed |
| NFR-07 | Self-hosted storage only | `data_architecture.md`; `security_architecture.md` §5 | ADR-002, ADR-003, ADR-010 | Qdrant, Neo4j, PostgreSQL | Architecture review / network check | AC-06 | Designed |
| NFR-08 | Пинированные Docker versions | `ADD.md` §8.6; `capacity_planning.md` | — | Docker Compose | Compose review | AC-01 | Planned |

---

## 5. Acceptance Criteria Coverage

| AC | Covered By | Evidence Document | Status |
|---|---|---|---|
| AC-01 | Startup, ingestion validation, UI availability | `ADD.md`, `api/openapi.yaml`, `capacity_planning.md` | Designed |
| AC-02 | Query pipeline, retrieval, generation, sources | `ADD.md`, `ADR-007`, `ADR-012`, `golden_dataset.jsonl` | Designed |
| AC-03 | RBAC, guardrails, access filtering | `security_architecture.md`, `ADR-005`, `golden_dataset.jsonl` | Designed |
| AC-04 | Knowledge Graph size and Explorer | `data_architecture.md`, `workspace.dsl`, `er.md` | Designed |
| AC-05 | Langfuse traces | `ADD.md`, `ADR-010` | Designed |
| AC-06 | No external APIs | `security_architecture.md`, `model_card.md`, `ADR-001`, `ADR-006` | Designed |
| AC-07 | C4 + deployment + sequence + data flow + ER | `docs/diagrams/`, включая `c4_level4_code.md` | Designed |
| AC-08 | ADR with trade-off analysis | `docs/ADR/` | Designed |
| AC-09 | Load report with P95/RPS | `evaluation_plan.md`, `capacity_planning.md` | Post-MVP Evidence |
| AC-10 | Video demo | `demo_script.md` | Planned |
| AC-11 | Knowledge Gap Detection | `ADD.md`, `api/openapi.yaml`, `evaluation_plan.md` | Designed |
| AC-12 | Confidence Score | `ADD.md`, `evaluation_plan.md` | Designed |
| AC-13 | Ontology normalization | `ontology.json`, `data_architecture.md` | Designed |

---

## 6. Missing Evidence After Implementation

Эти артефакты не должны быть заполнены до реализации MVP, но нужны для финального закрытия требований:

- `docs/evaluation/results/poc_comparison.md` — подтверждение преимущества GraphRAG над vector-only;
- `docs/evaluation/results/eval_report.md` — полный отчёт offline evaluation;
- `docs/load_test_report.md` — подтверждение AC-09;
- `docs/evaluation/results/raw_*.json` — исходные результаты evaluation;
- screenshots / video demo artifacts — подтверждение AC-10.

---

## 7. Связанные документы

- `docs/TECHNICAL_SPEC.md` — источник требований и критериев приёмки
- `docs/ADD.md` — основная архитектура решения
- `docs/api/openapi.yaml` — API contract
- `docs/security_architecture.md` — RBAC, guardrails, audit, threat model
- `docs/data_architecture.md` — схемы данных и lineage
- `docs/evaluation_plan.md` — план проверки качества, безопасности и производительности
- `docs/evaluation/golden_dataset.jsonl` — тестовый набор для offline/security evaluation
- `docs/ADR/` — журнал архитектурных решений
