# C4 Level 4 — Code Diagram: Q&A LangGraph Pipeline

**Scope:** code-level view for `POST /query`.

Shows API validation, domain gate, LangGraph pipeline, retrievers, LLM adapters and persistence.

```mermaid
classDiagram
    direction LR

    class API {
        <<FastAPI>>
        +query()
        +QueryRequest
        +QueryResponse
    }

    class Security {
        <<Guardrails>>
        +role_to_access_level()
        +mask_pii()
        +injection_check()
    }

    class QueryService {
        <<DomainService>>
        +ask()
    }

    class GraphAgent {
        <<ApplicationService>>
        +run_agent()
        +build_graph()
        +AgentState
    }

    class PrepareAndRewrite {
        <<LangGraphNodes>>
        +prepare_query()
        +query_rewriter()
    }

    class Retrieval {
        <<LangGraphNodes>>
        +dispatch_retrievers()
        +vector_retriever()
        +graph_retriever()
    }

    class MergeAndContext {
        <<LangGraphNodes>>
        +merge_results()
        +role_context()
    }

    class GenerationAndQuality {
        <<LangGraphNodes>>
        +generator()
        +critic()
        +confidence_score()
    }

    class OutputDecision {
        <<LangGraphNodes>>
        +output_guard()
        +knowledge_gap()
    }

    class VectorRetriever {
        <<Adapter>>
        +search()
    }

    class GraphRetriever {
        <<Adapter>>
        +search()
    }

    class LLMAdapter {
        <<Adapter>>
        +generate_answer()
        +evaluate()
    }

    class DataStores {
        <<DataPlane>>
        +Qdrant
        +Neo4j
        +SQLite gaps
    }

    class Observability {
        <<Observability>>
        +Langfuse
        +Prometheus
    }

    API --> Security : validate request
    API --> QueryService : delegate
    QueryService --> Security : domain guard
    QueryService --> GraphAgent : run

    GraphAgent --> PrepareAndRewrite : start
    PrepareAndRewrite --> Retrieval : query + entities
    Retrieval --> VectorRetriever : vector search
    Retrieval --> GraphRetriever : graph search
    VectorRetriever --> DataStores : Qdrant
    GraphRetriever --> DataStores : Neo4j

    Retrieval --> MergeAndContext : results
    MergeAndContext --> GenerationAndQuality : sources + role
    GenerationAndQuality --> LLMAdapter : generate / evaluate
    GenerationAndQuality --> OutputDecision : route
    OutputDecision --> DataStores : record gap
    OutputDecision --> API : answer

    GraphAgent --> Observability : traces
    LLMAdapter --> Observability : metrics
```

## Code Mapping

| Area | Source files | Responsibility |
|---|---|---|
| API | `backend/api/routes.py`, `backend/api/schemas.py` | HTTP contract and request validation |
| Security | `backend/security/*` | RBAC, PII masking, injection guard |
| Domain gate | `backend/query/service.py` | Safe entry point before LangGraph |
| Graph topology | `backend/agents/graph_agent.py`, `backend/agents/state.py` | graph build, state, agent execution |
| LangGraph nodes | `backend/agents/nodes.py` | поиск, генерация, маршрутизация качества |
| Query utilities | `backend/query/pipeline.py`, `backend/query/critic.py` | merge, confidence, critic adapters |
| Retrieval adapters | `backend/retrieval/vector_retriever.py`, `backend/retrieval/graph_retriever.py` | Qdrant and Neo4j access |
| LLM adapter | `backend/llm/client.py` | answer generation |
| Persistence | `backend/db/gap_store.py` | knowledge gaps |

## Requirements Coverage

| Requirement group | Covered by |
|---|---|
| Q&A API and response | API, QueryService, GraphAgent |
| Hybrid retrieval | Retrieval, VectorRetriever, GraphRetriever, MergeAndContext |
| RBAC and guardrails | Security, retriever filters, OutputDecision |
| Quality control and retries | GenerationAndQuality, OutputDecision |
| Knowledge gaps | OutputDecision, Persistence |
| Observability | Observability, GraphAgent, LLMAdapter |
