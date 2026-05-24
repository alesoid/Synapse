---
date: 2026-05-16
версия: "1.2"
Автор: "Алеся Мороз"
status: approved
---

# Synapse — Расчёт ёмкости и план валидации

## 0. Назначение документа

Документ оценивает ресурсные требования Synapse для local-lite разработки, GPU Dev, MVP demo/prod-like окружения и дальнейшего масштабирования. Он переводит уже описанные требования в:

- модель нагрузки;
- sizing CPU/RAM/VRAM/disk;
- ограничения MVP-развёртывания на одном сервере (без HA и Kubernetes);
- риски производительности;
- план проверки расчётов нагрузочными тестами.

Расчёт выполняется для RAG-системы с локальной LLM, векторной БД, графовой БД, API, UI, observability и LLM-трейсингом.

## 1. Исходные допущения

### 1.1 Профили нагрузки

| Профиль | Назначение | Данные | Нагрузка |
|---|---|---:|---:|
| Local Lite Dev | Mac 8 GB: документация, frontend, unit-тесты, mock/stub сценарии | small fixtures | ручные проверки без полного LLM stack |
| GPU Dev | основная разработка полного stack на VM 64 GB RAM + RTX 4090 24 GB VRAM | ~50 документов / до 10k чанков | ручные запросы и предварительные тесты до 10 API RPS |
| MVP Demo / Prod-like | первая production-like версия / защита | до 10k чанков | до 10 API RPS |
| Scale | рост нагрузки после MVP | 100k+ чанков | 50-100 API RPS |

Важно: API RPS и LLM generation RPS не равны. Один API-запрос может завершиться на guardrails, retrieval или cache-слое и не вызвать генерацию LLM. Для LLM отдельно учитываются:

- количество одновременных генераций;
- длина контекста;
- среднее число output tokens;
- tokens/sec целевой модели;
- размер KV-cache.

### 1.2 Целевые NFR для MVP

Полный список NFR описан в `TECHNICAL_SPEC.md`. В этом документе используются только требования, влияющие на расчёт ёмкости.

| Метрика | Цель | Влияние на capacity |
|---|---:|---|
| Retrieval latency P95 | < 300 ms | определяет требования к Qdrant и Neo4j |
| Полный RAG-ответ P95 на GPU | < 10 sec | определяет требования к LLM serving |
| Полный RAG-ответ P95 на GPU Dev | < 10 sec | задаёт ожидания для полноценной разработки и демо |
| Local Lite Dev на Mac 8 GB | без полного LLM stack | не используется для замера RAG latency |
| Error rate 5xx | < 1% | требует контроля OOM, timeouts и очередей |
| Availability | best effort для MVP | HA и multi-region не входят в расчёт |
| Запуск системы | `docker compose up` < 3 минут | ограничивает сложность инфраструктуры |
| Локальность | 0 внешних API | требует self-hosted LLM, БД и observability |

### 1.3 Что входит в расчёт

| Компонент | Входит | Причина |
|---|---|---|
| React UI | да | пользовательский интерфейс MVP |
| FastAPI | да | API orchestration и streaming |
| vLLM / optional Ollama fallback | да | vLLM — основной bottleneck по latency и VRAM; Ollama только local-lite fallback |
| Qdrant | да | vector search и RBAC payload filters |
| Neo4j | да | graph traversal и Explorer режим |
| Langfuse | да | LLM tracing и Knowledge Gaps |
| Prometheus / Grafana | да | метрики для AC-09 и демо |
| Kubernetes / HA / multi-region | нет | вне скоупа MVP |
| JWT / LDAP / AD | нет | scale-этап |

## 2. Development Profiles

Разработка разделяется на два профиля. Mac 8 GB остаётся рабочей машиной для кода и документации, но не является целевой средой полного запуска. Полный stack с LLM, БД и observability разрабатывается на GPU Dev VM.

### 2.1 Local Lite Dev — Mac 8 GB

Назначение local-lite профиля:

- документация и архитектурные артефакты;
- frontend-разработка;
- unit-тесты без LLM;
- mock/stub сценарии API, retrieval и LLM;
- SSH-разработка на GPU Dev VM.

| Компонент | Режим | Оценка RAM | Примечание |
|---|---|---:|---|
| FastAPI | локально или mock | ~0.3 GB | без тяжёлых LLM вызовов |
| React UI | локально | 0.2-0.5 GB | основной local-lite сценарий |
| Qdrant / Neo4j | optional, по одному или small fixtures | 0.3-1.3 GB | не запускать вместе с observability и LLM на 8 GB |
| LLM | mock или optional Ollama fallback | 0-7 GB | не является обязательным runtime для MVP |
| Observability | нецелевой режим | 0 GB | проверяется на GPU Dev / demo |

Вывод: Mac 8 GB не блокирует разработку, но используется как thin client и lightweight-среда. Полный RAG latency на нём не измеряется.

### 2.2 GPU Dev — VM 64 GB RAM + RTX 4090 24 GB

GPU Dev — основная среда разработки полного MVP stack. Она ближе к demo/prod-like окружению, потому что использует тот же LLM runtime (`vLLM`) и модель `Qwen2.5-14B-AWQ`.

| Сервис | Тип | RAM | VRAM | CPU | Порт | Примечание |
|---|---|---:|---:|---:|---:|---|
| vLLM + Qwen2.5-14B-AWQ | stateful | ~4 GB | ~12-16 GB | 2-4 | 8001 | основной потребитель VRAM |
| Embedding adapter | stateless/stateful | 0.5-2 GB | 0-1 GB | 1-2 | internal | Ollama допустим только как fallback |
| Qdrant v1.9 | stateful | ~0.3-2 GB | 0 | 0.1-1 | 6333/6334 | зависит от числа чанков |
| Neo4j 5.18 Community | stateful | 1-4 GB | 0 | 0.1-1 | 7474/7687 | heap/page cache настраиваются |
| PostgreSQL / Langfuse | stateful | 3-6 GB | 0 | 0.5-2 | 5432/3001 | traces, gaps, audit |
| FastAPI + uvicorn | stateless | 0.5-1 GB | 0 | 0.5-1 | 8000 | 1 worker в MVP |
| React UI | stateless | 0.2-0.5 GB | 0 | 0.2-1 | 3000 | nginx / dev-server |
| Prometheus + Grafana | stateful | 0.5-1 GB | 0 | 0.3-1 | 9090/3002 | metrics dashboard |

### 2.3 Итог Development

| Ресурс | Local Lite Dev | GPU Dev |
|---|---:|---:|
| RAM | 8 GB, без полного stack | ~20-30 GB из 64 GB |
| VRAM | нет CUDA GPU | ~12-16 GB из 24 GB |
| CPU | lightweight-тесты | 8+ cores желательно |
| Disk | 50-100 GB | 150-250+ GB |
| Основной LLM runtime | mock / optional Ollama | vLLM |

Вывод: основной риск разработки переносится с RAM Mac на VRAM GPU Dev VM. RTX 4090 подходит для разработки и демо, но не считается enterprise production GPU из-за отсутствия серверных возможностей вроде ECC/MIG; для production-like отчёта это нужно явно указать.

## 3. MVP Demo / Prod-like GPU Profile

Demo/prod-like профиль рассчитан для MVP-развёртывания на одном GPU-сервере без высокой доступности и Kubernetes. Это может быть GPU Dev VM с RTX 4090 для разработки/защиты или отдельный серверный GPU в облаке. Основное ограничение — VRAM, а не системная RAM.

### 3.1 VRAM

| Компонент | VRAM | Комментарий |
|---|---:|---|
| Qwen2.5-14B-AWQ weights | ~8-9 GB | зависит от конкретного AWQ checkpoint |
| KV-cache, context 4096 | ~2-4+ GB | зависит от concurrency, batch size и dtype |
| CUDA / vLLM overhead | ~1-2 GB | runtime buffers, fragmentation, activations |
| Embedding model | 0-0.5 GB | можно держать на CPU или отдельном процессе |
| **Итого** | **~12-15.5 GB** | для T4 16 GB запас ограничен; на RTX 4090 24 GB запас комфортнее |

Примечание: fp8 KV-cache может снизить расход VRAM, но совместимость и качество нужно проверить на целевой версии vLLM и GPU.

Вывод: RTX 4090 24 GB комфортнее для разработки и демо, чем T4 16 GB, но не является enterprise production GPU. T4 16 GB подходит только как минимальный production-like вариант. При добавлении второй модели, увеличении context length или росте concurrency потребуется GPU с 24 GB+ VRAM, например A10/A10G/L4/RTX 4090, либо отдельная GPU-нода.

### 3.2 RAM

| Сервис | RAM |
|---|---:|
| vLLM process, CPU часть | ~4 GB |
| Neo4j Heap + PageCache | ~4 GB |
| Qdrant | ~2 GB |
| Langfuse stack | ~3-6 GB |
| Prometheus + Grafana | ~1 GB |
| FastAPI | ~0.5-1 GB |
| React build + nginx | ~0.2 GB |
| ОС и системный запас | ~4 GB |
| **Итого** | **~18.7-22.2 GB** |

Для сервера с 64-96 GB RAM системная память не является узким местом. Основные риски: VRAM, latency генерации, диск под observability и рост векторного индекса.

## 4. Disk и Retention

Disk sizing для Synapse важен не только из-за пользовательских документов. В RAG-системе диск расходуется на несколько независимых слоёв: исходный корпус, векторный индекс, граф, LLM-трейсы, метрики, логи, модели и backups. Если не задать retention заранее, observability-слой может начать расти быстрее, чем сами бизнес-данные.

### 4.1 Типы данных

| Компонент | Что хранит | Характер роста | Основной риск |
|---|---|---|---|
| Source documents | исходные PDF, DOCX, XLSX, Markdown, CSV | растёт с корпусом документов | потеря воспроизводимости ingestion при удалении исходников |
| Prepared documents | очищенный текст, OCR/Vision output, metadata | растёт с числом документов и версий | дублирование данных после повторного ingestion |
| Qdrant | embeddings, payload, HNSW/index files | растёт с числом чанков и размерностью embedding | рост RAM/disk, увеличение времени snapshot |
| Neo4j | nodes, relationships, properties, transaction logs | растёт с числом сущностей, секций и связей | transaction logs и неочищенные старые версии графа |
| PostgreSQL / Langfuse | traces, prompts, generations, scores, sessions, knowledge gaps | растёт с числом запросов и длиной prompt/response | самый быстрый рост при активном тестировании |
| Prometheus | time-series metrics | растёт от scrape interval, числа targets и retention | незаметный рост TSDB при частом scrape |
| Grafana | dashboards, users, datasource config | почти статичный | низкий риск |
| vLLM / optional Ollama fallback | model weights, quantized checkpoints, tokenizer files | скачкообразный рост при добавлении моделей | десятки GB на модель, дублирование checkpoint-ов |
| Docker | images, layers, volumes, build cache, container logs | растёт при пересборках и тестах | заполнение диска без связи с данными приложения |
| Backups | snapshots Qdrant, Neo4j, PostgreSQL/Langfuse, configs | растёт по расписанию backup | backup может занять больше места, чем live data |

### 4.2 Оценка диска для MVP

Оценки ниже являются sizing-гипотезой для MVP и должны быть уточнены после ingestion тестового корпуса и нагрузочного тестирования.

| Категория | Local Lite Dev | GPU Dev / MVP Demo | Комментарий |
|---|---:|---:|---|
| Source documents | 0.1-2 GB | 1-10 GB | зависит от PDF, сканов и вложений |
| Prepared text / OCR output | optional | 1-5 GB | текст обычно меньше исходных PDF, но OCR/Vision output добавляет объём |
| Qdrant data | optional / fixtures | 2-10 GB | зависит от числа чанков, размерности embeddings и payload |
| Neo4j data | optional / fixtures | 1-5 GB | для MVP граф обычно меньше vector storage |
| Langfuse / PostgreSQL | нецелевой режим | 10-50+ GB | главный источник роста при тестах и demo traffic |
| Prometheus TSDB | нецелевой режим | 5-15 GB | зависит от scrape interval и retention |
| Model cache | 0-15 GB | 20-60 GB | local-lite может использовать mock или Ollama fallback; GPU Dev хранит 14B AWQ и VL-модель |
| Docker images / volumes / logs | 5-15 GB | 10-30 GB | зависит от частоты rebuild и логирования |
| Backups | optional | 20-100+ GB | минимум 1-2 полных backup-набора |
| **Рекомендуемый диск** | **50+ GB** | **150-250+ GB** | для MVP лучше иметь запас под traces, models и backups |

Вывод: для local-lite достаточно около 50 GB свободного места, комфортнее 100 GB. Для GPU Dev / MVP demo разумный стартовый объём persistent disk — 150-250 GB. Если планируются частые нагрузочные тесты с Langfuse tracing, лучше закладывать 300 GB+ или заранее ограничивать trace retention.

### 4.3 Retention policy для MVP

| Данные | Retention для Local Lite | Retention для GPU Dev / MVP Demo | Что делать после срока |
|---|---:|---:|---|
| Source documents | хранить постоянно | хранить постоянно | удалять только вручную вместе с версией корпуса |
| Prepared documents | 7-30 дней | 30-90 дней | пересоздавать из source documents при необходимости |
| Qdrant live index | постоянно | постоянно | удалять только через controlled reindex |
| Qdrant snapshots | optional | daily, хранить 7-14 копий | удалять старые snapshots |
| Neo4j live graph | постоянно | постоянно | удалять только через миграцию или reindex |
| Neo4j backups | optional | daily, хранить 7-14 копий | удалять старые backups |
| Langfuse traces | 3-7 дней | 7-30 дней | удалять старые traces/test runs |
| Knowledge gaps | 30-90 дней | 90-180 дней | агрегировать или экспортировать перед удалением |
| Prometheus metrics | 3-7 дней | 7-15 дней | удалять через TSDB retention |
| Application logs | 3-7 дней | 7-14 дней | log rotation |
| Docker build cache | вручную | вручную / weekly cleanup | чистить после сборок и тестов |
| Model cache | вручную | вручную | хранить только используемые модели |

### 4.4 Почему Langfuse требует отдельного контроля

Langfuse хранит не только факт запроса, но и содержимое LLM-взаимодействия: prompt, context, retrieved chunks, generation, scores, metadata и trace tree. В multi-agent pipeline один пользовательский запрос создаёт несколько spans и LLM-событий, поэтому при нагрузочных тестах traces могут быстро занять несколько GB. Для MVP raw traces хранятся ограниченное время, test runs размечаются тегами, а в `docs/load_test_report.md` фиксируется агрегированный результат.

### 4.5 Backup policy

Для MVP demo/prod-like backups нужны не для enterprise HA, а для воспроизводимости демо и защиты от потери индекса после reindex или очистки volumes. Минимальный набор: Qdrant snapshots, Neo4j dump, PostgreSQL/Langfuse dump, Grafana dashboard export, `.env`/configs и исходный корпус документов. Перед крупным reindex рекомендуется делать snapshots Qdrant и Neo4j, чтобы не прогонять заново OCR, extraction, embeddings и graph construction.

### 4.6 Практические ограничения для MVP

10k чанков занимают больше, чем размер embeddings: payload, metadata, HNSW/index files и snapshots увеличивают фактический объём. Langfuse traces нельзя хранить бессрочно, Vision/OCR временные файлы нужно удалять после ingestion, а Docker volumes должны быть явно названы и задокументированы. Retention должен быть частью docker-compose/env-конфигурации.

## 5. Масштабирование

### 5.1 До 10 API RPS — MVP

| Компонент | Оценка |
|---|---|
| FastAPI | справляется одним инстансом, если LLM-вызовы async |
| Qdrant | 10k чанков должны давать latency < 50-100 ms при корректном индексе |
| Neo4j | достаточно single instance при умеренных graph-запросах и индексах |
| LLM | главный bottleneck; считать по concurrent generations и tokens/sec |
| Observability | подходит для MVP при ограниченном retention |

Если каждый API-запрос доходит до LLM и генерация длится 3-7 секунд, то 10 API RPS создают 30-70 одновременных LLM-сессий. Это worst-case, а не ожидаемая рабочая нагрузка: в реальности часть запросов завершается на guardrails, retrieval-only fallback или cache-слое. Поэтому для MVP нужно отдельно измерять API RPS и LLM generation RPS, ограничить concurrent generations и при необходимости добавить очередь.

### 5.2 До 50 API RPS — Growth

Для 50 API RPS требуется разделить нагрузку:

- FastAPI: 2+ инстанса за nginx/load balancer;
- Qdrant: проверить latency на 100k чанков, рассмотреть on-disk индекс;
- Neo4j: увеличить Heap/PageCache, оптимизировать индексы и Cypher queries;
- LLM: одна T4, скорее всего, не выдержит 50 LLM RPS;
- Observability: вынести storage и настроить retention до нагрузочных тестов.

### 5.3 До 100 API RPS — Scale

100 API RPS — это scale-этап, не MVP. Для такого профиля потребуется:

- Kubernetes / Helm;
- отдельный LLM serving layer;
- GPU pool;
- Qdrant cluster;
- Neo4j Enterprise / read replicas или пересмотр graph workload;
- отдельная observability storage policy;
- очередь для LLM-задач и backpressure на API.

## 6. Оценка стоимости

Точные цены зависят от провайдера и тарифа, поэтому в MVP фиксируется не финальная смета, а категории затрат.

| Категория | Local Lite Dev | GPU Dev / MVP Demo | Примечание |
|---|---:|---:|---|
| Compute CPU/RAM | Mac / рабочая машина | GPU VM + системная RAM | для MVP важен запас RAM под БД и observability |
| GPU | нет CUDA GPU | RTX 4090 24 GB или серверный GPU | главный ограниченный ресурс |
| Storage | локальный диск | persistent disk | нужен запас под модели, БД, traces и backups |
| Backups | опционально | daily snapshots | Qdrant, Neo4j, PostgreSQL |
| Monitoring | нецелевой режим | Prometheus/Grafana/Langfuse | рост данных ограничивается retention |

Примерная оценка для Yandex Cloud Compute Cloud с Intel Ice Lake + NVIDIA T4 по прайс-листу Yandex Cloud:

| Ресурс | Тарифная единица | Цена с НДС с 01.01.2026 | Пример для MVP-ноды |
|---|---:|---:|---:|
| NVIDIA T4 | 1 GPU-hour | 70.272 ₽/час | 70.272 ₽/час |
| vCPU 100% | 1 core-hour | 1.1529 ₽/час | 8 cores = 9.2232 ₽/час |
| RAM | 1 GB-hour | 0.3074 ₽/час | 96 GB = 29.5104 ₽/час |
| **Compute subtotal** |  |  | **~109 ₽/час без диска и трафика** |

Вывод по TCO: для MVP стоимость в основном определяется GPU-нодой и persistent storage. Увеличение LLM concurrency почти всегда дороже, чем масштабирование API-слоя.

Полная финансовая модель (CapEx, OpEx, TCO за 1/3 года, Build vs Buy, ROI/Payback) — в `docs/tco.md`.

## 7. План валидации

Результаты фиксируются в `/docs/load_test_report.md`.

| Проверка | Инструмент | Метрика | Критерий приемки |
|---|---|---|---|
| FastAPI без LLM | Locust / k6 | max API RPS, P95 latency | нет 5xx, стабильная latency |
| Retrieval only | custom script / Locust | Qdrant P95, Neo4j P95 | retrieval P95 < 300 ms |
| Full RAG request | Locust / k6 / custom client | P50/P95 latency, error rate | P95 < 10 sec на GPU, 5xx < 1% |
| LLM serving | vLLM metrics | tokens/sec, concurrent generations | нет OOM, latency соответствует NFR |
| Observability overhead | Prometheus/Grafana | RAM/CPU/disk growth | нет неконтролируемого роста |
| Long context test | vLLM metrics / nvidia-smi | VRAM usage, OOM risk | нет OOM на целевом context length |
| Soak test | Locust / k6 | стабильность 1 час | нет memory leak и деградации latency |

## 8. Риски и открытые вопросы

| Риск | Влияние | Митигация |
|---|---|---|
| T4 16 GB недостаточно для модели и KV-cache | OOM, рост latency | для разработки использовать RTX 4090 24 GB; для demo/prod-like ограничить context/concurrency, fp8 KV-cache или GPU 24 GB+ |
| 10 API RPS ошибочно интерпретируются как 10 LLM RPS | завышенные ожидания | отдельно измерять API RPS и generation RPS |
| Langfuse быстро заполняет диск | disk pressure | retention 7-30 дней, очистка test runs |
| Neo4j queries становятся медленными при росте графа | рост retrieval latency | индексы, query profiling, ограничение depth |
| Qdrant индекс растёт при 100k+ чанков | рост RAM/disk | on-disk index, quantization, cluster на scale |
| Vision-модель конкурирует за VRAM с основной LLM | OOM во время ingestion | запускать vision ingestion отдельно от inference |

## 9. Вывод

| Ресурс | Local Lite Dev | GPU Dev | MVP Demo / Prod-like | Scale |
|---|---:|---:|---:|---:|
| RAM | 8 GB, без полного stack | 64 GB | 64-96 GB | 256+ GB |
| VRAM | нет CUDA GPU | 24 GB RTX 4090 | 16-24+ GB | 24-80+ GB |
| CPU | lightweight-тесты | 8+ cores | 8+ cores | 32+ cores |
| Disk | 50-100 GB | 150-250+ GB | 150-250+ GB | 1+ TB |
| API RPS | не измеряется | предварительно до 10 RPS | до 10 RPS | 50-100 RPS |
| LLM generation RPS | mock / optional fallback | зависит от tokens/sec и concurrency, требует теста | зависит от tokens/sec и concurrency, требует теста | GPU pool |

Для local-lite Mac 8 GB не является целевой средой полного stack. Он используется как рабочая машина для кода, документации, frontend и lightweight-тестов. Полный stack разрабатывается и проверяется на GPU Dev VM с RTX 4090.

Для MVP demo/prod-like системная RAM не является ограничением при сервере 64-96 GB. Основной ограниченный ресурс — VRAM. T4 16 GB подходит только для осторожного MVP с одной quantized LLM, ограниченным concurrency и контролируемым context length; RTX 4090 24 GB комфортнее для разработки и защиты, но не является enterprise production GPU.

Финальные значения RPS нельзя считать подтверждёнными до нагрузочного тестирования. До выполнения AC-09 все RPS-оценки являются предварительными sizing-гипотезами.

После выполнения плана валидации из раздела 7 результаты фиксируются в `docs/load_test_report.md`. Capacity Planning считается подтверждённым после прохождения AC-09: нагрузочный отчёт с P95 latency и RPS.
