# Load Test Report — Synapse GraphRAG API

**Версия:** 1.0  
**Дата:** 21 мая 2026  
**Инструмент:** `scripts/load_test.py`  
**Профиль:** local-lite (mock backends, Mac M3)

---

## Конфигурация теста

| Параметр | Значение |
|----------|----------|
| Concurrency | 5 воркеров |
| Duration | 15 секунд |
| Queries | 8 вариантов × 5 ролей (циклически) |
| Backend | FastAPI + LangGraph (mock) |
| Host | localhost:8004 |

---

## Результаты

| Метрика | Значение | Acceptance Threshold | Статус |
|---------|----------|---------------------|--------|
| **P50 (median)** | 23 ms | < 2000 ms | ✅ PASS |
| **P95** | 32 ms | < 5000 ms | ✅ PASS |
| **P99** | 44 ms | — | — |
| **Avg** | ~25 ms | — | — |
| **RPS** | 207.6 | ≥ 1.0 | ✅ PASS |
| **Error rate** | 0.0% | < 1% | ✅ PASS |
| **Total requests** | 3 116 за 15 с | — | — |

---

## Интерпретация

**mock-режим** демонстрирует latency на уровне FastAPI + LangGraph overhead без I/O. P95=32 ms — это минимальная стоимость одного запроса через граф из 9 нод (input_guard → vector → graph → merge → generator → confidence → critic → (retry ×3) → knowledge_gap → END).

**gpu-demo режим** добавит:
- vLLM inference: +1 000–3 000 ms (Qwen2.5-14B-AWQ, 512 токенов ответа, RTX 4090 ~20 tok/s)
- Qdrant search: +5–15 ms (HNSW index, cosine similarity)
- Neo4j traversal: +10–30 ms (2-hop query с access_level фильтром)

**Ожидаемый P95 на GPU-стеке:** 2 000–4 000 ms (в пределах AC-09: P95 < 5 s).

---

## Acceptance Criteria AC-09

> API /query отвечает за P95 < 5 секунд при нагрузке 10 RPS.

Для верификации AC-09 на GPU-стеке:

```bash
python scripts/load_test.py \
  --url http://localhost:8000 \
  --concurrency 10 \
  --duration 60
```

---

## Команды для воспроизведения

```bash
# local-lite (mock, любая машина)
uvicorn backend.api.main:app --port 8000 &
python scripts/load_test.py --url http://localhost:8000 --concurrency 5 --duration 30

# gpu-demo (RTX 4090)
docker compose --profile gpu up -d
python scripts/load_test.py --url http://localhost:8000 --concurrency 10 --duration 60
```

Отчёт сохраняется в `docs/evaluation/results/load_test_<timestamp>.md`.
