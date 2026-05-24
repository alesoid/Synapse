# Model Card — Synapse GraphRAG Knowledge Platform

**Версия:** 1.0  
**Дата:** 17 мая 2026  
**Автор:** Алеся Мороз  
**Статус:** Утверждено

---

## Обзор моделей

Synapse использует три модели, каждая для своей задачи:

| Роль | Модель | Среда | Runtime |
|---|---|---|---|
| LLM inference (основной) | Qwen2.5-14B-Instruct-AWQ | GPU Dev / Demo / Prod-like | vLLM 0.6.x |
| LLM inference (fallback) | Qwen2.5-7B-Q4 | Local Lite (Mac) | Ollama |
| Vision / Document OCR (опц.) | Qwen2.5-VL-7B-Instruct | Ingestion profile | vLLM (порт 8002) |
| Embeddings | nomic-embed-text | Все среды | embedding adapter |

---

## 1. Qwen2.5-14B-Instruct-AWQ

**Назначение:** основной LLM для генерации ответов (GeneratorAgent), оценки качества (CriticAgent) и извлечения сущностей при ingestion.

### Параметры модели

| Параметр | Значение |
|---|---|
| Полное название | `Qwen/Qwen2.5-14B-Instruct-AWQ` |
| Разработчик | Alibaba Cloud (Qwen Team) |
| Семейство | Qwen2.5 |
| Число параметров | 14.7B |
| Тип квантования | AWQ (Activation-aware Weight Quantization) |
| Размер весов | ~8–9 GB |
| Контекстное окно | 128K токенов (используется до 8K в MVP для экономии VRAM) |
| Поддерживаемые языки | Русский, Английский, Китайский и ещё 29 языков |
| Лицензия | Apache 2.0 — коммерческое использование без ограничений |
| HuggingFace | `https://huggingface.co/Qwen/Qwen2.5-14B-Instruct-AWQ` |

### Hardware requirements

| Ресурс | Минимум (T4) | Комфортно (RTX 4090) |
|---|---|---|
| VRAM | 16 GB (впритык) | 24 GB (с запасом) |
| VRAM под веса | ~8–9 GB | ~8–9 GB |
| VRAM под KV-cache | ~4–6 GB | ~6–8 GB |
| RAM (системная) | 16 GB | 32 GB+ |
| GPU | NVIDIA T4 16 GB | NVIDIA RTX 4090 24 GB |

### Конфигурация запуска (vLLM)

```bash
python -m vllm.entrypoints.openai.api_server \
  --model Qwen/Qwen2.5-14B-Instruct-AWQ \
  --quantization awq \
  --kv-cache-dtype fp8 \
  --max-model-len 8192 \
  --port 8001
```

### Производительность (ориентировочно)

| Метрика | T4 16 GB | RTX 4090 24 GB |
|---|---|---|
| Throughput | ~15–25 tok/s | ~40–60 tok/s |
| E2E latency P95 (200 токенов) | ~8–10 сек | ~4–6 сек |
| TTFT | ~2–3 сек | ~1–2 сек |

---

## 2. Qwen2.5-7B-Q4 (Local Lite fallback)

**Назначение:** lightweight fallback для разработки на Mac без GPU — unit-тесты, frontend-разработка, отладка без полного LLM stack. Критические сценарии всегда проверяются на GPU Dev с vLLM.

### Параметры модели

| Параметр | Значение |
|---|---|
| Полное название | `Qwen/Qwen2.5-7B-Instruct` (Q4_K_M квантование через Ollama) |
| Разработчик | Alibaba Cloud (Qwen Team) |
| Число параметров | 7.6B |
| Тип квантования | Q4_K_M (через Ollama GGUF) |
| Размер весов | ~5 GB |
| Контекстное окно | 32K токенов |
| Лицензия | Apache 2.0 |

### Hardware requirements

| Ресурс | Значение |
|---|---|
| RAM | 8 GB (минимум), 16 GB рекомендуется |
| GPU | не требуется (CPU inference) |
| Целевая платформа | Apple Silicon (M1/M2/M3), Intel Mac |

### Конфигурация запуска (Ollama)

```bash
ollama pull qwen2.5:7b
ollama serve
# Модель доступна на http://localhost:11434
```

### Ограничения по сравнению с prod

- Ниже качество ответов из-за меньшего числа параметров
- Медленнее inference (CPU vs GPU)
- Поведение может отличаться от prod — не используется для финального eval
- Не подходит для нагрузочного тестирования

---

## 3. Qwen2.5-VL-7B-Instruct (Vision, опционально)

**Назначение:** описание чертежей, схем и сканированных страниц при ingestion документов. Активируется только при `VISION_ENABLED=true` в профиле `ingest`.

### Параметры модели

| Параметр | Значение |
|---|---|
| Полное название | `Qwen/Qwen2.5-VL-7B-Instruct` |
| Разработчик | Alibaba Cloud (Qwen Team) |
| Число параметров | 7.6B |
| Тип | Multimodal LLM (текст + изображения) |
| Размер весов | ~15 GB (fp16) |
| Лицензия | Apache 2.0 |

### Особенности использования в Synapse

Модель активируется **только при ingestion**, не при обработке запросов пользователей. Это исключает конкуренцию за VRAM с основной моделью Qwen2.5-14B-AWQ. На T4 16 GB обе модели одновременно не помещаются — используется временное разделение через Docker Compose профили.

```bash
# Профиль ingestion — основная модель выгружается, vision загружается
docker compose --profile ingest up vllm-vision

# Профиль inference (обычная работа)
docker compose --profile gpu up vllm-main
```

---

## 4. nomic-embed-text

**Назначение:** векторизация чанков документов при ingestion и векторизация пользовательских запросов при retrieval.

### Параметры модели

| Параметр | Значение |
|---|---|
| Полное название | `nomic-ai/nomic-embed-text-v1.5` |
| Разработчик | Nomic AI |
| Размерность векторов | 768 |
| Метрика расстояния | Cosine Similarity |
| Максимальная длина входа | 8192 токенов |
| Поддерживаемые языки | Русский, Английский + другие |
| Размер модели | ~274 MB |
| Лицензия | Apache 2.0 |

### Производительность

| Метрика | Значение |
|---|---|
| Скорость (CPU) | ~200–500 чанков/мин |
| Скорость (GPU) | ~2000–5000 чанков/мин |
| Latency одного запроса | < 50 мс (CPU), < 10 мс (GPU) |

### Конфигурация

```python
# /backend/embeddings/adapter.py
from langchain_community.embeddings import OllamaEmbeddings

embeddings = OllamaEmbeddings(
    model="nomic-embed-text",
    base_url=os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
)
# Размерность проверяется при создании коллекции Qdrant: size=768
```

Реализация через embedding adapter — замена модели не требует изменений в бизнес-логике агента.

---

## 5. Поддерживаемые языки

| Язык | LLM (14B) | Embeddings | Статус |
|---|:---:|:---:|---|
| Русский | ✅ | ✅ | Основной язык корпуса |
| Английский | ✅ | ✅ | Технические термины, код |
| Смешанный (RU+EN) | ✅ | ✅ | Типично для ADR и технических документов |

---

## 6. Известные ограничения

| Ограничение | Описание | Механизм снижения |
|---|---|---|
| **Галлюцинации** | LLM может генерировать факты, которых нет в источниках | Принцип Retrieval before generation; CriticAgent проверяет Faithfulness; confidence_score < 0.5 → предупреждение |
| **Контекстное окно** | В MVP используется до 8K токенов из 128K (VRAM) | Chunking 500 токенов + overlap 50; top-10 чанков → ~5K токенов контекста |
| **Языковой bias** | Модель может предпочитать английский при смешанном контексте | System prompt явно требует отвечать на языке вопроса |
| **Деградация на длинных документах** | Качество extraction падает на документах > 50 страниц | Иерархический chunking по разделам H1/H2 |
| **T4 16 GB — минимальный порог** | При росте concurrency или длины контекста VRAM может не хватить | fp8 KV-cache; max-model-len=8192; monitoring VRAM через nvidia-smi exporter |
| **Холодный старт vLLM** | Загрузка модели ~2–3 минуты после docker compose up | Добавлен healthcheck; FastAPI запускается после vLLM ready |

---

## 7. Условия использования

| Требование | Статус |
|---|---|
| Только локальное развёртывание (on-premise) | ✅ Обязательно — Zero external APIs |
| Запрещена передача данных во внешние API | ✅ Обязательно — NFR-03, ФЗ-152 |
| Все модели open source | ✅ Apache 2.0 — коммерческое использование без ограничений |
| Версии моделей пинированы | ✅ NFR-08 — воспроизводимость |
| Название модели не раскрывается пользователям | ✅ Защита от модель-специфичных атак |

---

## 8. Риски и митигация

| Риск | Вероятность | Влияние | Митигация |
|---|:---:|:---:|---|
| Галлюцинации в ответе | Средняя | Высокое | CriticAgent (LLM-as-a-Judge), Self-Reflection retry, Faithfulness > 0.9 |
| Утечка системного промпта | Низкая | Среднее | Input Guardrails блокируют injection-паттерны; System prompt не цитируется в ответе |
| OOM на T4 при высоком concurrency | Средняя | Высокое | max-model-len=8192, fp8 KV-cache, мониторинг VRAM, очередь запросов |
| Расхождение качества local-lite vs prod | Высокая | Среднее | Критические тесты только на vLLM; golden dataset eval только на GPU Dev |
| Устаревание модели | Низкая | Низкое | Модульная архитектура — замена модели через env var без изменения логики |

---

## 9. Связанные документы

- `ADR-001-llm-serving.md` — обоснование выбора vLLM и Qwen2.5
- `ADR-006-embeddings.md` — обоснование выбора nomic-embed-text
- `ADR-013-multimodal.md` — Vision pipeline, Qwen2.5-VL
- `docs/capacity_planning.md` — VRAM и RAM sizing для всех профилей
- `docs/prompt_library.md` — промпты для каждого LLM-вызова
- `docs/evaluation_plan.md` — метрики качества моделей
