# Synapse — полный запуск без sudo и прав администратора
# Все сервисы запускаются как пользовательские процессы.
#
# Настройте пути под ваш сервер:
QDRANT_BIN   ?= $(shell which qdrant 2>/dev/null || echo qdrant)
QDRANT_PORT  ?= 6333
NEO4J_HOME   ?= $(shell echo $$NEO4J_HOME)   # задайте: export NEO4J_HOME=/opt/neo4j
NEO4J_PORT   ?= 7687
VLLM_MODEL   ?= Qwen/Qwen2.5-14B-Instruct-AWQ
VLLM_PORT    ?= 8001
HF_HOME      ?= $(HOME)/synapse/models

PYTHON   := .venv/bin/python
UVICORN  := .venv/bin/uvicorn
API_HOST := 0.0.0.0
API_PORT := 8000
# .env: ищем в корне, затем в infra/
ENV_FILE := $(shell [ -f .env ] && echo .env || echo infra/.env)

# PID-файлы (в /tmp — не требуют прав)
PID_QDRANT := /tmp/synapse_qdrant.pid
PID_NEO4J  := /tmp/synapse_neo4j.pid
PID_VLLM   := /tmp/synapse_vllm.pid
PID_API    := /tmp/synapse_api.pid

LOG_QDRANT := /tmp/synapse_qdrant.log
LOG_NEO4J  := /tmp/synapse_neo4j.log
LOG_VLLM   := /tmp/synapse_vllm.log
LOG_API    := /tmp/synapse_api.log

# ── Запуск всех сервисов ───────────────────────────────────────────────────────

.PHONY: start
start: start-qdrant start-neo4j start-api status

.PHONY: start-gpu   # с vLLM
start-gpu: start-qdrant start-neo4j start-vllm start-api status

# ── Qdrant ────────────────────────────────────────────────────────────────────

.PHONY: start-qdrant
start-qdrant:
	@if curl -sf http://localhost:$(QDRANT_PORT)/healthz > /dev/null 2>&1; then \
		echo "  ✅ Qdrant уже запущен"; \
	elif [ -x "$(QDRANT_BIN)" ] || which qdrant > /dev/null 2>&1; then \
		echo "▶ Запуск Qdrant..."; \
		$(QDRANT_BIN) >> $(LOG_QDRANT) 2>&1 & echo $$! > $(PID_QDRANT); \
		timeout 20 bash -c 'until curl -sf http://localhost:$(QDRANT_PORT)/healthz > /dev/null 2>&1; do sleep 1; done'; \
		echo "  ✅ Qdrant запущен (PID $$(cat $(PID_QDRANT)))"; \
	else \
		echo "  ⚠️  Qdrant не найден (QDRANT_BIN=$(QDRANT_BIN)) — пропускаем"; \
	fi

# ── Neo4j ─────────────────────────────────────────────────────────────────────

.PHONY: start-neo4j
start-neo4j:
	@if curl -sf http://localhost:7474 > /dev/null 2>&1; then \
		echo "  ✅ Neo4j уже запущен"; \
	elif [ -n "$(NEO4J_HOME)" ] && [ -x "$(NEO4J_HOME)/bin/neo4j" ]; then \
		echo "▶ Запуск Neo4j..."; \
		$(NEO4J_HOME)/bin/neo4j start >> $(LOG_NEO4J) 2>&1; \
		sleep 5; echo "  ✅ Neo4j запущен"; \
	elif which neo4j > /dev/null 2>&1; then \
		echo "▶ Запуск Neo4j..."; \
		neo4j start >> $(LOG_NEO4J) 2>&1; \
		sleep 5; echo "  ✅ Neo4j запущен"; \
	else \
		echo "  ⚠️  Neo4j не найден (задайте NEO4J_HOME) — пропускаем"; \
	fi

# ── vLLM (GPU-режим) ──────────────────────────────────────────────────────────

.PHONY: start-vllm
start-vllm:
	@if curl -sf http://localhost:$(VLLM_PORT)/health > /dev/null 2>&1; then \
		echo "  ✅ vLLM уже запущен"; \
	else \
		echo "▶ Запуск vLLM ($(VLLM_MODEL))..."; \
		PYTORCH_CUDA_ALLOC_CONF=expandable_segments:False HF_HOME=$(HF_HOME) \
		$(PYTHON) -m vllm.entrypoints.openai.api_server \
			--model $(VLLM_MODEL) \
			--host 0.0.0.0 --port $(VLLM_PORT) \
			--quantization awq \
			--dtype float16 \
			--max-model-len 8192 \
			--gpu-memory-utilization 0.85 \
			--guided-decoding-backend lm-format-enforcer \
			>> $(LOG_VLLM) 2>&1 & echo $$! > $(PID_VLLM); \
		echo "  ✅ vLLM запущен (PID $$(cat $(PID_VLLM)), прогрев ~3 мин)"; \
	fi

# ── Synapse API ───────────────────────────────────────────────────────────────

.PHONY: start-api
start-api:
	@if [ -f $(PID_API) ] && kill -0 $$(cat $(PID_API)) 2>/dev/null; then \
		echo "  ✅ API уже запущен (PID $$(cat $(PID_API)))"; \
	else \
		echo "▶ Запуск Synapse API на :$(API_PORT)..."; \
		env $$(grep -v '^#' $(ENV_FILE) | xargs) \
		$(UVICORN) backend.api.main:app \
			--host $(API_HOST) --port $(API_PORT) \
			>> $(LOG_API) 2>&1 & \
		echo $$! > $(PID_API); \
		sleep 3; \
		echo "  ✅ API запущен (PID $$(cat $(PID_API)))"; \
	fi

# ── Остановка ─────────────────────────────────────────────────────────────────

.PHONY: stop
stop:
	@$(MAKE) _kill PID=$(PID_API)   NAME=API
	@$(MAKE) _kill PID=$(PID_VLLM)  NAME=vLLM
	@$(MAKE) _kill PID=$(PID_QDRANT) NAME=Qdrant
	@if which neo4j > /dev/null 2>&1; then neo4j stop 2>/dev/null || true; fi
	@if [ -n "$(NEO4J_HOME)" ] && [ -x "$(NEO4J_HOME)/bin/neo4j" ]; then \
		$(NEO4J_HOME)/bin/neo4j stop 2>/dev/null || true; fi

.PHONY: _kill
_kill:
	@if [ -f $(PID) ] && kill -0 $$(cat $(PID)) 2>/dev/null; then \
		kill $$(cat $(PID)) && rm -f $(PID); \
		echo "  ■ $(NAME) остановлен"; \
	fi

.PHONY: restart
restart: stop start

.PHONY: restart-gpu   # полный перезапуск: зависимости + gpu-стек + индексация
restart-gpu:
	@echo "▶ Установка зависимостей..."
	@.venv/bin/pip install -e ".[dev,observability]" -q
	@echo "  ✅ Зависимости установлены"
	@$(MAKE) stop
	@echo "▶ Очистка Qdrant storage..."
	@rm -rf storage/collections/
	@echo "  ✅ Storage очищен"
	@$(MAKE) start-qdrant
	@$(MAKE) start-neo4j
	@$(MAKE) start-vllm
	@$(MAKE) start-api
	@echo "▶ Индексация корпуса..."
	@sleep 3
	@curl -sf -X POST http://localhost:$(API_PORT)/ingest \
		-H "X-User-Role: admin" \
		-H "Content-Type: application/json" | python3 -m json.tool
	@$(MAKE) status

# ── Статус ────────────────────────────────────────────────────────────────────

.PHONY: status
status:
	@echo ""
	@echo "━━━ Synapse status ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@curl -sf http://localhost:$(API_PORT)/health | python3 -m json.tool 2>/dev/null \
		|| echo "  ❌ API :$(API_PORT) — недоступен"
	@curl -sf http://localhost:$(QDRANT_PORT)/healthz > /dev/null \
		&& echo "  ✅ Qdrant  :$(QDRANT_PORT)" || echo "  ❌ Qdrant  :$(QDRANT_PORT)"
	@curl -sf http://localhost:7474 > /dev/null \
		&& echo "  ✅ Neo4j   :7474"  || echo "  ❌ Neo4j   :7474"
	@curl -sf http://localhost:$(VLLM_PORT)/health > /dev/null \
		&& echo "  ✅ vLLM    :$(VLLM_PORT)" || echo "  –  vLLM    :$(VLLM_PORT) (mock)"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""

# ── Утилиты ───────────────────────────────────────────────────────────────────

.PHONY: logs
logs:
	@tail -f $(LOG_API)

.PHONY: logs-all
logs-all:
	@tail -f $(LOG_API) $(LOG_QDRANT) $(LOG_NEO4J) $(LOG_VLLM) 2>/dev/null

.PHONY: ingest
ingest:
	@echo "▶ Индексация корпуса..."
	@curl -sf -X POST http://localhost:$(API_PORT)/ingest \
		-H "X-User-Role: admin" \
		-H "Content-Type: application/json" | python3 -m json.tool

.PHONY: update
update:
	@git pull
	@pip install -e . -q
	@$(MAKE) restart

.PHONY: test
test:
	@$(PYTHON) -m pytest tests/ -v --tb=short

.PHONY: install
install:
	@pip install -e ".[dev]"
