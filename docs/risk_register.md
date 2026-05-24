# Risk Register — Synapse GraphRAG Knowledge Platform

**Версия:** 1.0  
**Дата:** 17 мая 2026  
**Автор:** Алеся Мороз  
**Статус:** Актуально

> Расширяет раздел 8 `CONCEPT.md`. Формат по шаблону AI Risk Register (семинар 2).
>
> **Risk Score** = Probability × Impact (1–25)
> - 1–6: Low — мониторинг
> - 7–12: Medium — план митигации
> - 13–19: High — активные меры
> - 20–25: Critical — немедленные действия

---

## Технические риски

| ID | Описание риска | P (1–5) | I (1–5) | Score | Стратегия | Mitigation Plan | Триггер |
|---|---|:---:|:---:|:---:|---|---|---|
| R-T01 | **Низкое качество извлечения сущностей (NER)** — LLM извлекает неправильные типы сущностей или пропускает ключевые, граф остаётся разреженным | 3 | 5 | **15 (High)** | Mitigate | Few-shot промпты с 3 примерами в `entity_extraction.txt`; валидация графа после каждого ingestion: `MATCH (n) RETURN count(n)` ≥ 50; переход на более точные промпты при провале AC-04 | Граф < 50 узлов после загрузки всего корпуса |
| R-T02 | **OOM на T4 16 GB при высоком context length** — vLLM исчерпывает VRAM при длинных запросах или большом KV-cache | 4 | 4 | **16 (High)** | Mitigate | `--max-model-len 8192` в vLLM; fp8 KV-cache; мониторинг VRAM через nvidia-smi exporter; fallback на RTX 4090 для демо | `nvidia-smi` показывает VRAM > 90%; OOM в логах vLLM |
| R-T03 | **E2E latency > 10 сек на GPU** — pipeline слишком долгий, NFR-01 не выполняется | 3 | 4 | **12 (Medium)** | Mitigate | Параллельный retrieval (Send() API в LangGraph) уже реализован; профилирование через Langfuse spans — найти bottleneck; уменьшить top-k с 10 до 5 чанков; ограничить max_tokens | P95 latency > 10 сек на GPU Dev в нагрузочном тесте |
| R-T04 | **Retrieval latency Neo4j > 300 мс** — граф traversal замедляет pipeline | 2 | 3 | **6 (Low)** | Monitor | Индексы на `access_level` и `doc_id`; ограничение depth traversal до 2–3 хопов; query profiling через `PROFILE` в Cypher | Retrieval P95 > 300 мс в нагрузочном тесте |
| R-T05 | **Расхождение поведения Ollama vs vLLM** — тесты на local-lite проходят, на GPU dev падают из-за разных моделей | 4 | 3 | **12 (Medium)** | Mitigate | Критические тесты (RBAC, golden dataset eval) только на vLLM; Ollama — только для unit-тестов и frontend; явно задокументировано в Model Card | Тест проходит на Ollama, падает на vLLM |
| R-T06 | **Vision-модель конкурирует за VRAM с основной LLM** — OOM при одновременной работе | 3 | 4 | **12 (Medium)** | Avoid | Временное разделение через Docker Compose профили (`ingest` vs `gpu`); vision запускается только при ingestion, не в inference runtime | OOM в логах при запуске обоих профилей одновременно |

---

## AI / ML риски

| ID | Описание риска | P (1–5) | I (1–5) | Score | Стратегия | Mitigation Plan | Триггер |
|---|---|:---:|:---:|:---:|---|---|---|
| R-AI01 | **Галлюцинации в ответе** — LLM генерирует факты которых нет в источниках, Faithfulness < 0.9 | 4 | 4 | **16 (High)** | Mitigate | Принцип Retrieval before generation; CriticAgent проверяет Faithfulness (LLM-as-a-Judge); Self-Reflection retry до 3 раз; Knowledge Gap при score < 2 | Faithfulness < 0.9 на golden dataset eval |
| R-AI02 | **GraphRAG не превосходит vector-only RAG** — центральная гипотеза PoC не подтверждается | 3 | 5 | **15 (High)** | Mitigate | Тест alpha=1.0 vs alpha=0.7/0.3 на golden dataset; при отсутствии прироста — увеличить долю графа (alpha=0.5/0.5); проверить качество извлечения сущностей (может быть причиной) | GraphRAG ≤ vector-only по всем трём метрикам на poc_comparison |
| R-AI03 | **Деградация качества при малом корпусе** — 15 документов недостаточно для связного графа | 3 | 4 | **12 (Medium)** | Mitigate | Минимум 15 документов с равномерным покрытием всех 5 уровней доступа; проверка AC-04 (> 50 узлов, > 100 рёбер) до финального eval | Граф разреженный, Context Recall < 0.8 |
| R-AI04 | **Ошибки нормализации онтологии** — разные варианты написания одного термина создают дубли в Neo4j | 3 | 3 | **9 (Medium)** | Mitigate | Fuzzy match порог 0.85 в entity extractor; проверка AC-13 после ingestion: `MATCH (n) WHERE n.canonical_name IS NOT NULL RETURN n.canonical_name, count(*)`; пополнение aliases в `ontology.json` | Дубли по canonical_name в Neo4j |
| R-AI05 | **Неправильный confidence_score** — формула `1 - age_days/365` даёт некорректные значения из-за неправильных `last_updated` в манифесте | 3 | 2 | **6 (Low)** | Monitor | Проверить `last_updated` во всех 15 документах корпуса перед ingestion; тест AC-12 с документом old_date | confidence_score = 0 или > 1 в ответе |

---

## Security риски

| ID | Описание риска | P (1–5) | I (1–5) | Score | Стратегия | Mitigation Plan | Триггер |
|---|---|:---:|:---:|:---:|---|---|---|
| R-S01 | **Prompt Injection** — злоумышленник через запрос изменяет поведение LLM или получает системный промпт | 4 | 4 | **16 (High)** | Mitigate | Input Guardrails: regex-паттерны на `input_guard` ноде; системный промпт не цитируется в ответе; тест R-S01 в golden dataset (q-030); Injection Block Rate = 100% | Injection-запрос из golden dataset не заблокирован |
| R-S02 | **RBAC Bypass** — подмена заголовка `X-User-Role` для повышения уровня доступа | 5 | 5 | **25 (Critical)** | Accept (MVP scope) | В MVP явно задокументированное ограничение — X-User-Role без JWT. Допустимо в контролируемой демо-среде. В Scale — JWT + LDAP/AD. Тест RBAC в golden dataset (q-027..q-029); RBAC Leakage Rate = 0% | Источник с access_level > user_level появился в ответе |
| R-S03 | **PII Leakage** — персональные данные из документа попадают в ответ или логи | 2 | 4 | **8 (Medium)** | Mitigate | Input + Output Guardrails: PII regex-паттерны; корпус не содержит реальных PII (corpus/README.md); PII Filtering Rate = 100% в eval | PII-паттерн найден в ответе или в audit_log |
| R-S04 | **Data Poisoning** — загрузка вредоносного документа для манипуляции Knowledge Graph | 1 | 4 | **4 (Low)** | Accept | Только manager/admin могут загружать документы; валидация формата и объёма при ingestion; audit_log фиксирует все операции загрузки | Аномальные узлы или рёбра в графе после ingestion |

---

## Delivery риски

| ID | Описание риска | P (1–5) | I (1–5) | Score | Стратегия | Mitigation Plan | Триггер |
|---|---|:---:|:---:|:---:|---|---|---|
| R-D01 | **Нехватка времени на реализацию** — MVP не готов к дате защиты | 4 | 5 | **20 (Critical)** | Mitigate | WBS с фиксированными сроками; критический путь: golden_dataset → eval → код → документация; Блоки 12 (Production Readiness) и 9 (Roadmap) намеренно исключены из scope | До защиты осталось < 5 дней, а golden dataset не готов |
| R-D02 | **Расхождение кода и документации** — диаграммы описывают архитектуру которой нет в коде | 4 | 4 | **16 (High)** | Mitigate | Принцип: сначала диаграмма, потом код; компоненты без реализации помечены как `planned` в README; ADR фиксируют решения до реализации | Комиссия находит компонент в диаграмме которого нет в репо |
| R-D03 | **Golden Dataset не готов к eval** — вопросы написаны не по реальному корпусу | 4 | 5 | **20 (Critical)** | Mitigate | `positive` вопросы составляются после ingestion корпуса; `negative`, `rbac`, `injection` — уже готовы и не зависят от корпуса; 30 вопросов в шаблоне | eval запущен, но Context Recall = 0 из-за неправильных expected_sources |
| R-D04 | **Демо разваливается на живой защите** — технический сбой во время показа | 3 | 5 | **15 (High)** | Mitigate | Demo Script зафиксирован в `demo_script.md`; чеклист перед записью видео; видео-демо записано заранее (AC-10 = видео, не live) | Система не отвечает во время демо |
| R-D05 | **Нагрузочный тест не проводился** — AC-09 не закрыт | 3 | 4 | **12 (Medium)** | Mitigate | Plan валидации в `capacity_planning.md`; три сценария Locust; запустить тест за 3–5 дней до защиты; результаты → `docs/load_test_report.md` | AC-09 не закрыт за 3 дня до защиты |

---

## Сводная таблица по приоритетам

| Score | ID | Риск (кратко) | Владелец |
|:---:|---|---|---|
| **25** | R-S02 | RBAC Bypass (X-User-Role без JWT) | Архитектор |
| **20** | R-D01 | Нехватка времени на реализацию | Архитектор |
| **20** | R-D03 | Golden Dataset не по реальному корпусу | Архитектор |
| **16** | R-T02 | OOM на T4 16 GB | Инфраструктура |
| **16** | R-T03 | E2E latency > 10 сек (если) | Разработчик |
| **16** | R-AI01 | Галлюцинации, Faithfulness < 0.9 | AI/ML |
| **16** | R-S01 | Prompt Injection | Разработчик |
| **16** | R-D02 | Расхождение кода и документации | Архитектор |
| **15** | R-T01 | Низкое качество NER, граф разреженный | AI/ML |
| **15** | R-AI02 | GraphRAG не превосходит vector-only | AI/ML |
| **15** | R-D04 | Демо разваливается на защите | Архитектор |

---

## Связанные документы

- `CONCEPT.md` — раздел 8 (исходная таблица рисков)
- `docs/security_architecture.md` — детали митигации R-S01, R-S02, R-S03
- `docs/evaluation_plan.md` — метрики для контроля R-AI01, R-AI02
- `docs/model_card.md` — R-T02, R-T05, R-T06
- `docs/capacity_planning.md` — R-T02, R-T03, R-T04
- `docs/demo_script.md` — R-D04
