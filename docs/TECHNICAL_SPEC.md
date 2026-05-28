# Synapse — Техническое Задание (TECHNICAL_SPECIFICATION)

**Версия:** 1.6  
**Дата:** 17 мая 2026  
**Автор:** [Алеся Мороз]  
**Статус:** Утверждён  
**Область действия:** документ описывает MVP для защиты проектной работы 3 июня 2026 года. MVP реализуется в двух режимах: `local-lite` для разработки и тестирования на Mac M3 8 GB RAM с mock/lightweight backend-ами и `gpu-demo` для финального запуска через Docker Compose на сервере с RTX 4090 24 GB VRAM. PoC-функции реализуются первыми и входят в MVP; Scale-функции вынесены за рамки защиты.


**История изменений:**
| Версия | Дата | Изменения |
|---|---|---|
| 1.0 | 10 мая 2026 | Первая версия |
| 1.1 | 11 мая 2026 | Добавлены Knowledge Gap Detection, Confidence Score, Domain Ontology |
| 1.2 | 11 мая 2026 | Расширены форматы документов, добавлены User Channels, Corporate Systems, Identity Provider, Architecture Principles |
| 1.3 | 11 мая 2026 | Multi-Agent Architecture и Document Preparation Pipeline (OCR + Vision) перенесены из Scale в MVP; добавлен OpenTelemetry; обновлены FR, tech stack, Out of Scope |
| 1.4 | 17 мая 2026 | FR декомпозированы до атомарных; добавлена колонка Тип к FR; добавлена колонка Источник к NFR; добавлена матрица трассируемости FR → AC |
| 1.5 | 17 мая 2026 | Добавлена колонка Этап (PoC / MVP) к FR; добавлена строка Область действия в шапку |
| 1.6 | 21 мая 2026 | Уточнены профили `local-lite` и `gpu-demo`, дата защиты 3 июня 2026, снижены риски MVP: OCR/Vision/streaming/расширенный Explorer вынесены в Should Have |

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

### Этап 1: PoC / local-lite
**Срок:** до 25 мая 2026  
**Среда:** Mac M3 8 GB RAM  
**Результат:** рабочий прототип с Markdown ingestion, mock LLM, mock/lightweight embeddings, базовым GraphRAG retrieval, RBAC smoke-тестами и проверяемым LangGraph flow.

В этом режиме не запускается полный LLM/observability stack. Цель local-lite — быстро разрабатывать и проверять бизнес-логику без зависимости от GPU.

### Этап 2: MVP / gpu-demo
**Срок:** до 30 мая 2026  
**Среда:** Docker Compose на сервере с RTX 4090 24 GB VRAM  
**Результат:** демонстрируемая End-to-End система: vLLM + Qwen2.5-14B-AWQ, Qdrant, Neo4j, FastAPI, Web UI, Langfuse, Prometheus/Grafana, evaluation report и load test report.

MVP должен показать ключевые требования курса: локальную open-source LLM, GraphRAG, LangGraph/stateful pipeline, RBAC до передачи контекста в LLM, Guardrails, разделение Control Plane / Data Plane и измеримые метрики качества/производительности.

### Этап 3: Scale
**Срок:** к определению по результатам тестирования MVP  
**Среда:** к определению по результатам тестирования MVP  
**Результат:** архитектурная проработка перехода Synapse к production-ready платформе: JWT/LDAP/AD, Kubernetes/Helm, коннекторы к корпоративным системам, MLOps pipeline, production HA/SLA, расширенный multimodal RAG и автоматическая классификация `access_level`.

Функции этапа Scale не входят в MVP и используются как roadmap промышленного развития системы.

> В MVP Vision используется только как опциональный preprocessing-слой при ingestion (`Qwen2.5-VL` описывает страницы со схемами/чертежами). Полноценный Multimodal RAG в Scale означает пользовательские запросы и retrieval/generation по изображениям, таблицам и схемам как первичным источникам.

---

## 5. Функциональные требования

> **Типы требований:**
> - `Functional` — базовая функциональность системы
> - `Security` — требования информационной безопасности и разграничения доступа
> - `AI-specific` — требования специфичные для AI/ML систем (качество модели, retrieval, агентная логика)
> - `Observability` — мониторинг, трейсинг, метрики

> **Этапы реализации:**
> - `PoC` — реализуется в рамках Proof of Concept (до 25 мая 2026); цель — подтвердить техническую гипотезу GraphRAG
> - `MVP` — реализуется в рамках MVP / gpu-demo (до 30 мая 2026); цель — подготовить демонстрируемую систему для защиты 3 июня 2026

> **Граница MVP:** обязательный путь защиты — Markdown corpus → ingestion → Qdrant/Neo4j → hybrid retrieval → RBAC → LangGraph pipeline → ответ с источниками → confidence_score → traces/metrics → evaluation/load report.
>
> OCR, Vision preprocessing, streaming response и расширенный Graph Explorer считаются `Should Have`: они выполняются только если не угрожают стабильности основного End-to-End pipeline.


### 5.1 Q&A режим

| ID | Требование | Тип | Этап | Приоритет | AC |
|---|---|---|---|---|---|
| FR-01 | Система принимает запрос на русском языке от авторизованного пользователя | Functional | PoC | Must Have | AC-02 |
| FR-02a | Система выполняет векторный поиск по чанкам в Qdrant с RBAC фильтром | Functional | PoC | Must Have | AC-02 |
| FR-02b | Система выполняет графовый траверсал в Neo4j с RBAC фильтром | Functional | PoC | Must Have | AC-02 |
| FR-02c | Система объединяет результаты поиска через Reciprocal Rank Fusion (RRF): `alpha/(k+rank_v) + (1-alpha)*graph_signal/(k+rank_g)`, `alpha=0.7`, `k=60` | AI-specific | PoC | Must Have | AC-02 |
| FR-03 | Система возвращает ответ с указанием источников (название документа, раздел) | Functional | PoC | Must Have | AC-02 |
| FR-04 | Система фильтрует результаты поиска по уровню доступа пользователя до передачи контекста в LLM | Security | MVP | Must Have | AC-03 |
| FR-06 | Система возвращает streaming-ответ (токены передаются по мере генерации) | Functional | MVP | Should Have | — |

### 5.2 Explorer режим

| ID | Требование | Тип | Этап | Приоритет | AC |
|---|---|---|---|---|---|
| FR-07 | Admin/Analyst может получить данные графа знаний через API или Neo4j Browser; полноценная React-визуализация является расширением | Functional | MVP | Should Have | AC-04 |
| FR-08 | Клик по узлу графа в React UI показывает связанные документы и отношения | Functional | MVP | Should Have | — |
| FR-09 | Explorer режим доступен только пользователям с ролью Admin (access_level=5) | Security | MVP | Must Have | AC-03 |

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

| ID | Требование | Тип | Этап | Приоритет | AC |
|---|---|---|---|---|---|
| FR-10 | Парсер извлекает чистый текст из PDF, Markdown, CSV, DOCX, XLSX с удалением артефактов форматирования (колонтитулы, водяные знаки, служебные символы) | Functional | PoC | Must Have | AC-01 |
| FR-10a | **[Слой 1, опционально]** Для отсканированных PDF (нативный текст < 50 токенов на страницу) система применяет OCR через easyocr (ru+en) на растеризованных страницах (300 DPI) | Functional | MVP | Should Have | AC-01 |
| FR-10b | **[Слой 2, опционально]** Для страниц с чертежами и схемами (текст < 50 токенов после OCR) система генерирует текстовое описание через Qwen2.5-VL-7B; активируется через `VISION_ENABLED=true`; запускается только при ingestion, не конкурирует с основной моделью за VRAM | AI-specific | MVP | Should Have | — |
| FR-11 | Структурирование выделяет логические разделы документа по заголовкам; каждый раздел становится отдельным узлом типа `Section` в Neo4j | Functional | PoC | Must Have | AC-04 |
| FR-12 | Нормализация приводит роли, названия систем и процессов к единому словарю Synapse Corp (например: «тимлид» → `Tech Lead`, «наш gitlab» → `GitLab`) | AI-specific | MVP | Should Have | AC-13 |
| FR-13 | Разметка метаданных: оператор проставляет `access_level` (1–5), тип документа (`policy`, `standard`, `instruction`, `matrix`) и идентификатор при загрузке через `POST /ingest` | Functional | MVP | Must Have | AC-03 |
| FR-14a | Валидация отклоняет документ если текст пустой после очистки | Functional | PoC | Must Have | AC-01 |
| FR-14b | Валидация отклоняет документ если `access_level` не указан | Security | MVP | Must Have | AC-03 |
| FR-14c | Валидация отклоняет документ если объём менее 100 токенов | Functional | PoC | Must Have | AC-01 |
| FR-15 | Система логирует результат подготовки каждого документа: количество извлечённых разделов, итоговый объём токенов, источник извлечения (`native` / `ocr` / `vision`), статус валидации | Observability | MVP | Should Have | — |

> **Scale-этап:** автоматическая классификация `access_level` через LLM на основе содержания документа; OCR промышленного качества (Tesseract 5); коннекторы к Confluence и GitLab.

### 5.4 Ingestion Pipeline

| ID | Требование | Тип | Этап | Приоритет | AC |
|---|---|---|---|---|---|
| FR-16 | Система принимает Markdown-документы из `docs/corpus/adapted`; поддержка PDF, CSV, DOCX, XLSX относится к расширению Document Preparation Pipeline | Functional | PoC | Must Have | AC-01 |
| FR-17a | Система выполняет chunking с размером 500 токенов | Functional | PoC | Must Have | AC-04 |
| FR-17b | Система выполняет chunking с overlap 50 токенов между соседними чанками | Functional | PoC | Must Have | AC-04 |
| FR-18a | Система извлекает сущности из документов: в `local-lite` через deterministic/mock extractor, в `gpu-demo` через LLM в JSON-формате | AI-specific | PoC | Must Have | AC-04 |
| FR-18b | Система извлекает связи между сущностями: в `local-lite` через rules/mock extractor, в `gpu-demo` через LLM в JSON-формате | AI-specific | PoC | Must Have | AC-04 |
| FR-19a | Система записывает чанки с эмбеддингами в Qdrant | Functional | PoC | Must Have | AC-02 |
| FR-19b | Система записывает граф сущностей в Neo4j | Functional | PoC | Must Have | AC-04 |
| FR-20 | Каждый чанк в Qdrant и каждый узел в Neo4j размечается `access_level` (1–5) при загрузке | Security | MVP | Must Have | AC-03 |

### 5.5 RBAC

| ID | Требование | Тип | Этап | Приоритет | AC |
|---|---|---|---|---|---|
| FR-21 | Система поддерживает 5 ролей: Junior(1), Middle(2), Senior(3), Manager(4), Admin(5) | Security | MVP | Must Have | AC-03 |
| FR-22a | Векторный поиск в Qdrant возвращает только чанки с `access_level ≤ уровню пользователя` | Security | MVP | Must Have | AC-03 |
| FR-22b | Графовый траверсал в Neo4j возвращает только узлы с `access_level ≤ уровню пользователя` | Security | MVP | Must Have | AC-03 |
| FR-23 | Попытка доступа к закрытому документу возвращает HTTP 403 с информативным сообщением | Security | MVP | Must Have | AC-03 |

> **MVP:** роль передаётся через HTTP заголовок `X-User-Role`. JWT и интеграция с Identity Provider (LDAP/AD) — Scale-этап (см. раздел 13).

### 5.6 User Channels

Пользователи взаимодействуют с Synapse через различные каналы доступа. В MVP реализован веб-браузер (React UI). В Scale-этапе планируется расширение каналов.

| ID | Требование | Тип | Этап | Приоритет | AC |
|---|---|---|---|---|---|
| FR-43 | В MVP пользователь взаимодействует с системой через веб-браузер (React UI на порту 3000) | Functional | MVP | Must Have | AC-01 |
| FR-44 | Архитектура системы не привязана к конкретному каналу доступа — запросы поступают через API Gateway независимо от канала | Functional | MVP | Must Have | AC-07 |

> **Scale-этап:** Mobile App, Slack/Teams bot, REST API для внешних систем.

### 5.7 Guardrails

| ID | Требование | Тип | Этап | Приоритет | AC |
|---|---|---|---|---|---|
| FR-25a | Input Guardrail обнаруживает и маскирует email в запросе пользователя | Security | MVP | Must Have | AC-03 |
| FR-25b | Input Guardrail обнаруживает и маскирует телефонные номера в запросе пользователя | Security | MVP | Must Have | AC-03 |
| FR-25c | Input Guardrail обнаруживает и маскирует паспортные данные в запросе пользователя | Security | MVP | Must Have | AC-03 |
| FR-26 | Input Guardrail блокирует базовые prompt injection паттерны до передачи запроса в LLM | Security | MVP | Must Have | AC-03 |
| FR-27 | Output Guardrail проверяет ответ LLM на наличие PII перед отдачей пользователю | Security | MVP | Must Have | AC-03 |

### 5.8 Observability

| ID | Требование | Тип | Этап | Приоритет | AC |
|---|---|---|---|---|---|
| FR-28a | Каждый запрос инструментируется через OpenTelemetry SDK | Observability | MVP | Must Have | AC-05 |
| FR-28b | OTel трейсы экспортируются в Langfuse по протоколу OTLP с latency каждой ноды LangGraph | Observability | MVP | Must Have | AC-05 |
| FR-29a | Prometheus собирает метрику `request_latency_seconds` | Observability | MVP | Must Have | AC-09 |
| FR-29b | Prometheus собирает метрику `request_count_total` | Observability | MVP | Must Have | AC-09 |
| FR-29c | Prometheus собирает метрику `tokens_per_second` | Observability | MVP | Must Have | AC-09 |
| FR-30 | Grafana дашборд отображает latency, RPS, error rate, tokens/sec | Observability | MVP | Must Have | AC-09 |

### 5.9 Multi-Agent Architecture

Реализация паттерна Multi-Agent Collaboration через LangGraph `Send()` API. Подробное описание — ADR-012.

| ID | Требование | Тип | Этап | Приоритет | AC |
|---|---|---|---|---|---|
| FR-45 | Условное ребро `dispatch_retrievers` от `prepare_query` запускает `vector_retriever` и `graph_retriever` параллельно через LangGraph `Send()` API | AI-specific | MVP | Must Have | AC-02 |
| FR-46a | Нода `vector_retriever` применяет RBAC фильтр при поиске в Qdrant | Security | MVP | Must Have | AC-03 |
| FR-46b | Нода `graph_retriever` применяет RBAC фильтр при траверсале Neo4j | Security | MVP | Must Have | AC-03 |
| FR-47a | Нода `critic` получает вопрос + ответ + источники и возвращает `quality_score` в формате JSON | AI-specific | MVP | Must Have | AC-02 |
| FR-47b | Нода `critic` возвращает текстовый `feedback` с обоснованием оценки | AI-specific | MVP | Must Have | AC-02 |
| FR-48a | При `quality_score < retry_threshold` условное ребро `should_retry` от `confidence_score` повторяет параллельный retrieval через `Send()` | AI-specific | MVP | Must Have | AC-02 |
| FR-48b | Максимальное число итераций retry ограничено тремя | AI-specific | MVP | Must Have | AC-02 |
| FR-49 | Каждый агент инструментируется отдельным OTel span — в Langfuse видна latency каждого агента независимо | Observability | MVP | Should Have | AC-05 |

### 5.10 Knowledge Gap Detection

Механизм выявления пробелов в корпусе знаний на основе анализа неуспешных запросов.

| ID | Требование | Тип | Этап | Приоритет | AC |
|---|---|---|---|---|---|
| FR-31 | Если агент завершает работу с `quality_score < 2` после максимального числа итераций — запрос фиксируется как «неотвеченный» | AI-specific | MVP | Must Have | AC-11 |
| FR-32a | Неотвеченный запрос сохраняется в PostgreSQL с текстом запроса и ролью пользователя | Functional | MVP | Must Have | AC-11 |
| FR-32b | Неотвеченный запрос сохраняется в PostgreSQL с timestamp и числом итераций | Observability | MVP | Must Have | AC-11 |
| FR-33 | Эндпоинт `GET /knowledge-gaps` возвращает список неотвеченных запросов за период (доступен только Admin) | Security | MVP | Must Have | AC-11 |
| FR-34 | В ответе пользователю при неуспешном поиске явно указывается: «Информация по данному вопросу отсутствует в корпусе. Запрос зафиксирован для пополнения базы знаний» | Functional | MVP | Must Have | AC-11 |

### 5.11 Knowledge Confidence Score

Оценка актуальности ответа на основе возраста использованных источников.

| ID | Требование | Тип | Этап | Приоритет | AC |
|---|---|---|---|---|---|
| FR-35 | Каждый документ в Qdrant содержит поле `last_updated` (дата последнего обновления) в payload | Functional | MVP | Must Have | AC-12 |
| FR-36a | Агент вычисляет `confidence_score` по формуле `1 - (age_days / 365)` для каждого источника | AI-specific | MVP | Must Have | AC-12 |
| FR-36b | Итоговый `confidence_score` ответа — среднее значение по всем использованным источникам, ограниченное диапазоном [0, 1] | AI-specific | MVP | Must Have | AC-12 |
| FR-37 | Ответ содержит поле `confidence_score` и список источников с датами обновления | Functional | MVP | Must Have | AC-12 |
| FR-38 | Если `confidence_score < 0.5` — ответ сопровождается предупреждением: «Источники могут быть устаревшими. Рекомендуем проверить актуальность документов» | Functional | MVP | Must Have | AC-12 |

### 5.12 Domain Ontology

Явный словарь сущностей предметной области для нормализации Knowledge Graph.

| ID | Требование | Тип | Этап | Приоритет | AC |
|---|---|---|---|---|---|
| FR-39 | Система загружает онтологию предметной области из файла `ontology.json` при запуске | Functional | MVP | Must Have | AC-13 |
| FR-40a | Онтология содержит канонические имена сущностей и их типы | AI-specific | MVP | Must Have | AC-13 |
| FR-40b | Онтология содержит список синонимов для каждой сущности: `{"canonical": "GitLab", "type": "System", "aliases": ["gitlab", "наш gitlab", "система контроля версий"]}` | AI-specific | MVP | Must Have | AC-13 |
| FR-41a | Entity extractor сопоставляет извлечённую сущность с онтологией через fuzzy match | AI-specific | MVP | Must Have | AC-13 |
| FR-41b | Только при отсутствии совпадения в онтологии entity extractor создаёт новый узел в Neo4j | AI-specific | MVP | Must Have | AC-13 |
| FR-42 | Admin может просматривать и редактировать онтологию через эндпоинт `GET/POST /ontology` | Functional | MVP | Should Have | — |

---

## 6. Нефункциональные требования

> **Источники требований:**
> - `Бизнес` — продиктовано целевым UX и ожиданиями пользователей
> - `Железо` — обусловлено характеристиками целевого hardware (T4 16GB, RTX 4090)
> - `ИБ` — требования информационной безопасности и регуляторные ограничения (ФЗ-152)
> - `Академический` — требования дипломного проекта и воспроизводимости
> - `Отраслевой стандарт` — общепринятые практики для AI/ML production-систем

| ID | Требование | Целевое значение | Источник | Обоснование |
|---|---|---|---|---|
| NFR-01 | Latency ответа (P95) на GPU сервере | < 10 сек | Бизнес + Железо | UX-порог терпения пользователя при сложном запросе; T4 16GB с AWQ-квантованием обеспечивает ~5–8 сек на запрос до 200 токенов |
| NFR-02 | Latency ответа (P95) на GPU Dev VM | < 10 сек | Железо | RTX 4090 24GB быстрее T4; цель та же — обеспечить сопоставимый UX в dev-среде |
| NFR-02a | Local Lite Dev на Mac 8 GB | Не является целевой средой полного LLM stack; допускаются mock/stub сценарии и lightweight-тесты | Железо | Apple M3 8GB RAM не поддерживает vLLM; Ollama с 7B-Q4 пригоден только для разработки без LLM-нагрузки |
| NFR-03 | Локальность | 0 обращений к внешним API | ИБ | Требования ФЗ-152 (персональные данные не покидают периметр); политика ИБ заказчика; принцип Zero external APIs |
| NFR-04 | Поддержка языков | Русский и английский | Бизнес | Корпус документов преимущественно на русском; технические термины и код — на английском |
| NFR-05 | Запуск системы | `local-lite` запускается одной командой за < 3 минут; `gpu-demo` запускается через Docker Compose, время cold start vLLM фиксируется отдельно | Академический | Разделяет быстрый smoke-run и реальный GPU runtime с загрузкой модели |
| NFR-06 | Модели | Только open source с поддержкой русского языка | ИБ + Академический | Запрет на проприетарные облачные модели (OpenAI, Anthropic); требование импортозамещения |
| NFR-07 | Хранение данных | Только self-hosted БД (Qdrant, Neo4j, PostgreSQL) | ИБ | Данные не должны покидать корпоративный контур; cloud-managed БД недопустимы |
| NFR-08 | Воспроизводимость | Docker образы с пинированными версиями (не `latest`) | Академический + Отраслевой стандарт | Воспроизводимость результатов диплома; защита от breaking changes при повторном запуске |
| NFR-09 | Toxicity Score | < 0.01 (доля ответов с токсичным/запрещённым контентом) | ИБ + Бизнес | Корпоративный ассистент не должен генерировать грубость или запрещённый контент даже при провокационных запросах; проверяется на `injection`-подмножестве golden dataset через `output_guard`; в MVP реализован через PII/injection regex-гвардрейлы |
| NFR-10 | Data Freshness | MVP (ручной ingestion): время полного выполнения `POST /ingest` на корпусе ≤ 100 документов < 5 минут; Scale (автоматический pipeline): < 15 минут от появления документа до доступности в поиске | Бизнес + Отраслевой стандарт | В MVP ingestion запускается оператором вручную — автоматической синхронизации нет; ограничение осознанное и зафиксировано в Out of Scope; метрика для автоматического pipeline переходит в Scale-этап |
| NFR-11 | Concurrency (параллельные сессии) | MVP: ≥ 5 параллельных запросов без OOM и без деградации P95 latency выше NFR-01; Scale: 100 сессий | Железо + Бизнес | Одна RTX 4090 с vLLM поддерживает continuous batching; при 5 параллельных генерациях по 200 токенов VRAM остаётся в пределах NFR VRAM; измеряется в Сценарии 3 нагрузочного теста (`capacity_planning.md`) |

---

## 7. Матрица трассируемости

Связь функциональных требований с критериями приёмки MVP.

| AC | Критерий приёмки | Связанные FR |
|---|---|---|
| AC-01 | `docker compose up` запускает профиль `local-lite` без ошибок; `gpu-demo` запускается на RTX 4090 через профиль Docker Compose | Запуск на целевой среде профиля |
| AC-02 | Вопрос на русском → ответ с источниками | FR-01, FR-02a, FR-02b, FR-02c, FR-03, FR-45, FR-47a, FR-47b, FR-48a, FR-48b |
| AC-03 | Junior не получает документы с access_level > 1 | FR-04, FR-09, FR-20, FR-21, FR-22a, FR-22b, FR-23, FR-25a, FR-25b, FR-25c, FR-26, FR-27, FR-33, FR-46a, FR-46b |
| AC-04 | Knowledge Graph: >50 узлов, >100 рёбер | FR-07, FR-08, FR-11, FR-17a, FR-17b, FR-18a, FR-18b, FR-19b |
| AC-05 | Трейсы в Langfuse (5 запросов) | FR-28a, FR-28b, FR-49 |
| AC-06 | Нет обращений к внешним API | NFR-03, NFR-06, NFR-07 |
| AC-07 | Все диаграммы в репозитории | FR-44 |
| AC-08 | 5 ADR с trade-off analysis | — (документация, не FR) |
| AC-09 | Load test report с P95 и RPS | FR-29a, FR-29b, FR-29c, FR-30 |
| AC-10 | Видео-демо 5–7 минут | — (демо-артефакт) |
| AC-11 | Knowledge Gap фиксируется | FR-31, FR-32a, FR-32b, FR-33, FR-34 |
| AC-12 | `confidence_score` + предупреждение при старых источниках | FR-35, FR-36a, FR-36b, FR-37, FR-38 |
| AC-13 | Онтология: нет дублей по canonical name | FR-12, FR-39, FR-40a, FR-40b, FR-41a, FR-41b |

---

## 8. Роли пользователей и матрица доступа

| Роль | Access Level | Доступные документы |
|---|---|---|
| Junior | 1 | Публичные регламенты, онбординг-материалы |
| Middle | 2 | + Технические стандарты, инженерные практики |
| Senior | 3 | + Архитектурные решения, ADR, системные документы |
| Manager | 4 | + HR-политики, процессы согласований, бюджеты |
| Admin / Analyst | 5 | Все документы + Explorer режим (граф знаний) |

---

## 9. Входные и выходные данные

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

## 10. Технический стек

| Компонент | Технология | Обоснование |
|---|---|---|
| LLM (gpu-dev / demo / prod-like) | vLLM + Qwen2.5-14B-AWQ | Основной runtime для полного MVP stack, KV-cache, OpenAI-compatible API |
| LLM (local-lite, optional) | Ollama + Qwen2.5-7B-Q4 или mock LLM | Fallback для Mac 8 GB: документация, frontend, unit-тесты, отладка без полного stack |
| LLM Vision (опц.) | vLLM + Qwen2.5-VL-7B | Описание чертежей при ingestion, профиль `ingest` |
| Embeddings | nomic-embed-text через embedding adapter; Ollama допустим как local-lite fallback | Лёгкая модель, хорошее качество для русского; реализация должна быть заменяемой |
| Vector DB | Qdrant v1.9 | Self-hosted, payload filters для RBAC, активное развитие |
| Graph DB | Neo4j 5.18 Community | Cypher, визуализация в браузере, Python driver |
| Orchestration | LangGraph 0.2+ | Multi-Agent StateGraph: `prepare_query`, `vector_retriever`, `graph_retriever`, `generator`, `critic`; параллельный fan-out через `Send()` API (`dispatch_retrievers`), retry через `should_retry` |
| Document Preparation | pymupdf + easyocr + Qwen2.5-VL | Слой 1: текст/OCR; Слой 2: vision для чертежей |
| API | FastAPI + uvicorn | Async, OpenAPI автогенерация, streaming |
| Frontend | React + TypeScript + Tailwind | Компонентный подход, react-force-graph для Explorer |
| Observability | OpenTelemetry SDK + Langfuse + Prometheus + Grafana | OTel — стандарт инструментирования; Langfuse — LLM трейсы (OTLP); Prometheus/Grafana — инфраструктурные метрики |
| Database (Langfuse) | PostgreSQL | Хранение трейсов, Knowledge Gaps, сессий |
| Infra | Docker Compose | Одна команда запуска, пинированные образы; профиль `ingest` для vision-модели |
| GPU Dev | VM 64 GB RAM + NVIDIA RTX 4090 24 GB VRAM | Основная среда разработки полного stack и предварительных нагрузочных тестов |
| Cloud / Demo / Prod-like | Yandex Cloud gpu-standard-v3 (T4 16GB) или другой GPU-сервер | Production-like демо; финальный sizing подтверждается нагрузочным тестом |

---

## 11. Архитектурные ограничения

- Система разворачивается как монолитный docker-compose стек (не Kubernetes — вне скоупа MVP)
- Аутентификация реализована через HTTP заголовок с ролью (не JWT — вне скоупа MVP)
- Ingestion выполняется в batch режиме (не real-time streaming)
- Один инстанс каждого сервиса (без репликации — вне скоупа MVP)
- Управление секретами через `.env` файл (Vault — вне скоупа MVP, рекомендован для Scale)
- User Channels в MVP ограничены веб-браузером (React UI)

---

## 12. Критерии приёмки MVP

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

## 13. Out of Scope (MVP)

Следующие функции намеренно исключены из MVP и запланированы для рассмотрения на этапе Scale:

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

## 14. Связанные документы

- `CONCEPT.md` — концепция проекта, value proposition, архитектурные принципы, поэтапная стратегия
- `ADD.md` — Architecture Design Document, технические детали реализации
- `ADR/` — Architecture Decision Records, обоснование технических решений
- `docs/diagrams/` — C4 (4 уровня), Deployment, Sequence, Data Flow, ER диаграммы; C4 Level 4 описан в `docs/diagrams/c4_level4_code.md`
- `docs/api/openapi.yaml` — API контракт
- `docs/data_architecture.md` — схемы хранилищ и data lineage
- `docs/security_architecture.md` — модель угроз, RBAC, guardrails
- `docs/capacity_planning.md` — расчёт ресурсов инфраструктуры
- `docs/load_test_report.md` — результаты нагрузочного тестирования
