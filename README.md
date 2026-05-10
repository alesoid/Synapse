# Synapse 🧠

> Корпоративная платформа интеллектуального анализа знаний на основе GraphRAG

Synapse — это on-premise система для поиска по корпоративным документам, работающая полностью в закрытом контуре без обращения к внешним API. В отличие от обычного RAG, Synapse строит граф знаний из документов и комбинирует векторный поиск с графовым траверсалом, что даёт более точные и контекстно-обогащённые ответы.

---

## Ключевые возможности

- **GraphRAG** — гибридный поиск: векторный (Qdrant) + графовый (Neo4j Knowledge Graph)
- **RBAC** — разграничение доступа на уровне чанков по ролям (Junior / Middle / Senior / Manager / Admin)
- **Q&A режим** — вопрос на русском языке → ответ со ссылками на источники
- **Explorer режим** — визуализация графа знаний для Admin/Analyst
- **Guardrails** — фильтрация PII и защита от prompt injection
- **Полная локальность** — vLLM + Qwen2.5, без OpenAI/Anthropic

---

## Стек

| Компонент | Технология |
|---|---|
| LLM (prod) | vLLM + Qwen2.5-14B-AWQ |
| LLM (dev) | Ollama + Qwen2.5-7B-Q4 |
| Embeddings | nomic-embed-text |
| Vector DB | Qdrant v1.9 |
| Graph DB | Neo4j 5.18 Community |
| Orchestration | LangGraph |
| API | FastAPI |
| Frontend | React + TypeScript + Tailwind |
| Observability | Langfuse + Prometheus + Grafana |
| Infra | Docker Compose |
| Cloud | Yandex Cloud gpu-standard-v3 (T4) |

---

## Быстрый старт

### Требования
- Docker + Docker Compose v2
- 16GB RAM (минимум)
- Ollama (для dev режима): `brew install ollama`

### Запуск (dev режим, Apple M3 / CPU)

```bash
# 1. Клонировать репозиторий
git clone https://github.com/<your-username>/synapse.git
cd synapse

# 2. Скопировать конфигурацию
cp .env.example .env

# 3. Запустить стек
docker compose up -d

# 4. Проверить что все сервисы healthy
docker compose ps
```

### Запуск (prod режим, GPU сервер)

```bash
# Запустить с vLLM профилем
docker compose --profile gpu up -d
```

### Загрузка документов

```bash
curl -X POST http://localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{"file_path": "docs/corpus/sample/gitlab_handbook.pdf", "access_level": 1}'
```

### Первый запрос

```bash
curl -X POST http://localhost:8000/query \
  -H "X-User-Role: junior" \
  -H "Content-Type: application/json" \
  -d '{"question": "Какой процесс согласования доступа к продакшн-серверам?"}'
```

---

## Структура репозитория

```
synapse/
├── docker-compose.yml          # Полный стек одной командой
├── .env.example                # Шаблон переменных окружения
├── backend/
│   ├── agents/                 # LangGraph агенты
│   ├── api/                    # FastAPI эндпоинты
│   ├── db/                     # Клиенты Qdrant и Neo4j
│   ├── embeddings/             # Ollama embeddings
│   ├── ingestion/              # Pipeline загрузки документов
│   ├── retrieval/              # Гибридный поиск
│   └── security/               # RBAC + Guardrails
├── frontend/                   # React + TypeScript UI
├── infra/
│   ├── nginx/                  # Load balancer конфиг
│   ├── prometheus/             # Метрики конфиг
│   ├── grafana/                # Дашборды
│   └── locustfile.py           # Нагрузочные тесты
└── docs/
    ├── CONCEPT.md              # Концепция проекта
    ├── ТЗ.md                   # Техническое задание
    ├── ADD.md                  # Architecture Design Document
    ├── ADR/                    # Architecture Decision Records
    ├── diagrams/               # C4, Sequence, ER, Deployment, Data Flow
    ├── corpus/                 # Тестовый корпус документов
    ├── capacity_planning.md    # Расчёт ресурсов
    └── load_test_report.md     # Результаты нагрузочного теста
```

---

## Документация

| Документ | Описание |
|---|---|
| [CONCEPT.md](docs/CONCEPT.md) | Концепция, проблема, value proposition, стратегия PoC→MVP→Scale |
| [ТЗ.md](docs/ТЗ.md) | Техническое задание, функциональные и нефункциональные требования |
| [ADD.md](docs/ADD.md) | Architecture Design Document — полное техническое описание |
| [ADR/](docs/ADR/) | Architecture Decision Records — обоснование технических решений |
| [diagrams/](docs/diagrams/) | C4 (4 уровня), Deployment, Sequence, Data Flow, ER диаграммы |
| [capacity_planning.md](docs/capacity_planning.md) | Расчёт ресурсов инфраструктуры |
| [load_test_report.md](docs/load_test_report.md) | Результаты нагрузочного тестирования |

---

## Роли и доступ

| Роль | Уровень | Доступные документы |
|---|---|---|
| Junior | 1 | Публичные регламенты, онбординг |
| Middle | 2 | + Технические стандарты |
| Senior | 3 | + Архитектурные решения, ADR |
| Manager | 4 | + HR-политики, согласования |
| Admin | 5 | Все документы + Explorer режим |

---

## Демо-сценарии

**Сценарий 1 — Q&A с RBAC:**
Junior спрашивает про процесс согласования доступа → получает ответ с источниками → трейс виден в Langfuse

**Сценарий 2 — RBAC блокировка:**
Junior пытается получить HR-документ уровня Manager → система возвращает сообщение об ограничении доступа

**Сценарий 3 — Graph Explorer:**
Admin открывает Explorer → видит граф связей между документами, ролями и процессами в Neo4j Browser

Сценарий 4 — Guardrails:
Пользователь отправляет запрос с PII (например email) или prompt injection → система блокирует/фильтрует → в ответе видно что сработал guardrail → трейс в Langfuse показывает ноду input_guard

Сценарий 5 — Self-Reflection:
Намеренно сложный вопрос → агент делает 2-3 итерации → в Langfuse видно retry цикл → финальный ответ лучше первого

Сценарий 6 — Ingestion + логи vLLM:
Загрузка нового документа → извлечение сущностей → граф обновился в Neo4j Workspace → логи vLLM показывают tokens/sec
---

## Сервисы и порты

| Сервис | URL | Описание |
|---|---|---|
| Frontend | http://localhost:3000 | React UI |
| API | http://localhost:8000 | FastAPI + Swagger `/docs` |
| Neo4j Browser | http://localhost:7474 | Визуализация графа |
| Langfuse | http://localhost:3001 | Трейсы запросов |
| Grafana | http://localhost:3002 | Метрики |
| Prometheus | http://localhost:9090 | Сбор метрик |
| Qdrant | http://localhost:6333 | Vector DB UI |

---

## Переменные окружения

Скопируй `.env.example` в `.env` и заполни:

```bash
# Neo4j
NEO4J_PASSWORD=your_password

# LLM Backend (ollama или vllm)
LLM_BACKEND=ollama
OLLAMA_HOST=http://host.docker.internal:11434
VLLM_HOST=http://vllm:8001

# Langfuse
LANGFUSE_SECRET_KEY=your_secret
LANGFUSE_PUBLIC_KEY=your_public
```

---

## Лицензия

MIT
