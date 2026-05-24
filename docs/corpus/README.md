# Тестовый корпус Synapse

**Версия:** 1.0  
**Дата:** 17 мая 2026  
**Статус:** Готов к ingestion

---

## Назначение

Корпус используется для:
- Ingestion и построения Knowledge Graph (Neo4j + Qdrant)
- Оценки качества на `docs/evaluation/golden_dataset.jsonl`
- Демонстрации системы на защите диплома

Корпус предназначен для **demo/evaluation**, не для production.

---

## Состав корпуса

**Итого:** 15 документов, все в формате Markdown.

| doc_id | Файл | Access Level | Doc Type | Отдел | Название |
|---|---|:---:|---|---|---|
| INS-HR-001 | INS-HR-001_onboarding.md | 1 | instruction | HR | Инструкция по адаптации новых сотрудников |
| INS-HR-002 | INS-HR-002_corporate_tools.md | 1 | instruction | IT | Правила работы с корпоративными инструментами |
| POL-HR-001 | POL-HR-001_code_of_conduct.md | 1 | policy | HR | Кодекс поведения сотрудника |
| STD-ENG-001 | STD-ENG-001_code_review.md | 2 | standard | Engineering | Стандарт код-ревью |
| STD-ENG-002 | STD-ENG-002_git_workflow.md | 2 | standard | Engineering | Руководство по Git-workflow |
| STD-ENG-003 | STD-ENG-003_tech_docs.md | 2 | standard | Engineering | Стандарт написания технической документации |
| STD-ARCH-001 | STD-ARCH-001_microservices.md | 3 | standard | Architecture | Архитектурный стандарт микросервисов |
| STD-ARCH-002 | STD-ARCH-002_production.md | 3 | standard | Engineering | Регламент работы с продакшн-системами |
| POL-ARCH-001 | POL-ARCH-001_tech_debt.md | 3 | policy | Architecture | Политика управления техническим долгом |
| POL-SEC-001 | POL-SEC-001_access_policy.md | 4 | policy | IT | Политика согласования доступов к системам |
| POL-SEC-002 | POL-SEC-002_grades.md | 4 | policy | HR | HR-политика грейдов и повышений |
| POL-MGR-001 | POL-MGR-001_budgeting.md | 4 | policy | Finance | Регламент бюджетирования IT-проектов |
| POL-SEC-003 | POL-SEC-003_access_audit.md | 5 | policy | IT | Политика аудита и контроля доступов |
| POL-SEC-004 | POL-SEC-004_access_matrix.md | 5 | matrix | IT | Матрица доступов к системам |
| POL-SEC-005 | POL-SEC-005_incidents.md | 5 | policy | IT | Регламент управления инцидентами ИБ |

---

## Распределение по уровням доступа

| Access Level | Роль | Кол-во документов | Документы |
|---|---|:---:|---|
| 1 | junior | 3 | INS-HR-001, INS-HR-002, POL-HR-001 |
| 2 | middle | 3 | STD-ENG-001, STD-ENG-002, STD-ENG-003 |
| 3 | senior | 3 | STD-ARCH-001, STD-ARCH-002, POL-ARCH-001 |
| 4 | manager | 3 | POL-SEC-001, POL-SEC-002, POL-MGR-001 |
| 5 | admin | 3 | POL-SEC-003, POL-SEC-004, POL-SEC-005 |

Равномерное распределение — по 3 документа на каждый уровень — обеспечивает
полноценное тестирование RBAC-изоляции (AC-03) для всех 5 ролей.

---

## Синтетичность данных

Документы синтетические — созданы специально для целей демо и оценки системы.
Отражают типичную структуру корпоративных регламентов IT-компании.
Реальных персональных данных нет.

---

## Ограничения корпуса

- Только текстовые документы в формате Markdown
- Язык: русский (основной), отдельные технические термины на английском
- Сканы и чертежи отсутствуют (`VISION_ENABLED` не требуется)
- Объём: 15 документов (~150–300 страниц суммарно)
- Назначение: demo/evaluation — не отражает реальный production-корпус

---

## PII Policy

Корпус не содержит реальных персональных данных:
- Все имена сотрудников — синтетические
- Телефоны, email, паспортные данные — отсутствуют
- Финансовые данные — синтетические

---

## Загрузка корпуса

```bash
# Убедиться что система запущена
curl http://localhost:8000/health

# Загрузить все документы корпуса
python scripts/ingest_corpus.py --corpus docs/corpus/

# Проверить результат в Neo4j Browser (http://localhost:7474)
MATCH (n) RETURN count(n)        -- ожидается > 50 узлов
MATCH ()-[r]->() RETURN count(r) -- ожидается > 100 рёбер

# Проверить коллекцию в Qdrant UI (http://localhost:6333/dashboard)
# Коллекция: chunks — ожидается > 200 точек
```

Скрипт `ingest_corpus.py` последовательно вызывает `POST /ingest` для каждого
документа из `corpus_manifest.json`.

---

## corpus_manifest.json

Метаданные всех документов корпуса — источник истины для ingestion и evaluation.
`doc_id` из манифеста соответствует `expected_sources` в `golden_dataset.jsonl`.

```json
[
  {
    "doc_id": "INS-HR-001",
    "filename": "INS-HR-001_onboarding.md",
    "doc_type": "instruction",
    "access_level": 1,
    "last_updated": "2025-10-01"
  },
  ...
]
```

Полный манифест: `docs/corpus/corpus_manifest.json`

---

## Связанные документы

- `docs/evaluation/golden_dataset.jsonl` — тестовые вопросы по этому корпусу
- `docs/data_architecture.md` — metadata contract
- `docs/evaluation_plan.md` — как корпус используется в evaluation
