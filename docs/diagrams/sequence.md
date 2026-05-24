```mermaid
sequenceDiagram
    autonumber

    actor User as Сотрудник
    participant UI as React UI
    participant NGX as nginx
    participant API as FastAPI (routes.py)
    participant VAL as QueryRequest validator
    participant PQ as prepare_query node
    participant VR as vector_retriever node
    participant GR as graph_retriever node
    participant MR as merge_results node
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

    API->>PQ: run_agent(query, access_level, settings)
    activate PQ
    Note over PQ: preprocessing only — strip + extract_entities()\nНЕ security gate (injection/PII уже обработаны выше)
    PQ->>PQ: extract_entities(query) → entity list
    PQ->>LF: LangGraph callback: span prepare_query
    deactivate PQ

    Note over VR,GR: Параллельный запуск через LangGraph Send() API (FR-45)

    par vector_retriever node
        activate VR
        VR->>EMB: embed_query(query)
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

    MR->>MR: _merge(): α=0.7 × vector + 0.3 × graph, дедупликация
    MR-->>GEN: топ-5 источников

    loop quality_score < 3.0 AND iterations < agent_max_iterations (3)

        activate GEN
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
            CS-->>VR: retry: Send(vector_retriever, state)
            CS-->>GR: retry: Send(graph_retriever, state)
            deactivate CS
            Note over VR,GR: Повторный параллельный retrieval\n(тот же query и entities — без re-embedding)
            par retry vector
                VR->>EMB: embed_query(query)
                EMB-->>VR: вектор
                VR->>QD: повторный поиск
                QD-->>VR: новые чанки
                VR-->>MR: vector_chunks
            and retry graph
                GR->>N4J: повторный traversal
                N4J-->>GR: новые сущности
                GR-->>MR: graph_results
            end
            MR->>MR: merge
            MR-->>GEN: новые источники
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
    Note over UI: Streaming не реализован (stream=False)\nПолный ответ одним блоком
```
