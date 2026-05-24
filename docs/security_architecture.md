# Security Architecture — Synapse GraphRAG Knowledge Platform

**Версия:** 1.0  
**Дата:** 17 мая 2026  
**Автор:** Алеся Мороз  
**Статус:** Утверждено

---

## 1. Принципы безопасности

| Принцип | Описание |
|---|---|
| **Security enforced before inference** | RBAC-фильтрация выполняется до передачи данных в LLM. Недоступный контент физически не извлекается из хранилищ — не фильтруется из готового ответа |
| **Zero external APIs** | Никакие пользовательские или корпоративные данные не покидают периметр. Запрещены обращения к OpenAI, Anthropic и любым внешним сервисам в runtime |
| **Chunk-level access control** | Разграничение доступа применяется на уровне каждого чанка в Qdrant и каждого узла в Neo4j — не на уровне документа целиком |
| **Least privilege** | Пользователь получает минимально необходимый контекст для ответа на свой запрос |
| **Auditability** | Каждый запрос фиксируется в audit log: роль, хэш запроса, результат |

---

## 2. RBAC — три слоя фильтрации

RBAC реализован как три последовательных барьера. Данные проходят через все три до того как попасть в LLM.

```
Входящий запрос
        │
        ▼
┌───────────────────────────────────────┐
│  Слой 1 — API Gateway                 │
│  FastAPI: X-User-Role → access_level  │
│  Неизвестная роль → HTTP 403          │
└──────────────────────┬────────────────┘
                       │
                       ▼
┌───────────────────────────────────────┐
│  Слой 2 — Qdrant (vector search)      │
│  payload filter: access_level ≤ N     │
│  Недоступные чанки не возвращаются    │
└──────────────────────┬────────────────┘
                       │
                       ▼
┌───────────────────────────────────────┐
│  Слой 3 — Neo4j (graph traversal)     │
│  WHERE n.access_level <= $user_level  │
│  Недоступные узлы не обходятся        │
└──────────────────────┬────────────────┘
                       │
                       ▼
              LLM (видит только
           разрешённый контекст)
```

### 2.1 Матрица ролей

| Роль | Access Level | Доступные документы |
|---|:---:|---|
| junior | 1 | Публичные регламенты, онбординг-материалы |
| middle | 2 | + Технические стандарты, инженерные практики |
| senior | 3 | + Архитектурные решения, ADR, системные документы |
| manager | 4 | + HR-политики, процессы согласований |
| admin | 5 | Все документы + Explorer режим |

### 2.2 Слой 1 — API Gateway

```python
# /backend/security/rbac.py
ROLES = {"junior": 1, "middle": 2, "senior": 3, "manager": 4, "admin": 5}

async def get_current_user(
    role: str = Header(..., alias="X-User-Role")
) -> int:
    if role not in ROLES:
        raise HTTPException(
            status_code=403,
            detail=f"Unknown role: {role}"
        )
    return ROLES[role]
```

В MVP роль передаётся через HTTP-заголовок `X-User-Role`. JWT и интеграция с LDAP/AD — Scale-этап. Ограничение явно задокументировано и приемлемо для контролируемой демо-среды.

### 2.3 Слой 2 — Qdrant payload filtering

```python
# /backend/retrieval/hybrid_retriever.py
from qdrant_client.models import Filter, FieldCondition, Range

query_filter = Filter(
    must=[
        FieldCondition(
            key="access_level",
            range=Range(lte=user_access_level)  # ≤ уровню пользователя
        )
    ]
)

results = client.search(
    collection_name="chunks",
    query_vector=embedding,
    query_filter=query_filter,
    limit=10
)
```

Фильтрация применяется **внутри индекса** во время поиска, а не постфильтрацией результатов. Недоступные чанки не участвуют в ранжировании и не передаются в LLM.

### 2.4 Слой 3 — Neo4j WHERE clause

```cypher
-- /backend/retrieval/graph_retriever.py
MATCH (d:Document)-[:HAS_SECTION]->(s:Section)
WHERE d.access_level <= $user_level
  AND s.access_level <= $user_level
RETURN d.title, s.title, s.content_summary
LIMIT 10
```

Условие `WHERE access_level <= $user_level` применяется к каждому узлу в пути traversal — не только к стартовому узлу.

### 2.5 Chunk-level access control

`access_level` проставляется оператором при загрузке документа через `POST /ingest` и наследуется каждым чанком и узлом:

```json
{
  "doc_id": "hr-policy-001",
  "access_level": 4,
  "doc_type": "policy"
}
```

Все чанки этого документа в Qdrant и все связанные узлы в Neo4j получают `access_level = 4`. Пользователь с уровнем 3 (senior) не увидит ни одного фрагмента этого документа — ни в ответе, ни косвенно.

---

## 3. Guardrails

### 3.1 Input Guardrails

Выполняются в ноде `input_guard` до передачи запроса в LangGraph-агент.

| Проверка | Метод | Результат при срабатывании |
|---|---|---|
| PII в запросе (email, телефон, паспорт, СНИЛС) | regex + NER | HTTP 400, запрос отклонён |
| Prompt injection (`ignore previous instructions`, `you are now`, etc.) | regex patterns | HTTP 400, запрос отклонён |
| Длина запроса > 2000 символов | FastAPI validator (Pydantic) | HTTP 422, ошибка валидации |
| Пустой запрос | FastAPI validator | HTTP 422, ошибка валидации |

```python
# /backend/security/guardrails.py
INJECTION_PATTERNS = [
    r"ignore\s+(previous|all)\s+instructions",
    r"you\s+are\s+now\s+",
    r"act\s+as\s+",
    r"forget\s+your\s+",
    r"system\s*prompt",
    r"reveal\s+.*(prompt|instruction)",
]

PII_PATTERNS = [
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",  # email
    r"\+?[7-8][\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}",  # RU phone
    r"\b\d{4}\s?\d{6}\b",  # паспорт
    r"\b\d{3}-\d{3}-\d{3}\s?\d{2}\b",  # СНИЛС
]

def check_input(query: str) -> tuple[bool, str]:
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, query, re.IGNORECASE):
            return False, "Prompt injection detected"
    for pattern in PII_PATTERNS:
        if re.search(pattern, query):
            return False, "PII detected in query"
    return True, ""
```

### 3.2 Output Guardrails

Выполняются в ноде `output_guard` после генерации ответа LLM, до отдачи пользователю.

| Проверка | Метод | Результат при срабатывании |
|---|---|---|
| PII в ответе | regex + NER (те же паттерны) | PII заменяется на `[REDACTED]` |
| Нежелательный контент | keyword filter | Ответ заменяется на стандартное сообщение |

Output guardrails не блокируют запрос полностью — они редактируют ответ, сохраняя полезную часть.

---

## 4. Audit Logging

**Статус MVP: ✅ реализовано** — `backend/db/audit_store.py` (SQLite WAL, тот же паттерн, что `gap_store.py`).

Каждый вызов `POST /query` записывает одну строку в `audit_log` **независимо от результата** — до возврата ответа пользователю. Запись обёрнута в `try/except` в `routes.py`, поэтому сбой хранилища никогда не нарушает ответ.

**Реальная схема (SQLite, `audit_store.py`):**

```sql
CREATE TABLE IF NOT EXISTS audit_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_role     TEXT    NOT NULL,
    access_level  INTEGER NOT NULL,
    query_hash    TEXT    NOT NULL,   -- SHA-256 hex; plain text не хранится
    result_count  INTEGER,
    quality_score REAL,
    gap_detected  INTEGER DEFAULT 0,
    timestamp     TEXT    NOT NULL    -- ISO UTC
);
CREATE INDEX idx_audit_timestamp ON audit_log (timestamp DESC);
CREATE INDEX idx_audit_role      ON audit_log (user_role);
```

Просмотр записей — `GET /audit-log` (Admin only). Переход на PostgreSQL — Scale-этап.

Audit log используется для:
- расследования инцидентов доступа
- обнаружения аномальных паттернов (массовые запросы одной роли)
- выполнения требований ФЗ-152 к аудируемости каждого обращения к персональным данным

---

## 5. Zero External APIs

Система работает полностью в закрытом контуре (on-premise / air-gapped).

**Запрещено в runtime:**
- обращения к OpenAI, Anthropic, Yandex GPT, любым внешним LLM API
- передача пользовательских запросов или корпоративных документов во внешние сервисы
- загрузка моделей или зависимостей в runtime (только при подготовке окружения)

**Проверяется через:**
- network logs на уровне Docker-сети
- `REQUESTS_CA_BUNDLE=invalid` env для блокировки внешних HTTPS-соединений в runtime
- NFR-03, NFR-06, NFR-07 в `TECHNICAL_SPEC.md`

---

## 6. Модель угроз

Упрощённая threat model для MVP. Полная модель с trust boundaries и STRIDE-анализом — Scale-этап.

| ID | Угроза | Вероятность | Влияние | Механизм митигации |
|---|---|:---:|:---:|---|
| T-01 | **Prompt Injection** — злоумышленник через запрос пытается изменить поведение LLM, получить системный промпт или данные других пользователей | Высокая | Высокое | Input Guardrails: regex-паттерны на `input_guard` ноде. System prompt не передаётся в ответе. |
| T-02 | **RBAC Bypass** — пользователь подменяет заголовок `X-User-Role` для повышения уровня доступа | Высокая (MVP) | Высокое | В MVP: явно задокументированное ограничение, допустимо в контролируемой демо-среде. В Scale: JWT + LDAP/AD — подмена невозможна без private key |
| T-03 | **PII Leakage** — корпоративный документ с персональными данными попадает в ответ LLM | Средняя | Высокое | Input + Output Guardrails: PII-паттерны на входе и выходе. `access_level` ограничивает круг пользователей |
| T-04 | **Data Poisoning** — загрузка вредоносного документа для манипуляции Knowledge Graph | Низкая | Среднее | Валидация при ingestion (формат, объём, обязательные поля). Только `manager`/`admin` могут загружать документы |
| T-05 | **Retrieval Data Leakage** — через косвенные вопросы пользователь выводит содержимое недоступных документов | Средняя | Высокое | Chunk-level RBAC: недоступные чанки не извлекаются из Qdrant/Neo4j физически, не попадают в контекст LLM |
| T-06 | **Model Hallucination** — LLM генерирует уверенный ответ без опоры на источники | Высокая | Среднее | Архитектурный принцип Retrieval before generation: LLM получает контекст только из retrieval. CriticAgent оценивает качество. Knowledge Gap фиксирует неуверенные ответы |

### Границы MVP

Следующие угрозы находятся вне скоупа MVP и адресуются в Scale-этапе:

- **DoS / Rate limiting** — нет ограничения числа запросов в единицу времени
- **Supply chain атаки** — зависимости не проходят автоматический security audit
- **Model extraction** — нет защиты от систематического извлечения весов модели через API
- **Adversarial inputs** — нет защиты от специально сконструированных входных данных для деградации качества

---

## 7. Out of Scope (MVP)

| Механизм | Статус | Этап |
|---|---|---|
| JWT-аутентификация | Заменён на `X-User-Role` header | Scale |
| LDAP / Active Directory интеграция | Не реализована | Scale |
| HTTPS / TLS терминация | Не настроена (только localhost) | Scale |
| Rate limiting | Не реализован | Scale |
| Secrets Manager (Vault) | Заменён на `.env` файл | Scale |
| Автоматический security scan зависимостей | Не реализован | Scale |
| Penetration testing | Не проводился | Scale |

---

## 8. Связанные документы

- `ADD.md` — Security Model, три слоя RBAC (раздел 5)
- `ADR-005-rbac.md` — обоснование выбора chunk-level RBAC
- `docs/data_architecture.md` — схема audit_log, RBAC-фильтры в Qdrant и Neo4j
- `docs/api/openapi.yaml` — HTTP 403 responses, X-User-Role header
- `TECHNICAL_SPEC.md` — FR-21..FR-27 (RBAC и Guardrails), NFR-03, NFR-06, NFR-07
