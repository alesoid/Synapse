# Пояснительная записка  
## Synapse — Система гибридного поиска и генерации ответов по корпоративному корпусу документов на основе GraphRAG

**Автор:** Алеся Мороз  
**Дата защиты:** 3 июня 2026  
**Версия документа:** 1.0  

---

## Содержание

1. [Постановка задачи](#1-постановка-задачи)
2. [Описание системы](#2-описание-системы)
3. [Архитектура](#3-архитектура)
4. [Состав проекта](#4-состав-проекта)
5. [Технологический стек](#5-технологический-стек)
6. [Корпус документов](#6-корпус-документов)
7. [Многоагентный конвейер обработки запроса](#7-многоагентный-конвейер-обработки-запроса)
8. [Безопасность и разграничение доступа](#8-безопасность-и-разграничение-доступа)
9. [Наблюдаемость](#9-наблюдаемость)
10. [Тестирование и оценка качества](#10-тестирование-и-оценка-качества)
11. [Режимы работы и запуск](#11-режимы-работы-и-запуск)
12. [Документация проекта](#12-документация-проекта)
13. [Результаты](#13-результаты)

---

## 1. Постановка задачи

### 1.1 Проблема

Корпоративные знания в IT-компании хранятся в разрозненных источниках: PDF-регламенты, Markdown-стандарты, матрицы доступов, внутренние вики. Сотрудник тратит от 15 до 40 минут на поиск ответа на рабочий вопрос.

Существующие подходы не решают задачу:

- **Полнотекстовый поиск** (Confluence, Notion) не понимает смысл запроса и не учитывает связи между документами.
- **Обычный RAG** теряет контекст: не видит, что регламент А ссылается на политику Б, определяющую роль В.
- **Облачные LLM** (ChatGPT, Claude) недопустимы в закрытом контуре — нарушают ФЗ-152 и политику информационной безопасности.
- **Ручное разграничение доступа** не масштабируется: сотрудник либо видит лишнее, либо не находит нужное.

Дополнительные системные дисфункции управления знаниями:

| Дисфункция | Проявление |
|---|---|
| Пробелы в знаниях не видны | Ненайденный вопрос нигде не фиксируется |
| Знания стареют незаметно | Регламент 3-летней давности неотличим от актуального |
| Онтология не управляется | «Процесс деплоя», «pipeline выкатки», «релизный процесс» — это одно и то же, но три разных узла в графе |

### 1.2 Цели проекта

1. Создать on-premise GraphRAG систему, работающую без обращений к внешним API.
2. Реализовать гибридный поиск: векторный (семантический) + графовый (структурный).
3. Обеспечить ролевой контроль доступа (RBAC) на уровне каждого фрагмента документа.
4. Выявлять пробелы в корпоративных знаниях (Knowledge Gap Detection).
5. Сигнализировать об устаревших источниках через `confidence_score`.
6. Реализовать мультиагентную архитектуру с независимой оценкой качества (LLM-as-a-Judge).

---

## 2. Описание системы

**Synapse** — корпоративная платформа анализа знаний, реализующая паттерн GraphRAG (Graph-augmented Retrieval-Augmented Generation). Система работает полностью в закрытом контуре (on-premise / air-gapped).

### 2.1 Режимы работы

| Режим | Среда | Назначение |
|---|---|---|
| **Q&A** | Любой пользователь | Вопрос на русском языке → ответ со ссылками на источники с учётом роли |
| **Explorer** | Admin | Визуальное исследование графа знаний, поиск неочевидных связей |

### 2.2 Ключевые характеристики MVP

| Характеристика | Значение |
|---|---|
| Корпус | 15 документов, 5 уровней доступа |
| Чанки в Qdrant | 262 points |
| Узлы в Neo4j | 346 nodes |
| Рёбра в Neo4j | 1 654 edges |
| Ролей | 5 (junior → admin) |
| Нод в LangGraph-агенте | 11 |
| Тестов | 46 unit/integration |
| Eval-вопросов (golden dataset) | 32 |

---

## 3. Архитектура

### 3.1 Принципы

| Принцип | Реализация |
|---|---|
| On-premise by default | Никаких обращений к OpenAI / Anthropic / внешним API |
| Retrieval before generation | LLM получает контекст только после поиска по корпусу |
| Graph-enhanced context | Векторный поиск дополняется граф-траверсалом |
| Security before inference | RBAC и проверка запроса до передачи в LLM |
| Observability-first | Каждый этап трейсируется (Langfuse OTLP + Prometheus) |
| Modular infrastructure | LLM, vector DB, graph DB заменяемы без правки бизнес-логики |

### 3.2 Высокоуровневая схема

```
Пользователь (браузер)
       │  HTTP/JSON
       ▼
┌─────────────────────────────────────────────────────┐
│  FastAPI (backend/api/)                             │
│  X-User-Role → role_to_access_level()               │
│  Injection Guard → PII Guard                        │
└────────────────────┬────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────┐
│  LangGraph Agent (backend/agents/)                  │
│                                                     │
│  prepare_query → query_rewriter                     │
│       │                                             │
│       ├─── vector_retriever (Qdrant, RBAC filter)   │
│       └─── graph_retriever  (Neo4j, RBAC filter)    │
│                     │                               │
│              merge_results (RRF)                    │
│                     │                               │
│              role_context → generator (LLM)         │
│                     │                               │
│              critic (LLM-as-a-Judge)                │
│                     │                               │
│          confidence_score → should_retry            │
│               ├── output_guard → ответ              │
│               └── knowledge_gap → gap зафиксирован  │
└─────────────────────────────────────────────────────┘
       │               │
       ▼               ▼
   Qdrant           Neo4j
(векторный БД)   (граф знаний)
```

### 3.3 Два профиля инфраструктуры

```
local-lite  → mock LLM + mock embeddings  (любой Mac/Linux, без GPU, без Docker)
gpu-demo    → vLLM Qwen2.5-14B-AWQ + Qdrant + Neo4j + Langfuse Cloud (RTX 4090)
             Запуск: make restart-gpu  (нативно, без Docker)
             Или:    docker compose --profile gpu --profile observability up -d
```

---

## 4. Состав проекта

```
Synapse/
├── backend/                  # Python-бэкенд (FastAPI + LangGraph)
│   ├── agents/               # Мультиагентный граф LangGraph
│   ├── api/                  # HTTP API, схемы запросов/ответов
│   ├── core/                 # Конфигурация (Settings), соединения
│   ├── db/                   # Доступ к Neo4j, SQLite (audit, gaps)
│   ├── embeddings/           # Embedding-клиент (mock / nomic-embed-text)
│   ├── ingestion/            # Конвейер индексации: Markdown → chunks → БД
│   ├── llm/                  # LLM-клиент (mock / vLLM)
│   ├── observability/        # OTel-трейсинг, Prometheus-метрики
│   ├── ontology/             # Загрузчик словаря сущностей
│   ├── query/                # Конвейер запроса: pipeline, critic, rewriter
│   ├── retrieval/            # Ретриверы: векторный и граф
│   └── security/             # RBAC, защита от инъекций, PII-маскирование
├── frontend/                 # SPA-интерфейс (Tailwind CSS + Vanilla JS)
├── infra/                    # Docker Compose, Nginx, Prometheus, Grafana
├── scripts/                  # Скрипты оценки качества и нагрузочного теста
├── tests/                    # Unit- и интеграционные тесты (46 штук)
└── docs/                     # Вся проектная документация
    ├── corpus/               # Корпус: 15 документов + манифест
    ├── ADR/                  # 13 Architecture Decision Records
    ├── api/                  # OpenAPI-спецификация
    ├── diagrams/             # C4, ER, sequence, data flow диаграммы
    └── evaluation/           # Golden dataset, результаты eval-прогонов
```

### 4.1 `backend/agents/` — LangGraph-агент

| Файл | Назначение |
|---|---|
| `graph_agent.py` | Сборка StateGraph (11 нод + рёбра), точка входа `run_agent()` |
| `nodes.py` | Реализация всех нод и routing functions (`dispatch_retrievers`, `should_retry`) |
| `state.py` | Тип `AgentState` — 15 полей, разделяемых между нодами |

Граф использует `Send()` API LangGraph для параллельного запуска `vector_retriever` и `graph_retriever` (fan-out), что сокращает latency retrieval-шага на 30–40% по сравнению с последовательным выполнением.

### 4.2 `backend/api/` — HTTP API

| Файл | Назначение |
|---|---|
| `main.py` | Создание FastAPI-приложения, монтирование роутов, настройка OTel, статика UI |
| `routes.py` | Все эндпоинты: `/query`, `/ingest`, `/health`, `/ready`, `/graph`, `/knowledge-gaps`, `/audit-log`, `/ontology` |
| `schemas.py` | Pydantic-модели запросов и ответов (`QueryRequest`, `QueryResponse`, `HealthResponse` и др.) |

Ключевые эндпоинты:

| Метод | Путь | Роли | Описание |
|---|---|---|---|
| `POST` | `/query` | все | Задать вопрос корпусу; аудит каждого запроса в SQLite |
| `POST` | `/ingest` | manager, admin | Индексировать корпус (без тела) или загрузить один документ (с JSON-телом) |
| `GET` | `/health` | — | Статус сервиса, режим (gpu-demo / local-lite), состояние backends |
| `GET` | `/ready` | — | Readiness probe — 200 если API готов принимать запросы |
| `GET` | `/graph` | admin | Узлы и рёбра графа знаний (только при `STORAGE_BACKEND=qdrant-neo4j`) |
| `GET` | `/knowledge-gaps` | admin | Зафиксированные Knowledge Gaps (последние 100) |
| `GET` | `/audit-log` | admin | Журнал запросов — SHA-256 хеш, роль, quality_score (последние 200) |
| `GET` | `/ontology` | все | Просмотр загруженной доменной онтологии |
| `POST` | `/ontology` | admin | Перезагрузить онтологию с диска без рестарта сервера |

### 4.3 `backend/core/` — Конфигурация

| Файл | Назначение |
|---|---|
| `config.py` | `Settings` на основе `pydantic-settings`; все параметры читаются из `.env` / переменных окружения с type-safe значениями по умолчанию |
| `connections.py` | Ленивые синглтоны для Qdrant, Neo4j, LLM — инициализируются только при первом обращении |

Переключатели режимов через переменные окружения:

```
LLM_BACKEND=mock|vllm               # выбор LLM
EMBEDDINGS_BACKEND=mock|nomic       # выбор embedding-модели
STORAGE_BACKEND=mock|qdrant-neo4j   # выбор хранилища (in-memory vs Qdrant/Neo4j)
```

### 4.4 `backend/db/` — Доступ к данным

| Файл | Назначение |
|---|---|
| `neo4j_driver.py` | Низкоуровневый драйвер Neo4j (connection pool, retry) |
| `neo4j_client.py` | Типизированный клиент: создание узлов `Document`, `Section`, `Entity`, рёбер |
| `graph_queries.py` | Готовые Cypher-запросы для retrieval и Explorer-режима |
| `graph_repository.py` | Repository-слой: абстракция над Neo4j-клиентом |
| `audit_store.py` | SQLite-хранилище журнала запросов (`audit.db`); graceful degradation при незапущенном SQLite |
| `gap_store.py` | SQLite-хранилище зафиксированных Knowledge Gaps (`gaps.db`) |

### 4.5 `backend/embeddings/` — Embedding-клиент

| Файл | Назначение |
|---|---|
| `client.py` | Единый интерфейс `EmbeddingClient`; в `mock`-режиме — детерминированные SHA-256 embeddings (16 dim по умолчанию, конфигурируется через `MOCK_EMBEDDING_DIMENSION`); в `nomic` — реальная модель `nomic-embed-text` (768 dim) |

Mock-embeddings обеспечивают воспроизводимость тестов и возможность разработки на Mac без GPU.

### 4.6 `backend/ingestion/` — Конвейер индексации

| Файл | Назначение |
|---|---|
| `corpus_loader.py` | Чтение `corpus_manifest.json` и Markdown-файлов из `docs/corpus/adapted/` |
| `document_processor.py` | Предобработка документа: нормализация, извлечение метаданных |
| `chunker.py` | Разбивка текста на чанки: приоритет по заголовкам H1–H3, fallback — 500 слов / overlap 50 |
| `models.py` | Pydantic-модели для документа и чанка (`Document`, `Chunk`) |
| `storage.py` | Запись чанков в Qdrant (with RBAC payload) и узлов в Neo4j |
| `service.py` | Оркестрация всего pipeline ingestion: загрузка → чанкинг → embedding → запись |
| `ontology.json` | Локальная копия онтологии для ingestion-модуля |

Результат индексации: 262 чанка в Qdrant, 346 узлов и 1 654 рёбра в Neo4j.

### 4.7 `backend/llm/` — LLM-клиент

| Файл | Назначение |
|---|---|
| `client.py` | Единый интерфейс `LLMClient`; `mock` возвращает детерминированный ответ на основе шаблона; `vllm` вызывает OpenAI-совместимый REST API vLLM |

Разделение позволяет запускать все тесты без GPU и без сетевых зависимостей.

### 4.8 `backend/observability/` — Наблюдаемость

| Файл | Назначение |
|---|---|
| `tracing.py` | OpenTelemetry SDK: `setup_tracing(app)` устанавливает `TracerProvider` + OTLP-экспорт в Langfuse Cloud; `_NoOpTracer` / `_NoOpSpan` — graceful fallback при отсутствии пакетов; `tracer` — ProxyTracer, который используется во всех 11 нодах |
| `metrics.py` | Кастомные Prometheus-метрики LLM: `synapse_llm_tokens_per_second` (Gauge), `synapse_llm_completion_tokens_total` (Counter), `synapse_llm_generation_seconds` (Histogram). Стандартные HTTP-метрики (`http_requests_total`, latency) — через `prometheus-fastapi-instrumentator` в `main.py` |

### 4.9 `backend/ontology/` — Словарь сущностей

| Файл | Назначение |
|---|---|
| `loader.py` | Загрузка и валидация `ontology.json` — словаря канонических сущностей предметной области (роли, процессы, системы, политики) |

Онтология используется в нодах `prepare_query` (извлечение сущностей из запроса) и `graph_retriever` (поиск связанных узлов по сущностям).

### 4.10 `backend/query/` — Конвейер запроса

| Файл | Назначение |
|---|---|
| `pipeline.py` | Функция `_merge()` — Reciprocal Rank Fusion (RRF, alpha=0.7, k=60): объединяет результаты векторного и граф-поиска в ранжированный список источников |
| `critic.py` | `CriticAgent` — LLM-as-a-Judge: оценивает качество ответа по шкале 1.0–4.0, возвращает `quality_score` и `critic_feedback`; few-shot prompt; `MockCriticAgent` как fallback |
| `rewriter.py` | `QueryRewriter` — LLM переформулирует запрос пользователя в поисковые термины для улучшения recall |
| `service.py` | Высокоуровневый `QueryService`: точка входа для routes, связывает агент с API-слоем |

### 4.11 `backend/retrieval/` — Ретриверы

| Файл | Назначение |
|---|---|
| `vector_retriever.py` | Семантический поиск в Qdrant: `build_qdrant_rbac_filter()` строит payload-фильтр `access_level ≤ N` до выполнения запроса; возвращает top-10 чанков |
| `graph_retriever.py` | Graversal в Neo4j по сущностям запроса: Cypher-запрос с `WHERE n.access_level ≤ $user_level`; возвращает связанные разделы и документы |

RBAC применяется независимо в каждом ретривере — данные, недоступные пользователю, физически не попадают в контекст LLM.

### 4.12 `backend/security/` — Безопасность

| Файл | Назначение |
|---|---|
| `rbac.py` | Маппинг ролей в уровни доступа: `ROLES = {"junior": 1, …, "admin": 5}`; `role_to_access_level()` — FastAPI dependency |
| `injection.py` | Блокировка prompt-injection: regex-паттерны против `ignore previous instructions`, `system:`, base64-payload и т.п.; HTTP 422 при срабатывании |
| `pii.py` | PII-маскирование ответа перед отдачей пользователю: замена ФИО, телефонов, email на `[PII]` |

### 4.13 `frontend/` — Веб-интерфейс

| Файл | Назначение |
|---|---|
| `index.html` | SPA на Tailwind CSS + Vanilla JS: форма Q&A, выбор роли, отображение ответа с источниками, `confidence_score`, `quality_score`, `critic_feedback`, Graph Explorer для admin |
| `tailwind.min.css` | Локальная копия Tailwind CSS (без CDN — соответствует требованию air-gap) |

### 4.14 `infra/` — Инфраструктура

| Файл/папка | Назначение |
|---|---|
| `docker-compose.yml` | 4 профиля: `local-lite` (только backend), `gpu` (+ vLLM + Qdrant + Neo4j), `observability` (+ Langfuse + Grafana), `proxy` (Nginx) |
| `.env.example` | Шаблон переменных окружения |
| `prometheus.yml` | Конфигурация Prometheus: scrape backend `/metrics` каждые 10 с |
| `grafana/` | Datasources: Prometheus + Langfuse для дашбордов latency/RPS/tokens |
| `nginx/nginx.conf` | Reverse proxy: `/` → frontend, `/api/` → backend |

### 4.15 `scripts/` — Скрипты оценки

| Файл | Назначение |
|---|---|
| `eval_golden.py` | Прогон 32 вопросов из golden dataset; сравнение ответа с эталоном; сохранение отчёта в `docs/evaluation/results/` |
| `eval_rbac.py` | Проверка RBAC-leakage: 10 запросов с заниженной ролью к документам с повышенным уровнем доступа; цель — 0% утечек |
| `eval_comparison.py` | GraphRAG vs. vector-only: один и тот же запрос обрабатывается двумя pipeline, сравниваются `quality_score` |
| `load_test.py` | Асинхронный нагрузочный тест: N workers × T секунд → P50/P95/P99, RPS, error rate |

### 4.16 `tests/` — Тесты

| Файл | Что тестирует |
|---|---|
| `test_health.py` | `GET /health` возвращает 200 и корректную схему |
| `test_rbac.py` | role_to_access_level, блокировка при неизвестной роли, RBAC-фильтры ретриверов |
| `test_ingestion.py` | Полный pipeline ingestion: загрузка → чанки → embedding → storage |
| `test_document_processor.py` | Предобработка документов, chunking 500/50, overlap |
| `test_query_pipeline.py` | RRF-merge, CriticAgent, QueryRewriter, knowledge gap detection |
| `test_graph_agent.py` | LangGraph-агент: все ноды, retry-логика, confidence_score, output_guard |
| `test_audit_store.py` | Журнал запросов: запись, чтение, graceful degradation без SQLite |
| `test_local_lite.py` | End-to-end smoke: `POST /query` в mock-режиме возвращает валидный ответ |

### 4.17 `docs/` — Документация

| Путь | Содержание |
|---|---|
| `CONCEPT.md` | Концепт-документ: проблема, решение, архитектурные принципы |
| `TECHNICAL_SPEC.md` | Технические требования: 50+ FR (functional requirements), NFR, матрица рисков |
| `ADD.md` | Architecture Design Document: детальное описание всех компонентов и решений |
| `api/openapi.yaml` | OpenAPI 3.1 спецификация всех эндпоинтов |
| `ADR/` | 13 Architecture Decision Records (см. раздел 12) |
| `corpus/` | 15 корпоративных документов + манифест с метаданными |
| `diagrams/` | C4 (Level 4), ER, sequence, data flow диаграммы (Mermaid + Structurizr DSL) |
| `evaluation/` | Golden dataset (32 вопроса), результаты eval, load test report |
| `security_architecture.md` | Детальная схема трёх слоёв безопасности |
| `data_architecture.md` | Схема потоков данных ingestion и query |
| `prompt_library.md` | Библиотека промптов всех агентов с комментариями |
| `model_card.md` | Карточка модели Qwen2.5-14B-AWQ |
| `risk_register.md` | Реестр рисков с вероятностью и мерами снижения |
| `tco.md` | Расчёт совокупной стоимости владения |
| `traceability_matrix.md` | Матрица прослеживаемости: требования → реализация |

---

## 5. Технологический стек

| Слой | Технология | Обоснование |
|---|---|---|
| **LLM (gpu-demo)** | vLLM + Qwen2.5-14B-AWQ | Открытая лицензия Apache 2.0; AWQ-квантизация — 24 GB VRAM; OpenAI-совместимый API |
| **LLM (local-lite)** | Mock (детерминированный) | Разработка и тесты без GPU; воспроизводимость |
| **Embeddings** | nomic-embed-text (768 dim) | Лучшее качество для русского языка среди open-source моделей; MIT лицензия |
| **Vector DB** | Qdrant 1.9 | On-premise, payload-фильтрация (RBAC), HNSW индекс, Rust-производительность |
| **Graph DB** | Neo4j 5.18 Community | Cypher — стандарт де-факто для графовых запросов; WHERE-фильтрация по RBAC |
| **Оркестрация агентов** | LangGraph 0.6 | `Send()` API для параллельного fan-out; нативный StateGraph без смены фреймворка |
| **API** | FastAPI 0.110 + Pydantic v2 | Нативный async/await; автогенерация OpenAPI; `Depends()` для RBAC |
| **Frontend** | Tailwind CSS + Vanilla JS | SPA без build-шага; Tailwind поставляется локально (air-gap совместимость) |
| **Наблюдаемость** | Langfuse + OpenTelemetry + Prometheus + Grafana | Трейсинг LLM-вызовов + метрики инфраструктуры; Langfuse — OTLP-совместимый |
| **Инфраструктура** | Docker Compose (profiles) | Одна команда для любого режима; не требует Kubernetes для MVP |
| **Python** | 3.12 | `match/case`, улучшенный asyncio; современный type system |

---

## 6. Корпус документов

15 корпоративных документов — адаптированные для MVP IT-регламенты и политики на русском языке.

| ID | Название | Тип | Уровень доступа | Минимальная роль |
|---|---|---|---|---|
| INS-HR-001 | Инструкция по адаптации новых сотрудников | instruction | 1 | junior |
| INS-HR-002 | Правила работы с корпоративными инструментами | instruction | 1 | junior |
| POL-HR-001 | Кодекс поведения сотрудника | policy | 1 | junior |
| STD-ENG-001 | Стандарт код-ревью | standard | 2 | middle |
| STD-ENG-002 | Руководство по Git-workflow | standard | 2 | middle |
| STD-ENG-003 | Стандарт написания технической документации | standard | 2 | middle |
| STD-ARCH-001 | Архитектурный стандарт микросервисов | standard | 3 | senior |
| STD-ARCH-002 | Регламент работы с продакшн-системами | standard | 3 | senior |
| POL-ARCH-001 | Политика управления техническим долгом | policy | 3 | senior |
| POL-SEC-001 | Политика согласования доступов к системам | policy | 4 | manager |
| POL-SEC-002 | HR-политика грейдов и повышений | policy | 4 | manager |
| POL-MGR-001 | Регламент бюджетирования IT-проектов | policy | 4 | manager |
| POL-SEC-003 | Политика аудита и контроля доступов | policy | 5 | admin |
| POL-SEC-004 | Матрица доступов к системам | matrix | 5 | admin |
| POL-SEC-005 | Регламент управления инцидентами ИБ | policy | 5 | admin |

**Формат хранения:** Markdown в `docs/corpus/adapted/`; метаданные (тип, уровень доступа, дата обновления) — в `docs/corpus/corpus_manifest.json`.

---

## 7. Мультиагентный конвейер обработки запроса

### 7.1 Топология LangGraph StateGraph

Граф содержит 11 нод (узлов) и 2 routing functions:

```
START
  └→ prepare_query          ← strip, нормализация, извлечение сущностей
       └→ query_rewriter     ← LLM: вопрос → поисковые термины
            └→ [Send() fan-out] ─┬─ vector_retriever ─┐
                                 └─ graph_retriever  ─┴→ merge_results (RRF)
                                                              └→ role_context
                                                                   └→ generator (LLM)
                                                                        └→ critic (LLM-as-a-Judge)
                                                                             └→ confidence_score
                                                                  ┌──────────────┤
                                                                  │              │
                                                          output_guard    knowledge_gap
                                                              └→ END           └→ END
```

### 7.2 Описание нод

| Нода | Роль |
|---|---|
| `prepare_query` | Нормализация запроса, извлечение именованных сущностей |
| `query_rewriter` | LLM-переформулировка в поисковые термины (улучшение recall) |
| `dispatch_retrievers` | Routing function: `Send("vector_retriever") + Send("graph_retriever")` — параллельный fan-out |
| `vector_retriever` | Cosine-поиск в Qdrant с RBAC-фильтром |
| `graph_retriever` | Cypher-траверсал в Neo4j по сущностям с RBAC WHERE |
| `merge_results` | RRF: `alpha/(k+rank_v) + (1-alpha)×graph_signal/(k+rank_g)`, alpha=0.7, k=60 |
| `role_context` | Детерминированная ролевая подсказка для генератора (L1–L5) |
| `generator` | Генерация ответа с контекстом, ролевым фокусом и retry_feedback |
| `critic` | LLM-as-a-Judge: few-shot оценка качества 1.0–4.0, формат `ЧИСЛО \| ПОЯСНЕНИЕ` |
| `confidence_score` | Актуальность источников: `avg(1 − age_days/365)` по датам документов |
| `should_retry` | Routing function: retry только `generator` (не retrieval) → экономия latency |
| `output_guard` | PII-маскирование ответа перед отдачей пользователю |
| `knowledge_gap` | Фиксация пробела в знаниях в SQLite при низком quality_score |

### 7.3 Логика retry

При `quality_score < 3.0` и `iterations < 3`: перезапускается только нода `generator`, источники берутся из уже заполненного `state["sources"]`, критик-обратная связь (`critic_feedback`) передаётся как `retry_feedback` в промпт. Повторный retrieval не выполняется — это экономит 1–2 с на каждый retry-шаг.

### 7.4 AgentState — общее состояние агентов

```python
class AgentState(TypedDict):
    query: str                # исходный запрос
    access_level: int         # уровень доступа (1–5)
    entities: list[str]       # извлечённые сущности
    query_rewritten: str      # переформулированный запрос
    vector_chunks: list       # результаты Qdrant
    graph_results: list       # результаты Neo4j
    sources: list             # merged RRF-список
    role_hint: str            # ролевой контекст для генератора
    answer: str               # ответ LLM
    quality_score: float      # оценка критика (1.0–4.0)
    critic_feedback: str      # пояснение критика
    confidence_score: float   # актуальность источников (0–1)
    iterations: int           # счётчик retry
    gap_detected: bool        # флаг knowledge gap
    trace_id: str             # Langfuse trace ID
```

---

## 8. Безопасность и разграничение доступа

### 8.1 Три слоя RBAC

```
Слой 1: API Gateway
  └─ role_to_access_level("X-User-Role") → int (1–5)
  └─ HTTP 403 при неизвестной роли

Слой 2: Qdrant payload filter
  └─ FieldCondition(key="access_level", range=Range(lte=user_level))
  └─ Применяется ДО выполнения ANN-поиска

Слой 3: Neo4j Cypher WHERE
  └─ WHERE n.access_level <= $user_level
  └─ Применяется на traversal-уровне
```

Данные, недоступные пользователю, никогда не попадают в контекст LLM.

### 8.2 Input Guardrails

Реализованы в `backend/security/injection.py`:
- Блокировка prompt-injection паттернов (regex + keyword matching)
- HTTP 422 с сообщением `Query blocked by security policy`
- Проверка максимальной длины запроса (1 000 символов)

### 8.3 Output Guardrails

Реализованы в ноде `output_guard`:
- PII-маскирование в ответе: ФИО, телефоны, email → `[PII]`
- Применяется ко всем ответам, кроме ветки `knowledge_gap`

### 8.4 Аудит

Каждый запрос логируется в `audit.db` (SQLite): `user_role`, `access_level`, `query_hash` (SHA-256, plain text не хранится), `result_count`, `quality_score`, `gap_detected`, `timestamp`. Доступно через `GET /audit-log` (только admin, последние 200 записей).

---

## 9. Наблюдаемость

### 9.1 Трейсинг (Langfuse / OpenTelemetry)

Реализован в `backend/observability/tracing.py`:

- **ProxyTracer**: модульный `tracer = trace.get_tracer("synapse.agent")` создаётся при импорте; после вызова `setup_tracing(app)` автоматически начинает использовать реальный `TracerProvider` (OTel lazy delegation)
- **OTLP-экспорт**: спаны отправляются в Langfuse через OTLP HTTP endpoint
- **Все 11 нод** обёрнуты в `with tracer.start_as_current_span("node_name")` с атрибутами (access_level, results_count, iteration и т.д.)
- **FastAPIInstrumentor**: авто-инструментация HTTP-запросов
- **Graceful degradation**: `_NoOpTracer` / `_NoOpSpan` при отсутствии пакетов `opentelemetry-sdk`

### 9.2 Метрики (Prometheus + Grafana)

Реализованы в `backend/observability/metrics.py`:

**Кастомные LLM-метрики** (`backend/observability/metrics.py`):

| Метрика | Тип | Описание |
|---|---|---|
| `synapse_llm_tokens_per_second` | Gauge | Скорость генерации LLM (tokens/sec, последний вызов) |
| `synapse_llm_completion_tokens_total` | Counter | Всего сгенерированных токенов с момента запуска |
| `synapse_llm_generation_seconds` | Histogram | Latency LLM-вызова (бакеты: 0.5–30 с) |

**Стандартные HTTP-метрики** (через `prometheus-fastapi-instrumentator`):

| Метрика | Описание |
|---|---|
| `http_requests_total` | Количество запросов по handler/method/status |
| `http_request_size_bytes` | Размер тела запроса |
| `http_response_size_bytes` | Размер тела ответа |

Метрики доступны на `/metrics`. В gpu-demo: Grafana dashboard показывает LLM latency, tokens/sec, HTTP RPS и error rate.

---

## 10. Тестирование и оценка качества

### 10.1 Unit и интеграционные тесты

46 тестов в 8 файлах, запуск: `python -m pytest tests/ -v`

Все тесты проходят в `local-lite` режиме без GPU и без внешних сервисов.

### 10.2 Golden Dataset

32 вопроса в `docs/evaluation/golden_dataset.jsonl`, разбитые на категории:

| Категория | Количество | Цель |
|---|---|---|
| Positive (есть ответ) | 18 | Правильный ответ с источниками |
| Negative (нет ответа) | 6 | Knowledge Gap Detection |
| RBAC | 6 | 0% утечек при заниженной роли |
| Injection | 2 | HTTP 422 |

Запуск: `python scripts/eval_golden.py --url http://localhost:8000`

### 10.3 Оценка безопасности

RBAC-leakage тест: 10 запросов с ролью `junior` к документам уровня `manager`/`admin`. Целевой показатель — 0 утечек.

Injection-тест: 3 паттерна prompt-injection → все блокируются с HTTP 422.

### 10.4 Нагрузочный тест

`python scripts/load_test.py --url http://localhost:8000 --concurrency 5 --duration 30`

Результаты в mock-режиме (Mac M3):

| Метрика | Результат |
|---|---|
| P95 latency | 32 мс |
| RPS | 207 |
| Error rate | 0% |

### 10.5 Eval: GraphRAG vs Vector-only

`eval_comparison.py` прогоняет один и тот же набор вопросов через GraphRAG-pipeline и через pipeline без граф-ретривера, сравнивает средний `quality_score`. Результаты в `docs/evaluation/results/`.

---

## 11. Режимы работы и запуск

### 11.1 local-lite (Mac, без GPU)

Разработка, тестирование, демонстрация на локальной машине без GPU.

```bash
# Установка зависимостей
pip install -e ".[dev]"

# Запуск сервера
uvicorn backend.api.main:app --host 0.0.0.0 --port 8000

# Открыть интерфейс
open http://localhost:8000/ui/

# Пример запроса
curl -X POST http://localhost:8000/query \
  -H "X-User-Role: junior" \
  -H "Content-Type: application/json" \
  -d '{"query": "Кто отвечает за выдачу IT-доступов при онбординге?"}'
```

### 11.2 local-lite (Docker)

```bash
cd infra && cp .env.example .env
docker compose --profile local-lite up -d
open http://localhost:8000/ui/
```

### 11.3 gpu-demo (RTX 4090, полный стек)

**Предварительные требования:**
- Python venv в `.venv/` (`python3 -m venv .venv && .venv/bin/pip install -e ".[dev,observability]"`)
- `qdrant` в `PATH` или бинарный файл доступен
- `neo4j` в `PATH` или задана переменная `NEO4J_HOME`
- `.env` или `infra/.env` заполнен (`LANGFUSE_*` ключи для трейсинга)

**Нативный запуск (без Docker):**
```bash
# Одна команда — полный цикл:
# 1. pip install -e ".[dev,observability]"   — зависимости включая langfuse
# 2. make stop                               — остановка всех сервисов
# 3. rm -rf storage/collections/            — очистка Qdrant WAL
# 4. start-qdrant → start-neo4j → start-vllm → start-api
# 5. make ingest                             — индексация корпуса (262 чанка)
# 6. ожидание готовности vLLM (до 5 мин, прогресс: .........)
# 7. make status                             — итоговый статус всех сервисов
make restart-gpu
```

**Полезные команды после запуска:**
```bash
make status        # статус всех сервисов (Qdrant, Neo4j, vLLM, API)
make logs          # tail -f логов API
make logs-vllm     # tail -f логов vLLM (видны tokens/sec при прогреве)
make ingest        # повторная индексация корпуса
make stop          # остановка всех сервисов
```

**Docker Compose (альтернатива):**
```bash
cd infra && cp .env.example .env
# Заполнить HF_TOKEN для загрузки Qwen2.5-14B-AWQ
docker compose --profile gpu --profile observability up -d

# Индексация корпуса (однократно)
curl -X POST http://localhost:8000/ingest \
  -H "X-User-Role: admin" \
  -H "Content-Type: application/json"
```

### 11.4 Доступные сервисы

| Сервис | URL | Профиль |
|---|---|---|
| UI | http://localhost:8000/ui/ | все |
| Swagger / OpenAPI | http://localhost:8000/docs | все |
| Neo4j Browser | http://localhost:7474 | gpu |
| Qdrant Dashboard | http://localhost:6333 | gpu |
| Langfuse Cloud | https://cloud.langfuse.com | observability (внешний сервис) |
| Grafana | http://localhost:3001 | observability (Docker) |
| Prometheus | http://localhost:9090 | observability (Docker) |

---

## 12. Документация проекта

Проект содержит 13 Architecture Decision Records (ADR) — документов, фиксирующих ключевые архитектурные решения с анализом альтернатив и trade-offs:

| ADR | Тема решения |
|---|---|
| ADR-001 | LLM: vLLM + Qwen2.5-14B-AWQ (vs Ollama, OpenAI API) |
| ADR-002 | Vector DB: Qdrant (vs Weaviate, pgvector, Chroma) |
| ADR-003 | Graph DB: Neo4j (vs ArangoDB, Amazon Neptune) |
| ADR-004 | Оркестрация: LangGraph (vs LangChain, AutoGen, Crew AI) |
| ADR-005 | RBAC: трёхслойный header-based (vs JWT, OAuth2) |
| ADR-006 | Embeddings: nomic-embed-text (vs BGE, OpenAI) |
| ADR-007 | Гибридный поиск: RRF alpha=0.7, k=60 (vs линейная комбинация) |
| ADR-008 | Chunking: 500 слов / overlap 50 / иерархический по заголовкам |
| ADR-009 | API-фреймворк: FastAPI (vs Django, Flask, aiohttp) |
| ADR-010 | Наблюдаемость: Langfuse + OTel + Prometheus (vs Datadog, W&B) |
| ADR-011 | Frontend: Vanilla JS + Tailwind (vs React, Vue, Next.js) |
| ADR-012 | Multi-Agent: Orchestrator + Parallel Retrievers + Critic |
| ADR-013 | Мультимодальность: PDF/Vision (Scale-этап) |

---

## 13. Результаты

### 13.1 Статус реализации

| Компонент | Статус |
|---|---|
| Корпус документов (15 шт., 5 уровней доступа) | ✅ |
| Ingestion pipeline (Markdown → Qdrant + Neo4j) | ✅ |
| Мультиагентный LangGraph pipeline (11 нод) | ✅ |
| RBAC (3 слоя: API + Qdrant + Neo4j) | ✅ |
| Input Guardrails (injection + PII) | ✅ |
| CriticAgent (LLM-as-a-Judge, few-shot) | ✅ |
| Confidence Score (актуальность источников) | ✅ |
| Knowledge Gap Detection + SQLite-хранилище | ✅ |
| Параллельный retrieval (LangGraph Send() fan-out) | ✅ |
| Output Guard (PII-маскирование) | ✅ |
| OpenTelemetry SDK + Langfuse OTLP | ✅ |
| Prometheus метрики | ✅ |
| Web UI (Tailwind + Vanilla JS) | ✅ |
| Docker Compose (4 профиля) | ✅ |
| Golden dataset (32 вопроса) + eval scripts | ✅ |
| 46 unit/integration тестов | ✅ |
| 13 ADR + полная проектная документация | ✅ |

### 13.2 Ключевые показатели

| Показатель | Результат |
|---|---|
| Unit-тесты | 46/46 PASS |
| RBAC-leakage | 0% (0/10 restricted probes) |
| Knowledge Gap detection | 6/6 PASS |
| Injection blocking | 3/3 PASS (HTTP 422) |
| Load test P95 (5 workers, mock) | 32 мс |
| Load test RPS (5 workers, mock) | 207 RPS |
| Чанки в Qdrant | 262 points |
| Узлы в Neo4j | 346 nodes |
| Рёбра в Neo4j | 1 654 edges |

### 13.3 Архитектурные инновации относительно baseline

| Baseline (single-agent RAG) | Synapse (GraphRAG + Multi-Agent) |
|---|---|
| Последовательный retrieval | Параллельный fan-out через `Send()` |
| Self-assessment bias при оценке | Независимый CriticAgent (LLM-as-a-Judge) |
| Нет граф-контекста | Neo4j Knowledge Graph, 1 654 рёбра |
| RBAC только на уровне API | RBAC в каждом ретривере независимо |
| Нет фиксации пробелов | Knowledge Gap Detection + SQLite |
| Нет сигнала об устаревших данных | Confidence Score по дате документа |
