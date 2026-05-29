```mermaid
sequenceDiagram
    autonumber

    actor User as Сотрудник
    participant UI as Synapse UI (Vanilla JS SPA)
    participant NGX as nginx (опционально)
    participant API as FastAPI (routes.py)
    participant VAL as QueryRequest validator
    participant QS as QueryService (domain gate)
    participant PQ as prepare_query node
    participant QRW as query_rewriter node
    participant VR as vector_retriever node
    participant GR as graph_retriever node
    participant MR as merge_results node
    participant RC as role_context node
    participant EMB as Embedding Service
    participant QD as Qdrant
    participant N4J as Neo4j
    participant GEN as generator node
    participant CRIT as critic node
    participant CS as confidence_score node
    participant OG as output_guard node
    participant KG as knowledge_gap node
    participant LLM as vLLM Engine
    participant SQLITE as SQLite (gap_store)
    participant LF as Langfuse

    User->>UI: Вопрос на русском языке
    UI->>NGX: HTTPS POST /query {question, role}
    NGX->>API: HTTP POST /query
    API->>API: X-User-Role → access_level (role_to_access_level)

    API->>VAL: Входящий запрос
    activate VAL
    Note over VAL: FR-26 injection check + FR-25 PII mask\n(Pydantic field_validator)
    alt PII или prompt injection обнаружен
        VAL-->>API: ValueError → HTTP 422 Unprocessable Entity
        API-->>User: 422 — запрос заблокирован
    else Запрос чистый
        VAL-->>API: masked query
    end
    deactivate VAL

    API->>QS: QueryService.ask(query, access_level)
    activate QS
    Note over QS: Доменный security gate — дублирует проверки для\nнеHTTP-вызовов (скрипты, тесты): FR-26 injection + FR-25 PII
    QS->>PQ: run_agent() → LangGraph ainvoke
    deactivate QS
    activate PQ
    Note over PQ: preprocessing only — strip + extract_entities()\nНЕ security gate (injection/PII уже обработаны выше)
    PQ->>PQ: extract_entities(query) → entity list
    PQ->>LF: LangGraph callback: span prepare_query
    deactivate PQ

    activate QRW
    QRW->>LLM: POST /v1/chat/completions — rewrite prompt [sync, max_tokens=80]
    LLM-->>QRW: query_rewritten (поисковые термины)
    Note over QRW: «Как проходит онбординг?» →\n«процедура адаптации этапы документы ответственные»
    QRW->>LF: span: query_rewriter
    deactivate QRW

    Note over VR,GR: Параллельный запуск через LangGraph Send() API (FR-45)

    par vector_retriever node
        activate VR
        VR->>EMB: embed_query(query_rewritten)
        EMB-->>VR: вектор [768]
        VR->>QD: vector search + payload filter(access_level ≤ user_level)
        QD-->>VR: Top-K чанков с scores
        VR->>LF: span: vector_retriever
        VR-->>MR: vector_chunks
        deactivate VR
    and graph_retriever node
        activate GR
        GR->>N4J: MATCH traversal WHERE COALESCE(access_level,1) ≤ $lvl
        N4J-->>GR: связанные сущности
        GR->>LF: span: graph_retriever
        GR-->>MR: graph_results
        deactivate GR
    end

    MR->>MR: _merge(): RRF fusion — alpha/(k+rank_v) + graph_signal/(k+rank_g), дедупликация
    MR-->>RC: sources (top merged)

    activate RC
    Note over RC: Детерминированный lookup: access_level → role_hint\nL1=пошаговые инструкции / L3=архитектурные нюансы\nL4=метрики и compliance / L5=полная картина
    RC-->>GEN: role_hint + sources
    deactivate RC

    loop quality_score < 3.0 AND iterations < agent_max_iterations (3)

        activate GEN
        Note over GEN: system_prompt + role_hint + [DOC-ID: Title] section\ntext × 5 чанков
        GEN->>LLM: generate(context, query) [async]
        LLM-->>GEN: ответ
        GEN->>LF: span: generator
        GEN-->>CRIT: answer + trace_id
        deactivate GEN

        activate CRIT
        Note over CRIT: VLLMCriticAgent (gpu-demo) или MockCriticAgent (local-lite)
        alt llm_backend == vllm
            CRIT->>LLM: POST /v1/chat/completions — scoring prompt [sync http]
            LLM-->>CRIT: quality float 1.0–4.0
        else mock mode
            CRIT->>CRIT: score = 1.0 + min(n_sources × 0.5, 3.0)
        end
        CRIT->>LF: span: critic — quality_score, iterations
        CRIT-->>CS: quality_score + iterations
        deactivate CRIT

        activate CS
        CS->>CS: _compute_confidence(sources)\navg(1 − age_days/365)
        CS->>LF: span: confidence_score

        alt quality_score < 3.0 AND iterations < 3
            CS-->>GEN: generator-only retry: Send(generator, state)
            deactivate CS
            Note over GEN: sources уже в state — re-retrieval пропущен (~1–2 с экономии)\ncritic_feedback → retry_feedback в system_prompt генератора
        end

    end

    activate CS
    alt quality_score >= 3.0 OR quality_score >= 2.0 после max iter
        CS->>OG: передать answer + sources
        deactivate CS

        activate OG
        OG->>OG: mask_pii(answer) — FR-27
        OG->>LF: span: output_guard
        OG-->>API: answer + sources + quality_score + confidence_score
        deactivate OG

        API-->>User: QueryResponse {answer, sources, quality_score, confidence_score, gap_detected=false}

    else quality_score < 2.0 после max iterations
        CS->>KG: передать query + access_level + quality_score
        deactivate CS

        activate KG
        KG->>SQLITE: INSERT knowledge_gaps (query, access_level, quality_score, iterations, timestamp)
        KG->>LF: span: knowledge_gap
        KG-->>API: gap_detected=True
        deactivate KG

        API-->>User: QueryResponse {answer="", gap_detected=true}
    end

    UI-->>User: Ответ отрисован
    Note over UI: stream=False — полный JSON одним блоком\nTyping-анимация (слово за словом) на стороне UI
```
