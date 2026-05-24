# PoC Comparison: GraphRAG vs Vector-only Retrieval

**Версия:** 1.0  
**Дата:** 21 мая 2026  
**Статус:** Данные mock-режима; финальные данные — после запуска с GPU-профилем

---

## Гипотеза

**H1:** Гибридный поиск GraphRAG (0.7 × vector + 0.3 × graph) даёт качество ответов выше, чем vector-only RAG на том же корпусе.

---

## Методология

**Инструмент:** `scripts/eval_comparison.py`  
**Датасет:** 20 positive-вопросов из `docs/evaluation/golden_dataset.jsonl`  
**Метрика качества:** `quality_score` от CriticAgent (шкала 1–5, LLM-as-a-Judge)  
**Метрика точности:** Source hit rate (наличие ожидаемого doc_id в returned sources)

### Условия запуска

| Режим | LLM | Embeddings | Storage | Описание |
|-------|-----|-----------|---------|----------|
| **local-lite** | mock | mock | mock | Детерминированные stub-ответы, без GPU |
| **gpu-demo** | vLLM (Qwen2.5-14B-AWQ) | nomic-embed-text | Qdrant + Neo4j | Полный стек, RTX 4090 |

---

## Результаты: local-lite (mock mode)

В mock-режиме оба пути retrieval возвращают пустой список источников, поэтому сравнение не репрезентативно.

| Метрика | GraphRAG | Vector-only | Delta |
|---------|:--------:|:-----------:|:-----:|
| Avg quality_score | 1.0 | 1.0 | +0.00 |
| Source hit rate | 0/20 (0%) | 0/20 (0%) | 0 |

**Интерпретация:** mock-ретриверы намеренно возвращают пустые списки для изоляции тестов остальных компонентов (агент, маршрутизатор, RBAC-guard). Качество ответов низкое (1.0) из-за отсутствия контекста, что корректно вызывает knowledge gap detection (6/6 negative-случаев заблокированы).

---

## Ожидаемые результаты: gpu-demo (полный стек)

На основе архитектурного анализа и теоретических обоснований:

| Метрика | GraphRAG | Vector-only | Ожидаемый Delta |
|---------|:--------:|:-----------:|:---------------:|
| Avg quality_score | ~3.8–4.2 | ~3.2–3.6 | +0.4 – +0.8 |
| Source hit rate | ~70–80% | ~55–65% | +10–15% |

### Почему GraphRAG превосходит Vector-only

**Scenario A — вопросы с перекрёстными ссылками:**  
Вопрос: "Как получить расширенный доступ?" требует и POL-SEC-001 (политика), и INS-HR-001 (процедура). Vector search находит один из документов, Neo4j traversal по связям `REFERS_TO` находит оба.

**Scenario B — синонимы и аббревиатуры:**  
Вопрос про "MR" → vector находит чанки с "Merge Request", граф через онтологический узел GitLab также находит чанки STD-ENG-001 и STD-ENG-002.

**Scenario C — иерархические запросы:**  
Вопрос про "архитектурные требования senior" → граф traversal по `REQUIRES_ROLE` связям сразу исключает документы уровня < 3, снижая шум в контексте LLM.

---

## Порядок запуска финального сравнения

```bash
# 1. Запуск полного стека
cd infra
docker compose --profile gpu --profile observability up -d

# 2. Ожидание готовности (vLLM ~2 мин на загрузку модели)
docker compose ps  # all services healthy

# 3. Индексация корпуса
curl -X POST http://localhost:8000/ingest \
  -H "X-User-Role: admin" \
  -H "Content-Type: application/json"

# 4. Запуск сравнения
python scripts/eval_comparison.py --url http://localhost:8000
```

---

## Метрики системы при запуске GPU-стека

Grafana dashboard (http://localhost:3001):
- `synapse_request_latency_seconds` — P95 target < 5s
- `synapse_tokens_per_second` — Qwen2.5-14B-AWQ target > 20 tok/s на RTX 4090
- `synapse_knowledge_gap_total` — счётчик невалидных запросов

Langfuse traces (http://localhost:3000):
- Breakdown по нодам: vector_retriever, graph_retriever, generator, critic
- Bottleneck identification: обычно generator (LLM inference) занимает 80% времени

---

## Acceptance Criteria

| AC | Описание | Threshold | Статус |
|----|----------|-----------|--------|
| AC-02 | Answer quality (positive cases) | quality_score > 3.0 avg | Ожидает GPU |
| AC-03 | RBAC isolation | 0% leakage | ✅ PASS (mock) |
| AC-11 | Knowledge gap detection | 100% на negative cases | ✅ PASS (mock) |
| AC-12 | Guardrails | 100% injection blocked | ✅ PASS (mock) |
