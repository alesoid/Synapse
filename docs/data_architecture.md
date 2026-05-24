# Data Architecture — Synapse GraphRAG Knowledge Platform

**Версия:** 1.0  
**Дата:** 17 мая 2026  
**Автор:** Алеся Мороз  
**Статус:** Утверждено

---

## 1. Источники данных

Система принимает корпоративные документы в следующих форматах:

| Формат | Библиотека парсинга | Что извлекается |
|---|---|---|
| PDF (текстовый) | pymupdf | Нативный текст, структура блоков, очистка колонтитулов и служебных символов |
| PDF (скан) | pymupdf + easyocr | Растеризация 300 DPI, OCR ru+en |
| PDF (чертёж/схема) | pymupdf + Qwen2.5-VL | Текстовое описание изображения при `VISION_ENABLED=true` (если OCR < 50 токенов) |
| DOCX | python-docx | Основной текст, стили, очистка ревизий и скрытого текста |
| XLSX | openpyxl | Значения ячеек, очистка пустых строк и формул (только значения) |
| Markdown | прямой текст | Очистка HTML-комментариев и front matter |
| CSV | pandas | Очистка пустых строк и BOM |

Метаданные документа указываются оператором вручную при вызове `POST /ingest`. Автоматическая классификация `access_level` запланирована на Scale-этап.

---

## 2. Document Lifecycle

Путь документа от загрузки до ответа пользователю:

```
Сырой документ (PDF / DOCX / XLSX / Markdown / CSV / скан)
        │
        ▼
┌─────────────────────────────────────────────────┐
│           Document Preparation Pipeline          │
│                                                  │
│  1. Парсинг и очистка        ← pymupdf          │
│  2. OCR (при необходимости)  ← easyocr          │
│  3. Vision-описание (опц.)   ← Qwen2.5-VL       │
│  4. Структурирование по разделам (H1/H2)         │
│  5. Нормализация терминов    ← ontology.json     │
│  6. Разметка метаданных оператором               │
│  7. Валидация                                    │
└──────────────────────────┬──────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────┐
│              Ingestion Pipeline                  │
│                                                  │
│  8.  Chunking (500 токенов / overlap 50)         │
│  9.  Embeddings (nomic-embed-text, 768-dim)      │
│  10. Запись чанков → Qdrant (vectors + payload)  │
│  11. Извлечение сущностей и связей ← LLM (JSON) │
│  12. Запись узлов и рёбер → Neo4j               │
│  13. Логирование результатов (audit_log)         │
└──────────────────────────┬──────────────────────┘
                           │
                           ▼
               Indexed Knowledge Base
         (Qdrant + Neo4j + PostgreSQL)
                           │
                           ▼
┌─────────────────────────────────────────────────┐
│              Query Pipeline (LangGraph)          │
│                                                  │
│  1. Input Guardrails (PII, prompt injection)     │
│  2. VectorRetrieverAgent → Qdrant (RBAC filter)  │
│  3. GraphRetrieverAgent  → Neo4j (RBAC filter)   │
│  4. Merge: 0.7 × vector + 0.3 × graph           │
│  5. GeneratorAgent → vLLM → ответ               │
│  6. CriticAgent → quality_score                  │
│  7. Retry если quality_score < 3 (до 3 раз)     │
│  8. Output Guardrails (PII фильтрация)           │
│  9. Knowledge Gap Detection (при score < 2)      │
└──────────────────────────┬──────────────────────┘
                           │
                           ▼
          answer + sources + quality_score
                 + confidence_score
```

**Правило валидации при ingestion.** Документ отклоняется (HTTP 422) если:
- текст пустой после очистки
- `access_level` не указан
- объём менее 100 токенов после подготовки

---

## 3. Metadata Contract

Каждый документ, чанк и узел графа несёт единый набор обязательных метаданных:

| Поле | Тип | Обязательно | Описание | Пример |
|---|---|:---:|---|---|
| `doc_id` | string | ✅ | Уникальный идентификатор документа | `"arch-001"` |
| `doc_type` | enum | ✅ | Тип документа | `"adr"`, `"standard"`, `"policy"`, `"onboarding"`, `"technical"`, `"hr"` |
| `access_level` | int 1–5 | ✅ | Минимальный уровень доступа (RBAC) | `3` |
| `last_updated` | date | ✅ | Дата последнего обновления документа | `"2025-11-01"` |
| `source` | string | — | Путь к оригинальному файлу | `"docs/ADR/ADR-001.md"` |
| `extraction_source` | enum | — | Способ извлечения текста | `"native"`, `"ocr"`, `"vision"` |

Метаданные проставляются оператором при вызове `POST /ingest` и наследуются каждым чанком в Qdrant и каждым узлом в Neo4j. Это обеспечивает сквозной RBAC от документа до ответа.

---

## 4. Схема Qdrant

### Коллекция `chunks`

```python
client.create_collection(
    collection_name="chunks",
    vectors_config=VectorParams(
        size=768,           # nomic-embed-text размерность
        distance=Distance.COSINE
    )
)
```

### Структура точки (Point)

| Поле | Тип | Описание |
|---|---|---|
| `id` | UUID | Уникальный идентификатор чанка |
| `vector` | float[768] | Эмбеддинг чанка (nomic-embed-text) |
| `payload.doc_id` | string | Идентификатор родительского документа |
| `payload.doc_type` | string | Тип документа |
| `payload.access_level` | int | Уровень доступа — ключевое поле для RBAC |
| `payload.last_updated` | date | Дата обновления — используется для `confidence_score` |
| `payload.source` | string | Путь к оригинальному файлу |
| `payload.text` | string | Текст чанка (500 токенов) |
| `payload.section_title` | string | Заголовок раздела (H1/H2), из которого взят чанк |
| `payload.chunk_index` | int | Порядковый номер чанка внутри документа |
| `payload.extraction_source` | string | `native` / `ocr` / `vision` |

### RBAC-фильтр при поиске

```python
client.search(
    collection_name="chunks",
    query_vector=embedding,
    query_filter=Filter(
        must=[FieldCondition(
            key="access_level",
            range=Range(lte=user_access_level)   # только чанки с access_level ≤ роли пользователя
        )]
    ),
    limit=10
)
```

Фильтрация применяется **во время поиска** (не постфильтрация) — недоступные чанки не попадают в результат и не передаются в LLM.

---

## 5. Схема Neo4j

### Узлы (Nodes)

#### MVP — реализовано (`_ALLOWED_LABELS` в `graph_repository.py`)

| Label | Свойства | Описание |
|---|---|---|
| `Document` | `id`, `title`, `doc_type`, `access_level`, `last_updated` | Корневой узел документа |
| `Section` | `id`, `title`, `content_summary`, `access_level`, `doc_id` | Раздел документа (H1/H2), соответствует чанку в Qdrant |
| `Concept` | `id`, `name`, `canonical_name`, `access_level` | Абстрактное понятие предметной области (нормализованное через `ontology.json`) |

#### Scale — planned (не реализовано; расширят граф для более богатого traversal)

| Label | Свойства | Описание | Статус |
|---|---|---|---|
| `System` | `id`, `name`, `canonical_name`, `description`, `version` | Информационная система или инструмент | 🔲 planned |
| `Process` | `id`, `name`, `description`, `access_level` | Бизнес-процесс или workflow | 🔲 planned |
| `Role` | `id`, `name`, `access_level` | Организационная роль | 🔲 planned |
| `Policy` | `id`, `name`, `description`, `access_level` | Регламент, политика, стандарт | 🔲 planned |

Нормализация имён: entity extractor выполняет fuzzy match по `ontology.json` (порог 0.85). При совпадении используется `canonical_name` — новый узел не создаётся, дублей нет.

### Рёбра (Relationships)

#### MVP — реализовано (`_ALLOWED_REL_TYPES` в `graph_repository.py`)

| Тип | Откуда → Куда | Описание |
|---|---|---|
| `HAS_SECTION` | Document → Section | Документ содержит раздел |
| `REFERENCES` | Document/Section → Concept | Документ или раздел ссылается на понятие |

#### Scale — planned (зависят от реализации узлов System / Process / Role / Policy)

| Тип | Откуда → Куда | Описание | Статус |
|---|---|---|---|
| `GOVERNED_BY` | Process → Policy | Процесс регулируется политикой | 🔲 planned |
| `REQUIRES` | Role → Concept/System | Роль требует знания или инструмента | 🔲 planned |
| `USES` | Process → System | Процесс использует систему | 🔲 planned |
| `APPLIES_TO` | Policy → Role/Process | Политика применяется к роли или процессу | 🔲 planned |
| `DEPENDS_ON` | System → System | Зависимость между системами | 🔲 planned |

> **Архитектурное замечание.** MVP-граф (3 типа узлов, 2 типа рёбер) намеренно упрощён для снижения сложности entity extraction. Расширение до 7 типов узлов в Scale-этапе потребует LLM-based extraction (ADR-013) вместо текущего regex + ontology matching, а также полной переиндексации Neo4j.

### RBAC-фильтр при traversal

```cypher
MATCH (d:Document)-[:HAS_SECTION]->(s:Section)
WHERE COALESCE(d.access_level, 1) <= $user_level
  AND COALESCE(s.access_level, 1) <= $user_level
RETURN d, s
LIMIT 10
```

`COALESCE(access_level, 1)` трактует узлы без явного `access_level` как публичные (уровень 1) — согласованно с поведением `filter_authorized_items` в `backend/security/rbac.py`.

### Целевые метрики графа (AC-04)

После загрузки тестового корпуса (MVP-граф): более 50 узлов, более 100 рёбер.

---

## 6. Схема хранилищ — статус реализации

| Таблица | Хранилище | Статус | Файл |
|---|---|---|---|
| `knowledge_gaps` | SQLite WAL | ✅ Реализовано | `backend/db/gap_store.py` |
| `audit_log` | SQLite WAL | ✅ Реализовано (MVP) | `backend/db/audit_store.py` |
| `audit_log` (production) | PostgreSQL | 🔲 Planned (Scale) | — |
| Langfuse traces | PostgreSQL (managed by Langfuse) | ✅ Реализовано | Langfuse container |

---

### Таблица `knowledge_gaps` — ✅ реализовано

Реализована в `backend/db/gap_store.py` как SQLite WAL (single-process, local-lite fallback). Спецификация (FR-32a/b) предписывает PostgreSQL для production — переход запланирован на Scale-этап.

**Реальная схема (SQLite, `gap_store.py`):**

```sql
CREATE TABLE IF NOT EXISTS knowledge_gaps (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    query         TEXT    NOT NULL,        -- plain text (намеренно, для анализа пробелов)
    access_level  INTEGER NOT NULL,
    quality_score REAL    NOT NULL,
    iterations    INTEGER NOT NULL DEFAULT 0,
    timestamp     TEXT    NOT NULL         -- ISO UTC datetime
);
```

> Поля `user_role` и `status` отсутствуют в текущей реализации. `status` ('open' | 'in_progress' | 'resolved') запланирован для Scale-этапа, когда knowledge gaps станут управляемым workflow для операторов.

---

### Таблица `audit_log` — 🔲 planned (Scale)

**Не реализована в MVP.** Ни файла, ни подключения к PostgreSQL в `backend/` не существует.

Audit logging для MVP обеспечивается косвенно через Langfuse traces (каждый запрос трассируется) и `knowledge_gaps` (фиксируются неотвеченные запросы).

**Целевая схема для Scale (PostgreSQL):**

```sql
-- Целевая схема — не реализована в MVP
CREATE TABLE audit_log (
    id            SERIAL PRIMARY KEY,
    user_role     VARCHAR(20)   NOT NULL,
    access_level  INT           NOT NULL,
    query_hash    VARCHAR(64)   NOT NULL,   -- SHA-256 текста запроса (plain text не хранится)
    result_count  INT,                      -- число найденных чанков
    quality_score FLOAT,                    -- оценка CriticAgent (1.0–4.0)
    gap_detected  BOOLEAN       DEFAULT FALSE,
    timestamp     TIMESTAMPTZ   DEFAULT NOW()
);

CREATE INDEX idx_audit_timestamp ON audit_log (timestamp DESC);
CREATE INDEX idx_audit_role ON audit_log (user_role);
```

Реализация требует: подключение к PostgreSQL в `backend/db/`, middleware или dependency в FastAPI для записи каждого запроса, конфигурация через `DATABASE_URL` env var.

### Таблица `langfuse_traces` (управляется Langfuse)

Langfuse хранит трейсы LangGraph-агента в PostgreSQL автоматически. Схема управляется Langfuse-миграциями. Каждый span содержит:

| Атрибут | Описание |
|---|---|
| `trace_id` | Идентификатор трейса E2E запроса |
| `span_name` | Имя ноды агента (`input_guard`, `vector_retriever`, …) |
| `latency_ms` | Время выполнения ноды |
| `role` | Роль пользователя |
| `access_level` | Числовой уровень доступа |
| `chunks_retrieved` | Число найденных чанков |
| `quality_score` | Оценка CriticAgent |
| `confidence_score` | Актуальность источников |
| `tokens_per_second` | Скорость генерации LLM |
| `model_backend` | `vllm` / `ollama` / `mock` |

> **Out of Scope (MVP):** data retention automation и backup strategy. Для диплома достаточно ручного управления через volume snapshot. Рекомендуемое retention для трейсов Langfuse — 7–30 дней (см. `capacity_planning.md`).

---

## 7. Data Lineage — от вопроса до ответа

Полная цепочка прослеживаемости одного запроса:

```
Пользователь задаёт вопрос
        │
        ▼
FastAPI: X-User-Role → access_level (RBAC)
        │
        ▼
input_guard: валидация запроса, PII-проверка
        │
        ├──────────────────────┐
        ▼                      ▼
VectorRetrieverAgent    GraphRetrieverAgent
Qdrant: cosine search   Neo4j: Cypher traversal
filter: access_level≤N  WHERE access_level≤N
→ top-10 chunks         → related nodes/sections
        │                      │
        └──────────┬───────────┘
                   ▼
             merge_results
         0.7 × vector + 0.3 × graph
         → ranked документы с источниками
                   │
                   ▼
           GeneratorAgent
           vLLM + системный промпт
           → answer (stream)
                   │
                   ▼
           confidence_score
           avg(1 - age_days/365) по источникам
                   │
                   ▼
            CriticAgent
           LLM-as-a-Judge
           → quality_score (1–5) + feedback
                   │
          ┌────────┴────────┐
          │ quality_score   │ quality_score
          │     ≥ 3         │     < 3
          ▼                 ▼
    output_guard      retry (до 3 раз)
    PII фильтрация    или knowledge_gap
          │
          ▼
    Ответ пользователю:
    {
      answer,
      sources: [{ doc_id, section, last_updated, access_level, retrieval_score }],
      quality_score,
      confidence_score,
      gap_detected,
      trace_id        ← ссылка на трейс в Langfuse
    }
          │
          ▼
    audit_log (PostgreSQL): user_role, query_hash, result_count, quality_score
    Langfuse trace: все spans от input_guard до output_guard
```

**Принцип:** данные, недоступные пользователю по RBAC, не попадают в LLM — они физически не извлекаются из хранилищ, а не фильтруются постфактум из ответа.

---

## 8. Связанные документы

- `ADD.md` — детали Document Preparation Pipeline и Security Model
- `docs/api/openapi.yaml` — API контракт (схемы IngestRequest, QueryResponse, SourceReference)
- `ADR-002-vectordb.md` — обоснование выбора Qdrant
- `ADR-003-graphdb.md` — схема Neo4j, Cypher-примеры
- `ADR-005-rbac.md` — RBAC модель
- `ADR-006-embeddings.md` — nomic-embed-text, 768-dim
- `ADR-008-chunking.md` — параметры chunking (500 / overlap 50)
- `docs/capacity_planning.md` — sizing хранилищ, retention policy
