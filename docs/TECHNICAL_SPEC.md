# Synapse — Техническое Задание (TECHNICAL_SPECIFICATION)

**Версия:** 1.3  
**Дата:** 11 мая 2026  
**Автор:** [Алеся Мороз]  
**Статус:** Утверждён

**История изменений:**
| Версия | Дата | Изменения |
|---|---|---|
| 1.0 | 10 мая 2026 | Первая версия |
| 1.1 | 11 мая 2026 | Добавлены Knowledge Gap Detection, Confidence Score, Domain Ontology |
| 1.2 | 11 мая 2026 | Расширены форматы документов, добавлены User Channels, Corporate Systems, Identity Provider, Architecture Principles |
| 1.3 | 11 мая 2026 | Multi-Agent Architecture и Document Preparation Pipeline (OCR + Vision) перенесены из Scale в MVP; добавлен OpenTelemetry; обновлены FR, tech stack, Out of Scope |

---

## 1. Назначение системы

Synapse — корпоративная платформа интеллектуального анализа знаний на основе GraphRAG для IT-компаний. Система предназначена для автоматизации поиска информации во внутренних корпоративных документах с учётом ролевого разграничения доступа, работающая полностью в закрытом корпоративном контуре без обращения к внешним API.

**Контекст применения:** IT-компания, 5 категорий сотрудников, корпус внутренних документов (регламенты, технические стандарты, политики, процессы).

---

## 2. Цели и задачи

**Цель проекта:** разработать MVP корпоративной платформы анализа знаний, демонстрирующей преимущество GraphRAG подхода над обычным векторным поиском при соблюдении требований информационной безопасности.

**Задачи:**

1. Реализовать pipeline загрузки и обработки корпоративных документов с построением Knowledge Graph
2. Реализовать гибридный поиск (векторный + графовый) для получения контекстно-обогащённых ответов
3. Обеспечить разграничение доступа к документам на уровне чанков по ролям пользователей (RBAC)
4. Реализовать агентную архитектуру на LangGraph с Self-Reflection и защитой от некачественных ответов
5. Обеспечить полную локальность системы (on-premise, без внешних API)
6. Подготовить архитектурную документацию уровня Enterprise

---

## 3. Архитектурные принципы

Полное описание принципов — в `CONCEPT.md`, раздел 2.1 и 2.2. Ключевые принципы:

| Принцип | Описание |
|---|---|
| On-premise by default | Система разворачивается в закрытом корпоративном контуре, без обращений к внешним API |
| Retrieval before generation | LLM получает контекст только после поиска по корпусу |
| Graph-enhanced context enrichment | Векторный поиск дополняется графовым траверсалом |
| Security enforced before inference | Проверка прав доступа выполняется до передачи данных в LLM |
| Separation of Control Plane and Data Plane | Оркестрация (LangGraph, API Gateway) и хранилища (Qdrant, Neo4j, vLLM) разделены архитектурно |
| Ontology-driven knowledge graph | Граф знаний строится на основе явного словаря сущностей предметной области |

---

## 4. Этапы реализации (PoC → MVP → Scale)

### Этап 1: PoC (Proof of Concept)
**Срок:** до 25 мая 2026  
**Результат:** рабочий прототип с базовым GraphRAG pipeline, подтверждение технической гипотезы

### Этап 2: MVP (текущий ТЗ)
**Срок:** до 6 июня 2026  
**Результат:** полнофункциональная система, готовая к демонстрации и защите диплома

### Этап 3: Scale (вне скоупа текущего ТЗ)
**Результат:** production-ready платформа с Kubernetes, JWT, полноценным Multimodal RAG, интеграцией с Corporate Systems и Identity Provider

> В MVP Vision используется только как опциональный preprocessing-слой при ingestion (`Qwen2.5-VL` описывает страницы со схемами/чертежами). Полноценный Multimodal RAG в Scale означает пользовательские запросы и retrieval/generation по изображениям, таблицам и схемам как первичным источникам.

---

## 5. Функциональные требования

### 5.1 Q&A режим

| ID | Требование | Приоритет |
|---|---|---|
| FR-01 | Система принимает запрос на русском языке от авторизованного пользователя | Must Have |
| FR-02 | Система выполняет гибридный поиск: векторный (Qdrant) + графовый (Neo4j) с merge по формуле `0.7 * vector + 0.3 * graph` | Must Have |
| FR-03 | Система возвращает ответ с указанием источников (название документа, раздел) | Must Have |
| FR-04 | Система фильтрует результаты поиска по уровню доступа пользователя (RBAC) | Must Have |
| FR-05 | CriticAgent выполняет независимую оценку качества ответа (LLM-as-a-Judge) и инициирует повторный поиск если quality_score < 3 (макс. 3 итерации) | Must Have |
| FR-06 | Система возвращает streaming-ответ (токены передаются по мере генерации) | Should Have |

### 5.2 Explorer режим

| ID | Требование | Приоритет |
|---|---|---|
| FR-07 | Admin/Analyst видит визуализацию графа знаний в React UI (react-force-graph) | Must Have |
| FR-08 | Клик по узлу графа показывает связанные документы и отношения | Must Have |
| FR-09 | Explorer режим доступен только пользователям с ролью Admin (access_level=5) | Must Have |

### 5.3 Document Preparation Pipeline

Реальные корпоративные документы поступают в систему в неструктурированном виде: отсканированные PDF, Word-файлы с произвольным форматированием, Confluence-страницы с макросами, Excel-матрицы, чертежи. Прямая передача таких документов в Ingestion Pipeline приводит к низкому качеству чанкинга и ошибкам при извлечении сущностей.

Document Preparation Pipeline — обязательный слой подготовки документа перед его индексацией. Реализован в два слоя (см. ADR-013).

**Этапы подготовки:**

```
Сырой документ (PDF / DOCX / XLSX / Markdown / CSV / скан / чертёж)
        ↓
[1. Парсинг и очистка]         ← pymupdf, easyocr (Слой 1, обязательно)
        ↓
[2. Vision-описание]           ← Qwen2.5-VL (Слой 2, при VISION_ENABLED=true)
        ↓
[3. Структурирование]
        ↓
[4. Нормализация терминов]
        ↓
[5. Разметка метаданных]
        ↓
[6. Валидация]
        ↓
Подготовленный документ → Ingestion Pipeline
```

| ID | Требование | Приоритет |
|---|---|---|
| FR-10 | Парсер извлекает чистый текст из PDF, Markdown, CSV, DOCX, XLSX с удалением артефактов форматирования (колонтитулы, водяные знаки, служебные символы) | Must Have |
| FR-10a | **[Слой 1]** Для отсканированных PDF (нативный текст < 50 токенов на страницу) система применяет OCR через easyocr (ru+en) на растеризованных страницах (300 DPI) | Must Have |
| FR-10b | **[Слой 2, опционально]** Для страниц с чертежами и схемами (текст < 50 токенов после OCR) система генерирует текстовое описание через Qwen2.5-VL-7B; активируется через `VISION_ENABLED=true`; запускается только при ingestion, не конкурирует с основной моделью за VRAM | Should Have |
| FR-11 | Структурирование выделяет логические разделы документа по заголовкам; каждый раздел становится отдельным узлом типа `Section` в Neo4j | Must Have |
| FR-12 | Нормализация приводит роли, названия систем и процессов к единому словарю Synapse Corp (например: «тимлид» → `Tech Lead`, «наш gitlab» → `GitLab`) | Should Have |
| FR-13 | Разметка метаданных: оператор проставляет `access_level` (1–5), тип документа (`policy`, `standard`, `instruction`, `matrix`) и идентификатор при загрузке через `POST /ingest` | Must Have |
| FR-14 | Валидация отклоняет документ если: текст пустой после очистки, `access_level` не указан, объём менее 100 токенов | Must Have |
| FR-15 | Система логирует результат подготовки каждого документа: количество извлечённых разделов, итоговый объём токенов, источник извлечения (`native` / `ocr` / `vision`), статус валидации | Should Have |

> **Scale-этап:** автоматическая классификация `access_level` через LLM на основе содержания документа; OCR промышленного качества (Tesseract 5); коннекторы к Confluence и GitLab.

### 5.4 Ingestion Pipeline

| ID | Требование | Приоритет |
|---|---|---|
| FR-16 | Система принимает документы форматов PDF, Markdown, CSV, DOCX, XLSX | Must Have |
| FR-17 | Система выполняет chunking с настраиваемым размером (default: 500 токенов, overlap: 50) | Must Have |
| FR-18 | Система извлекает сущности и связи из документов через LLM (JSON mode) | Must Have |
| FR-19 | Система записывает чанки с эмбеддингами в Qdrant и граф сущностей в Neo4j | Must Have |
| FR-20 | Каждый чанк и узел графа размечается уровнем доступа (access_level 1–5) при загрузке | Must Have |

### 5.5 RBAC

| ID | Требование | Приоритет |
|---|---|---|
| FR-21 | Система поддерживает 5 ролей: Junior(1), Middle(2), Senior(3), Manager(4), Admin(5) | Must Have |
| FR-22 | Пользователь получает только документы с access_level ≤ его уровню | Must Have |
| FR-23 | Попытка доступа к закрытому документу возвращает сообщение об ограничении доступа | Must Have |
| FR-24 | RBAC применяется одновременно в Qdrant (payload filter) и Neo4j (WHERE n.access_level <= user_level) | Must Have |

> **MVP:** роль передаётся через HTTP заголовок `X-User-Role`. JWT и интеграция с Identity Provider (LDAP/AD) — Scale-этап (см. раздел 11).

### 5.6 User Channels

Пользователи взаимодействуют с Synapse через различные каналы доступа. В MVP реализован веб-браузер (React UI). В Scale-этапе планируется расширение каналов.

| ID | Требование | Приоритет |
|---|---|---|
| FR-43 | В MVP пользователь взаимодействует с системой через веб-браузер (React UI на порту 3000) | Must Have |
| FR-44 | Архитектура системы не привязана к конкретному каналу доступа — запросы поступают через API Gateway независимо от канала | Must Have |

> **Scale-этап:** Mobile App, Slack/Teams bot, REST API для внешних систем.

### 5.7 Guardrails

| ID | Требование | Приоритет |
|---|---|---|
| FR-25 | Input Guardrail фильтрует PII в запросе: email, телефон, паспортные данные | Must Have |
| FR-26 | Input Guardrail блокирует базовые prompt injection паттерны | Must Have |
| FR-27 | Output Guardrail проверяет ответ на наличие PII перед отдачей пользователю | Must Have |

### 5.8 Observability

| ID | Требование | Приоритет |
|---|---|---|
| FR-28 | Каждый запрос инструментируется через OpenTelemetry SDK; трейсы экспортируются в Langfuse по протоколу OTLP (ноды LangGraph агентов, latency каждой ноды) | Must Have |
| FR-29 | Prometheus собирает метрики: request_latency_seconds, request_count_total, tokens_per_second | Must Have |
| FR-30 | Grafana дашборд отображает latency, RPS, error rate, tokens/sec | Must Have |

### 5.9 Knowledge Gap Detection

Механизм выявления пробелов в корпусе знаний на основе анализа неуспешных запросов.

| ID | Требование | Приоритет |
|---|---|---|
| FR-31 | Если агент завершает работу с `quality_score < 2` после максимального числа итераций — запрос фиксируется как «неотвеченный» | Must Have |
| FR-32 | Неотвеченные запросы сохраняются в PostgreSQL (Langfuse): текст запроса, роль пользователя, timestamp, число итераций | Must Have |
| FR-33 | Эндпоинт `GET /knowledge-gaps` возвращает список неотвеченных запросов за период (доступен только Admin) | Must Have |
| FR-34 | В ответе пользователю при неуспешном поиске явно указывается: «Информация по данному вопросу отсутствует в корпусе. Запрос зафиксирован для пополнения базы знаний» | Must Have |

### 5.10 Knowledge Confidence Score

Оценка актуальности ответа на основе возраста использованных источников.

| ID | Требование | Приоритет |
|---|---|---|
| FR-35 | Каждый документ в Qdrant содержит поле `last_updated` (дата последнего обновления) в payload | Must Have |
| FR-36 | Агент вычисляет `confidence_score` ответа: среднее значение актуальности источников по формуле `1 - (age_days / 365)`, ограниченное диапазоном [0, 1] | Must Have |
| FR-37 | Ответ содержит поле `confidence_score` и список источников с датами обновления | Must Have |
| FR-38 | Если `confidence_score < 0.5` — ответ сопровождается предупреждением: «Источники могут быть устаревшими. Рекомендуем проверить актуальность документов» | Must Have |

### 5.11 Domain Ontology

Явный словарь сущностей предметной области для нормализации Knowledge Graph.

| ID | Требование | Приоритет |
|---|---|---|
| FR-39 | Система загружает онтологию предметной области из файла `ontology.json` при запуске | Must Have |
| FR-40 | Онтология содержит канонические имена сущностей, их типы и список синонимов: `{"canonical": "GitLab", "type": "System", "aliases": ["gitlab", "наш gitlab", "система контроля версий"]}` | Must Have |
| FR-41 | Entity extractor сначала сопоставляет извлечённую сущность с онтологией (fuzzy match), и только при отсутствии совпадения создаёт новый узел в Neo4j | Must Have |
| FR-42 | Admin может просматривать и редактировать онтологию через эндпоинт `GET/POST /ontology` | Should Have |

### 5.12 Multi-Agent Architecture

Реализация паттерна Multi-Agent Collaboration через LangGraph `Send()` API. Подробное описание — ADR-012.

| ID | Требование | Приоритет |
|---|---|---|
| FR-45 | OrchestratorAgent запускает VectorRetrieverAgent и GraphRetrieverAgent параллельно через LangGraph `Send()` API | Must Have |
| FR-46 | VectorRetrieverAgent и GraphRetrieverAgent применяют RBAC фильтр независимо друг от друга | Must Have |
| FR-47 | CriticAgent выполняет независимую оценку ответа (LLM-as-a-Judge): получает вопрос + ответ + источники, возвращает `quality_score` и `feedback` в формате JSON | Must Have |
| FR-48 | При `quality_score < 3` и числе итераций < 3 OrchestratorAgent повторяет параллельный retrieval | Must Have |
| FR-49 | Каждый агент инструментируется отдельным OTel span — в Langfuse видна latency каждого агента независимо | Should Have |

---

## 6. Нефункциональные требования

| ID | Требование | Целевое значение |
|---|---|---|
| NFR-01 | Latency ответа (P95) на GPU сервере | < 10 сек |
| NFR-02 | Latency ответа (P95) на GPU Dev VM | < 10 сек |
| NFR-02a | Local Lite Dev на Mac 8 GB | Не является целевой средой полного LLM stack; допускаются mock/stub сценарии и lightweight-тесты |
| NFR-03 | Локальность | 0 обращений к внешним API (OpenAI/Anthropic/etc) |
| NFR-04 | Поддержка языков | Русский и английский |
| NFR-05 | Запуск системы | Одной командой `docker compose up` за < 3 минут |
| NFR-06 | Модели | Только open source с поддержкой русского языка |
| NFR-07 | Хранение данных | Только self-hosted БД (Qdrant, Neo4j, PostgreSQL) |
| NFR-08 | Воспроизводимость | Docker образы с пинированными версиями (не latest) |

---

## 7. Роли пользователей и матрица доступа

| Роль | Access Level | Доступные документы |
|---|---|---|
| Junior | 1 | Публичные регламенты, онбординг-материалы |
| Middle | 2 | + Технические стандарты, инженерные практики |
| Senior | 3 | + Архитектурные решения, ADR, системные документы |
| Manager | 4 | + HR-политики, процессы согласований, бюджеты |
| Admin / Analyst | 5 | Все документы + Explorer режим (граф знаний) |

---

## 8. Входные и выходные данные

### Входные данные системы

| Тип | Формат | Описание |
|---|---|---|
| Корпоративные документы | PDF, Markdown, CSV, DOCX, XLSX | Регламенты, стандарты, политики, матрицы доступов, чертежи, сканы |
| Метаданные документа | JSON (при загрузке) | `access_level`, `doc_type`, `doc_id`, `last_updated` — указываются оператором при вызове `POST /ingest` |
| Пользовательский запрос | Текст (RU/EN) | Вопрос к системе, макс. 1000 символов |
| Роль пользователя | HTTP заголовок `X-User-Role` | Одно из: junior, middle, senior, manager, admin |

### Выходные данные системы

| Тип | Формат | Описание |
|---|---|---|
| Ответ на запрос | JSON / Streaming text | Текст ответа + список источников (doc_id, section, access_level) + `confidence_score` |
| Данные графа | JSON (nodes + edges) | Узлы и рёбра Knowledge Graph для Explorer режима |
| Трейс запроса | Langfuse UI | Граф выполнения LangGraph агента с latency каждой ноды |
| Метрики | Prometheus/Grafana | RPS, latency, tokens/sec, error rate |
| Knowledge Gaps | JSON | Список неотвеченных запросов за период (эндпоинт `GET /knowledge-gaps`) |

---

## 9. Технический стек

| Компонент | Технология | Обоснование |
|---|---|---|
| LLM (gpu-dev / demo / prod-like) | vLLM + Qwen2.5-14B-AWQ | Основной runtime для полного MVP stack, KV-cache, OpenAI-compatible API |
| LLM (local-lite, optional) | Ollama + Qwen2.5-7B-Q4 или mock LLM | Fallback для Mac 8 GB: документация, frontend, unit-тесты, отладка без полного stack |
| LLM Vision (опц.) | vLLM + Qwen2.5-VL-7B | Описание чертежей при ingestion, профиль `ingest` |
| Embeddings | nomic-embed-text через embedding adapter; Ollama допустим как local-lite fallback | Лёгкая модель, хорошее качество для русского; реализация должна быть заменяемой |
| Vector DB | Qdrant v1.9 | Self-hosted, payload filters для RBAC, активное развитие |
| Graph DB | Neo4j 5.18 Community | Cypher, визуализация в браузере, Python driver |
| Orchestration | LangGraph 0.2+ | Multi-Agent: OrchestratorAgent, Retrievers, GeneratorAgent, CriticAgent; `Send()` API для параллельного запуска |
| Document Preparation | pymupdf + easyocr + Qwen2.5-VL | Слой 1: текст/OCR; Слой 2: vision для чертежей |
| API | FastAPI + uvicorn | Async, OpenAPI автогенерация, streaming |
| Frontend | React + TypeScript + Tailwind | Компонентный подход, react-force-graph для Explorer |
| Observability | OpenTelemetry SDK + Langfuse + Prometheus + Grafana | OTel — стандарт инструментирования; Langfuse — LLM трейсы (OTLP); Prometheus/Grafana — инфраструктурные метрики |
| Database (Langfuse) | PostgreSQL | Хранение трейсов, Knowledge Gaps, сессий |
| Infra | Docker Compose | Одна команда запуска, пинированные образы; профиль `ingest` для vision-модели |
| GPU Dev | VM 64 GB RAM + NVIDIA RTX 4090 24 GB VRAM | Основная среда разработки полного stack и предварительных нагрузочных тестов |
| Cloud / Demo / Prod-like | Yandex Cloud gpu-standard-v3 (T4 16GB) или другой GPU-сервер | Production-like демо; финальный sizing подтверждается нагрузочным тестом |

---

## 10. Архитектурные ограничения

- Система разворачивается как монолитный docker-compose стек (не Kubernetes — вне скоупа MVP)
- Аутентификация реализована через HTTP заголовок с ролью (не JWT — вне скоупа MVP)
- Ingestion выполняется в batch режиме (не real-time streaming)
- Один инстанс каждого сервиса (без репликации — вне скоупа MVP)
- Управление секретами через `.env` файл (Vault — вне скоупа MVP, рекомендован для Scale)
- User Channels в MVP ограничены веб-браузером (React UI)

---

## 11. Критерии приёмки MVP

| ID | Критерий | Способ проверки |
|---|---|---|
| AC-01 | `docker compose up` запускает весь стек без ошибок | Запуск на чистой машине |
| AC-02 | Вопрос на русском → ответ с источниками | Ручное тестирование, 10 вопросов |
| AC-03 | Junior не получает документы с access_level > 1 | Автотест для каждой роли |
| AC-04 | Knowledge Graph содержит >50 узлов и >100 рёбер | Neo4j Browser: `MATCH (n) RETURN count(n)` |
| AC-05 | Трейсы всех запросов видны в Langfuse | Отправить 5 запросов, проверить UI |
| AC-06 | Нет обращений к внешним API | Проверка network logs |
| AC-07 | C4 (4 уровня) + Deployment + Sequence + Data Flow + ER диаграммы в репозитории | Ревью репозитория |
| AC-08 | 5 ADR с trade-off analysis | Ревью `/docs/ADR/` |
| AC-09 | Нагрузочный отчёт с P95 latency и RPS | `/docs/load_test_report.md` |
| AC-10 | Видео-демо 5–7 минут с тремя сценариями и логами vLLM | Просмотр видео |
| AC-11 | Вопрос без ответа → фиксируется в `/knowledge-gaps`, пользователь видит информативное сообщение | Отправить вопрос вне тематики корпуса, проверить `GET /knowledge-gaps` |
| AC-12 | Ответ содержит `confidence_score`; при использовании документа старше 12 месяцев — предупреждение об актуальности | Проверить ответ с источником с `last_updated` > 1 года |
| AC-13 | Онтология загружена из `ontology.json`; одна и та же сущность под разными именами создаёт один узел в Neo4j | Neo4j Browser: проверить отсутствие дублей по canonical name |

---

## 12. Out of Scope (MVP)

Следующие функции намеренно исключены из MVP и запланированы для этапа Scale:

- **JWT-аутентификация и Identity Provider** — интеграция с LDAP/Active Directory; в MVP роль передаётся через HTTP заголовок
- **Kubernetes развёртывание** — Helm charts, автомасштабирование
- **Corporate Systems интеграция** — ERP (1С), CRM, HR-система, GitLab, Confluence; показаны в C4 Level 1 как будущие интеграции; в MVP документы загружаются вручную через `POST /ingest`
- **User Channels расширение** — Mobile App, Slack/Teams bot, REST API для внешних систем; в MVP только веб-браузер
- **Real-time обновление графа** при изменении документов (только batch ingestion)
- **Cross-encoder reranker** — только скоринговый merge 0.7/0.3
- **MLOps pipeline** — автоматическое переобучение эмбеддингов
- **SLA и production-grade мониторинг**
- **Document Preparation (расширенный):** OCR промышленного качества (Tesseract 5), автоматическая классификация `access_level` через LLM, коннекторы к Confluence и GitLab — в MVP метаданные проставляются оператором вручную; Слой 2 Vision (Qwen2.5-VL) реализуется при наличии времени и VRAM
- **Multi-Agent расширение:** SupervisorAgent + доменные агенты по типу документа (PolicyAgent, TechnicalAgent, HRAgent) — базовая мультиагентная архитектура (Orchestrator + Retrievers + Critic) реализована в MVP
- **Knowledge Decay Detection:** автоматические уведомления владельцам документов об устаревании, визуализация «холодных» узлов в Explorer — в MVP только `confidence_score` в ответе
- **Tacit Knowledge Capture:** захват неявных знаний из Slack/почты
- **Knowledge Health Dashboard:** панель состояния корпуса

---

## 13. Связанные документы

- `CONCEPT.md` — концепция проекта, value proposition, архитектурные принципы, поэтапная стратегия
- `ADD.md` — Architecture Design Document, технические детали реализации
- `ADR/` — Architecture Decision Records, обоснование технических решений
- `docs/diagrams/` — C4 (4 уровня), Deployment, Sequence, Data Flow, ER диаграммы
- `docs/capacity_planning.md` — расчёт ресурсов инфраструктуры
- `docs/load_test_report.md` — результаты нагрузочного тестирования
