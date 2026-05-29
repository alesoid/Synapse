# Synapse — централизованное управление сервисами (нативный запуск, без Docker)
# Использование:
#   make start        — запустить все сервисы + API
#   make stop         — остановить API (сторонние сервисы через stop-services)
#   make status       — проверить здоровье всех компонентов
#   make logs         — хвост лога API
#   make ingest       — проиндексировать корпус
#   make test         — запустить тесты

PYTHON      := .venv/bin/python
UVICORN     := .venv/bin/uvicorn
API_HOST    := 0.0.0.0
API_PORT    := 8000
API_PID     := /tmp/synapse_api.pid
API_LOG     := /tmp/synapse_api.log

# ── Запуск ────────────────────────────────────────────────────────────────────

.PHONY: start
start: start-services wait-services start-api status

.PHONY: start-services
start-services:
	@echo "▶ Запуск Qdrant..."
	@sudo systemctl start qdrant 2>/dev/null || echo "  [skip] qdrant не systemd-сервис"
	@echo "▶ Запуск Neo4j..."
	@sudo systemctl start neo4j 2>/dev/null || echo "  [skip] neo4j не systemd-сервис"
	@echo "▶ Запуск vLLM (если настроен)..."
	@sudo systemctl start vllm 2>/dev/null || true

.PHONY: wait-services
wait-services:
	@echo "⏳ Ожидание готовности сервисов..."
	@timeout 30 bash -c 'until curl -sf http://localhost:6333/health > /dev/null 2>&1; do sleep 1; done' \
		&& echo "  ✅ Qdrant ready" || echo "  ⚠️  Qdrant недоступен — продолжаем"
	@timeout 15 bash -c 'until curl -sf http://localhost:7474 > /dev/null 2>&1; do sleep 1; done' \
		&& echo "  ✅ Neo4j ready" || echo "  ⚠️  Neo4j недоступен — продолжаем"

.PHONY: start-api
start-api:
	@if [ -f $(API_PID) ] && kill -0 $$(cat $(API_PID)) 2>/dev/null; then \
		echo "  ℹ️  API уже запущен (PID $$(cat $(API_PID)))"; \
	else \
		echo "▶ Запуск Synapse API на :$(API_PORT)..."; \
		$(UVICORN) backend.api.main:app \
			--host $(API_HOST) --port $(API_PORT) \
			>> $(API_LOG) 2>&1 & \
		echo $$! > $(API_PID); \
		sleep 3; \
		echo "  ✅ API запущен (PID $$(cat $(API_PID)))"; \
	fi

# ── Остановка ─────────────────────────────────────────────────────────────────

.PHONY: stop
stop:
	@if [ -f $(API_PID) ]; then \
		echo "■ Остановка API (PID $$(cat $(API_PID)))..."; \
		kill $$(cat $(API_PID)) 2>/dev/null && rm $(API_PID); \
		echo "  ✅ Остановлен"; \
	else \
		echo "  ℹ️  API не запущен"; \
	fi

.PHONY: stop-services
stop-services: stop
	@sudo systemctl stop qdrant 2>/dev/null || true
	@sudo systemctl stop neo4j  2>/dev/null || true
	@sudo systemctl stop vllm   2>/dev/null || true
	@echo "■ Сервисы остановлены"

.PHONY: restart
restart: stop start

# ── Статус ────────────────────────────────────────────────────────────────────

.PHONY: status
status:
	@echo ""
	@echo "━━━ Synapse status ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@curl -sf http://localhost:$(API_PORT)/health | python3 -m json.tool 2>/dev/null \
		|| echo "  ❌ API http://localhost:$(API_PORT) — недоступен"
	@echo ""
	@curl -sf http://localhost:6333/health > /dev/null \
		&& echo "  ✅ Qdrant   :6333" || echo "  ❌ Qdrant   :6333 — недоступен"
	@curl -sf http://localhost:7474 > /dev/null \
		&& echo "  ✅ Neo4j    :7474" || echo "  ❌ Neo4j    :7474 — недоступен"
	@curl -sf http://localhost:8001/health > /dev/null \
		&& echo "  ✅ vLLM     :8001" || echo "  –  vLLM     :8001 — не используется (mock)"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""

# ── Логи ──────────────────────────────────────────────────────────────────────

.PHONY: logs
logs:
	@tail -f $(API_LOG)

# ── Индексация ────────────────────────────────────────────────────────────────

.PHONY: ingest
ingest:
	@echo "▶ Индексация корпуса..."
	@curl -sf -X POST http://localhost:$(API_PORT)/ingest \
		-H "X-User-Role: admin" \
		-H "Content-Type: application/json" | python3 -m json.tool

# ── Разработка ────────────────────────────────────────────────────────────────

.PHONY: test
test:
	@$(PYTHON) -m pytest tests/ -v --tb=short

.PHONY: install
install:
	@pip install -e ".[dev]"

.PHONY: update
update:
	@git pull
	@pip install -e .
	@$(MAKE) restart
