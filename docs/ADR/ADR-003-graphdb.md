# ADR-003: Graph Database — Neo4j

**Статус:** Принято  
**Дата:** 11 мая 2026  
**Автор:** Алеся Мороз

---

## Контекст

Synapse строит Knowledge Graph из корпоративных документов — фиксирует сущности (роли, процессы, системы, политики) и связи между ними. Граф используется для graph traversal при гибридном поиске и визуализации в Explorer режиме. Ключевые требования:

- Язык запросов для traversal с RBAC фильтрацией
- Визуализация графа для демо (Neo4j Browser)
- Python driver
- Self-hosted, Docker
- Поддержка property graph модели (свойства на узлах и рёбрах)

---

## Решение

**Neo4j 5.18 Community Edition** — развёртывание через `neo4j:5.18-community`.

**Схема узлов:**
```cypher
(:Document {id, title, doc_type, access_level, last_updated})
(:Section {id, title, content_summary, access_level, doc_id})
(:Role {id, name, access_level})
(:Process {id, name, description, access_level})
(:System {id, name, canonical_name, description})
(:Policy {id, name, description, access_level})
```

**Типы рёбер:**
`HAS_SECTION`, `GOVERNED_BY`, `REFERENCES`, `REQUIRES`, `USES`, `APPLIES_TO`, `DEPENDS_ON`

**RBAC traversal:**
```cypher
MATCH (d:Document)-[:HAS_SECTION]->(s:Section)
WHERE d.access_level <= $user_level
AND s.access_level <= $user_level
RETURN d, s LIMIT 10
```

---

## Альтернативы рассмотрены

| Вариант | Плюсы | Минусы | Решение |
|---|---|---|---|
| **ArangoDB** | Multi-model (граф + документы + key-value), единая БД | Меньше экосистема, слабее визуализация для демо, меньше LangChain интеграций | **Отклонён** |
| **FalkorDB** | Высокая производительность (Redis-based), Redis-совместимый API | Новый проект (2023), мало production кейсов, высокий риск для MVP | **Отклонён** |
| **Nebula Graph** | Масштабируется на большие графы, распределённая архитектура | Сложнее развёртывание (несколько компонентов), меньше документации на русском | **Отклонён** |
| **Amazon Neptune** | Managed сервис, не требует администрирования | Облачный сервис — нарушает требование on-premise и ФЗ-152 | **Отклонён** (блокер по безопасности) |
| **TigerGraph** | Высокая производительность на аналитических запросах | Enterprise лицензия, избыточен для MVP | **Отклонён** |
| **NetworkX (Python)** | Нет отдельного сервиса, простой Python API | In-memory граф — нет персистентности, нет Cypher, нет визуализации | **Отклонён** |

---

## Trade-offs

**Плюсы Neo4j:**
- Cypher — выразительный язык запросов, RBAC фильтры на уровне traversal
- Neo4j Browser — встроенная визуализация графа для демо (порт 7474)
- Богатая экосистема: LangChain Neo4j интеграция из коробки
- property graph модель — свойства на узлах и рёбрах
- APOC библиотека для сложных операций с графом
- Хорошая документация, активное community

**Минусы Neo4j:**
- Community Edition без кластеризации и enterprise функций
- Выше потребление RAM при больших графах (компенсируется объёмом MVP корпуса)
- Лицензия Community не включает backup инструменты (достаточно volume snapshot для MVP)

---

## Последствия

- Граф инициализируется при первом ingestion
- Ontology-driven extraction: сущности сопоставляются с `ontology.json` перед записью в Neo4j
- Explorer режим (`GET /graph`) читает узлы и рёбра из Neo4j для Admin роли
- Целевые метрики: >50 узлов, >100 рёбер после загрузки корпуса (AC-04)
- В Scale-этапе: Neo4j Enterprise или переход на FalkorDB при необходимости производительности

---

## Compliance & Ethics

**Регуляторное соответствие:**
- Neo4j Community Edition развёртывается self-hosted — данные корпоративного Knowledge Graph не покидают периметр, требования **ФЗ-152** соблюдены
- Лицензия **GPL v3** (Community Edition) допускает использование в закрытом корпоративном развёртывании без обязательства открывать исходный код собственной системы
- Телеметрия Neo4j отключена в `neo4j.conf` (`dbms.usage_report.enabled=false`) для исключения любых внешних обращений (NFR-03)

**Этические риски и меры снижения:**
- Риск утечки закрытых знаний через Explorer режим: пользователь с ролью Admin видит весь граф. Мера: Explorer доступен только при `access_level=5` (FR-09), каждый запрос к `GET /graph` логируется в audit log
- Риск раскрытия структуры документов через метаданные узлов даже при ограниченном доступе к содержимому. Мера: RBAC фильтр применяется на уровне traversal (WHERE n.access_level <= $user_level), а не постфильтрацией результатов
