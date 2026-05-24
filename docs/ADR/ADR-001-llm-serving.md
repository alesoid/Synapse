# ADR-001: LLM Serving — vLLM + Qwen2.5-14B-AWQ

**Статус:** Принято  
**Дата:** 11 мая 2026  
**Автор:** Алеся Мороз

---

## Scope

| Этап | Dev-среда | Prod-среда | Статус |
|---|---|---|---|
| **MVP** | GPU Dev: vLLM + Qwen2.5-14B-AWQ на VM 64 GB RAM + RTX 4090; Local Lite: mock/Ollama fallback на Mac 8 GB | vLLM + Qwen2.5-14B-AWQ на GPU-сервере | ✅ Текущее решение |
| **Scale** | vLLM/SGLang с более крупной моделью при наличии GPU pool | vLLM + Qwen3-30B или SGLang, tensor parallelism на мульти-GPU | 🔜 Вне скоупа MVP |

> **Почему vLLM в GPU Dev:**  
> Полный стек Synapse требует LLM serving, Qdrant, Neo4j, PostgreSQL и observability. Mac 8 GB не является целевой средой такого запуска. Основная разработка полного MVP выполняется на GPU Dev VM с RTX 4090, поэтому dev и demo/prod-like используют один runtime — vLLM.  
>
> **Роль Ollama:**  
> Ollama остаётся optional fallback для local-lite сценариев на Mac: unit-тесты, frontend, mock/stub отладка и разработка без полного LLM stack. Критические сценарии проверяются на vLLM.  
>
> **Рекомендация для Scale:** при росте нагрузки перейти на GPU pool, SGLang/vLLM tensor parallelism или более крупную модель без изменения внешнего LLM client contract.

---

## Контекст

Synapse требует production-grade LLM serving с поддержкой русского языка, работающий полностью локально (on-premise, без внешних API). Система должна обрабатывать запросы с латентностью P95 < 10 сек на GPU. Дополнительные требования: квантование для GPU с ограниченной VRAM, оптимизация KV-cache для высокого throughput, совместимость с OpenAI-compatible API для простой интеграции.

Три режима работы:
- **Local Lite** — Mac 8 GB, mock/Ollama fallback, без полного LLM stack
- **GPU Dev** — VM 64 GB RAM + RTX 4090 24 GB VRAM, основной full-stack development
- **Demo / Prod-like** — GPU-сервер, vLLM inference

---

## Решение

**vLLM** как основной inference сервер в GPU Dev и demo/prod-like режимах. **Ollama** остаётся optional fallback для local-lite разработки.

**Модель:** Qwen2.5-14B-Instruct-AWQ (GPU Dev и demo/prod-like) / Qwen2.5-7B-Q4 или mock LLM (local-lite fallback)

**Конфигурация prod:**
```bash
python -m vllm.entrypoints.openai.api_server \
  --model Qwen/Qwen2.5-14B-Instruct-AWQ \
  --quantization awq \
  --kv-cache-dtype fp8 \
  --port 8001
```

**Переключение через env var:**
```bash
LLM_BACKEND=mock    # local-lite без LLM
LLM_BACKEND=ollama  # local-lite fallback
LLM_BACKEND=vllm    # gpu-dev / demo / prod-like
```

---

## Альтернативы рассмотрены

| Вариант | Плюсы | Минусы | Решение |
|---|---|---|---|
| **Ollama (prod / full dev)** | Простой запуск, хорошо работает на CPU/Apple Silicon, нет зависимости от GPU | Нет KV-cache оптимизации, нет tensor parallelism, throughput существенно ниже vLLM на GPU | **Отклонён для full stack**, оставлен как local-lite fallback |
| **TGI (Text Generation Inference)** | Поддержка многих моделей, активное развитие HuggingFace | Меньший throughput на AWQ моделях, сложнее конфигурация квантования | **Отклонён** |
| **SGLang** | Высокая производительность, активное академическое сообщество | Меньше документации на русском, меньше community support, выше риск для MVP | **Отклонён** |
| **LMDeploy** | Хорошая поддержка квантования, оптимизирован под Qwen | Меньше интеграций с LangChain/LangGraph, меньше примеров | **Отклонён** |
| **OpenAI API** | Эталонное качество, мгновенный старт, богатая экосистема | Данные покидают периметр, нарушает ФЗ-152 и политику ИБ, переменный OpEx | **Отклонён** (блокер по безопасности) |

---

## Trade-offs

**Плюсы vLLM:**
- PagedAttention — эффективное использование VRAM, минимальная фрагментация
- AWQ квантование — Qwen2.5-14B умещается в T4 16GB (~8GB веса + ~4GB KV-cache)
- OpenAI-compatible API — нулевые изменения в коде при переключении с Ollama
- Continuous batching — высокий throughput при параллельных запросах
- fp8 KV-cache — дополнительная экономия VRAM

**Минусы vLLM:**
- Требует GPU для prod (нет смысла на CPU)
- Холодный старт ~2-3 минуты при загрузке модели
- Local-lite fallback через Ollama может расходиться по поведению с vLLM; критические проверки выполняются на GPU Dev

---

## Последствия

- Local Lite: mock/Ollama fallback — достаточно для unit-тестов и разработки без полного stack
- GPU Dev: vLLM + Qwen2.5-14B-AWQ на VM 64 GB RAM + RTX 4090 — основная среда разработки полного MVP
- Demo / Prod-like: vLLM + Qwen2.5-14B-AWQ на GPU-сервере — для демо и нагрузочных тестов
- Единый LLM client в `/backend/llm/client.py` абстрагирует оба бэкенда
- Логи vLLM показывают tokens/sec и KV-cache hit rate — используется в видео-демо
- В Scale-этапе: возможна замена на SGLang или переход на Qwen3-30B без изменения архитектуры

---

## Compliance & Ethics

**Регуляторное соответствие:**
- Решение полностью соответствует требованиям **ФЗ-152** («О персональных данных»): никакие данные не передаются во внешние API
- Соответствует внутренней политике ИБ: модель работает в изолированном контуре без доступа в интернет
- Использована модель с открытой лицензией (Qwen2.5 — Apache 2.0), допускающей коммерческое использование без лицензионных отчислений

**Этические риски и меры снижения:**
- Qwen2.5 — instruction-tuned модель, существует остаточный риск генерации некорректных или предвзятых ответов. Мера: Output Guardrail (проверка ответа перед отдачей пользователю, фильтрация токсичности)
- Риск галлюцинаций на сложных запросах. Мера: принцип «Retrieval before generation» — LLM получает контекст только из корпуса, Self-Reflection с оценкой quality_score
- В ответе пользователю не раскрывается название и версия используемой модели (защита от целенаправленных атак на специфику модели)
