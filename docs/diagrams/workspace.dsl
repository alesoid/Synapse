workspace "Synapse" "Корпоративная платформа интеллектуального анализа знаний" {

  model {

    u1 = person "Сотрудник" "Q&A запросы"
    u2 = person "Admin / Analyst" "Explorer, управление"

    fs = softwareSystem "Knowledge Sources" "PDF, DOCX, XLSX, сканы, чертежи" {
      tags "External"
    }
    corp = softwareSystem "Corporate Systems" "ERP, CRM, HR, GitLab, Confluence" {
      tags "External" "Future"
    }
    idp = softwareSystem "Identity Provider" "LDAP / Active Directory" {
      tags "External" "Future"
    }

    synapse = softwareSystem "Synapse" "AI-платформа корпоративных знаний" {

      group "Frontend" {
        ui = container "Web UI" "Веб-интерфейс пользователя" "Tailwind CDN + Vanilla JS SPA" {
          tags "Frontend"
        }
      }

      group "Control Plane" {
        nginx = container "nginx" "Load Balancer, Reverse Proxy" "nginx 1.25" {
          tags "ControlPlane"
        }
        api = container "API Gateway" "REST API, маршрутизация, RBAC" "FastAPI + uvicorn" {
          tags "ControlPlane"
        }
        orchestrator = container "LangGraph Orchestrator" "Multi-Agent оркестрация: параллельный retrieval, CriticAgent (LLM-as-a-Judge), Guardrails" "LangGraph 0.6.x" {
          tags "ControlPlane"

          # ── Memory ──────────────────────────────────────────
          agent_state = component "AgentState" "Состояние агентов (TypedDict): query, access_level, vector_chunks, graph_results, sources, answer, quality_score, confidence_score, iterations, gap_detected, trace_id" "Python TypedDict" {
            tags "Memory"
          }

          # ── Security (API layer + domain layer — НЕ LangGraph ноды) ─────────────
          input_guard = component "InputGuard" "Двухслойная защита: (1) QueryRequest.strip_and_guard_query — Pydantic HTTP gate; (2) QueryService.ask() — domain gate. FR-26 injection block; FR-25 PII mask. Выполняется ДО вызова run_agent()." "api/schemas.py + query/service.py" {
            tags "Planner"
          }
          output_guard = component "OutputGuard" "Маскирует PII в ответе LLM перед отдачей пользователю (FR-27)" "LangGraph Node — agents/nodes.py" {
            tags "Planner"
          }

          # ── Agents ───────────────────────────────────────────
          prepare_query_node = component "prepare_query" "Первая нода LangGraph: strip + extract_entities(). НЕ security gate." "LangGraph Node" {
            tags "Planner"
          }
          query_rewriter_node = component "query_rewriter" "Перефразирование запроса: вопрос → поисковые термины (document-style) для лучшего vector recall. Записывает query_rewritten в state." "LangGraph Node" {
            tags "Planner"
          }
          dispatch_retrievers_edge = component "dispatch_retrievers" "Conditional edge от query_rewriter: запускает vector_retriever и graph_retriever параллельно через LangGraph Send() API (langgraph.constants.Send)" "LangGraph Conditional Edge" {
            tags "Planner"
          }
          vector_retriever = component "vector_retriever" "Семантический поиск в Qdrant с RBAC фильтром (access_level); использует query_rewritten" "LangGraph Node" {
            tags "Planner"
          }
          graph_retriever = component "graph_retriever" "Graph traversal в Neo4j; RBAC WHERE COALESCE(access_level,1) <= user_level; возвращает match_count + hop_distance" "LangGraph Node" {
            tags "Planner"
          }
          merge_results = component "merge_results" "RRF-слияние: alpha/(k+rank_v) + (1-alpha)*graph_signal/(k+rank_g); дедупликация по (doc_id, section)" "LangGraph Node — query/pipeline.py" {
            tags "Planner"
          }
          role_context_node = component "role_context" "Детерминированный role_hint по access_level (L1–L5): фокус ответа генератора. Без LLM, O(1)." "LangGraph Node" {
            tags "Planner"
          }
          generator_agent = component "generator" "Генерация ответа на основе топ-5 чанков + role_hint; на retry передаёт critic_feedback как retry_feedback в system_prompt" "LangGraph Node + vLLM" {
            tags "Planner"
          }
          critic_agent = component "critic" "Оценка ответа: CriticResult(quality_score: float, feedback: str); gpu-demo — LLM-as-a-Judge через vLLM" "LangGraph Node" {
            tags "Planner"
          }
          confidence_score_node = component "ConfidenceScore" "confidence_score = avg(1 - age_days/365); маршрутизатор: generator-only retry / knowledge_gap / output_guard" "LangGraph Node" {
            tags "Planner"
          }
          knowledge_gap = component "knowledge_gap" "Фиксирует неотвеченный запрос (quality_score < 2 после max iterations) в SQLite WAL gap_store; PostgreSQL — цель для production, не реализована" "LangGraph Node" {
            tags "Planner"
          }

          # ── Tools ────────────────────────────────────────────
          qdrant_tool = component "Qdrant Tool" "Векторный поиск с RBAC payload filter" "qdrant-client" {
            tags "Tool"
          }
          neo4j_tool = component "Neo4j Tool" "Graph traversal с RBAC WHERE clause" "neo4j Python driver" {
            tags "Tool"
          }
          vllm_tool = component "vLLM Tool" "LLM inference, JSON mode; OpenAI-compatible API" "httpx → vLLM /v1/chat/completions" {
            tags "Tool"
          }
          ontology_tool = component "Ontology" "Загружает docs/ontology.json при старте; нормализует сущности через fuzzy match (difflib, cutoff=0.75); FR-39–41" "Python lru_cache" {
            tags "Tool"
          }
          langfuse_tool = component "Langfuse Callback" "Трейсинг LangGraph нод через LangChain callback; OTel-совместимый экспорт в Langfuse" "langfuse.callback.CallbackHandler" {
            tags "Tool"
          }
          prometheus_tool = component "Prometheus Metrics" "request_latency_seconds, request_count_total (instrumentator); synapse_llm_tokens_per_second, synapse_llm_generation_seconds (custom)" "prometheus_client" {
            tags "Tool"
          }
        }

        ingestion = container "Ingestion Pipeline" "Document Preparation (pymupdf + easyocr + Qwen2.5-VL), чанкинг, извлечение сущностей" "Python + LangChain" {
          tags "ControlPlane"
        }
      }

      group "Data Plane" {
        vllm = container "vLLM Engine" "LLM inference, KV-cache, AWQ квантование" "vLLM + Qwen2.5-14B-AWQ" {
          tags "DataPlane"
        }
        embeddings = container "Embedding Service" "Векторизация текста" "Embedding adapter + nomic-embed-text" {
          tags "DataPlane"
        }
        qdrant = container "Qdrant" "Векторное хранилище, payload filters для RBAC" "Qdrant v1.9" {
          tags "DataPlane" "Database"
        }
        neo4j = container "Neo4j" "Knowledge Graph, Cypher traversal" "Neo4j 5.18 Community" {
          tags "DataPlane" "Database"
        }
        postgres = container "PostgreSQL" "Только трейсы Langfuse. Knowledge Gaps хранятся в SQLite WAL (gap_store.py) во всех режимах; PostgreSQL — цель для production, не реализована." "PostgreSQL 16" {
          tags "DataPlane" "Database"
        }
      }

      group "Observability" {
        langfuse = container "Langfuse" "Трейсинг LangGraph нод, LLM-as-a-Judge" "Langfuse v2" {
          tags "Observability"
        }
        prometheus = container "Prometheus" "Сбор метрик" "Prometheus v2" {
          tags "Observability"
        }
        grafana = container "Grafana" "Дашборды: latency, RPS, tokens/sec" "Grafana v10" {
          tags "Observability"
        }
      }
    }

    # Люди → система (Level 1)
    u1 -> synapse "via User Channels"
    u2 -> synapse "via User Channels"

    # Люди → Frontend (Level 2)
    u1 -> ui "via User Channels"
    u2 -> ui "via User Channels"

    # Внешние системы (Level 1)
    synapse -> fs "читает документы (batch)"
    synapse -> corp "data exchange [future]"
    corp -> synapse "data & context [future]"
    synapse -> idp "проверка credentials [future]"

    # Внешние системы → контейнеры (Level 2)
    ingestion -> fs "читает документы (batch)"
    ingestion -> corp "читает данные [future]"
    api -> idp "проверка credentials [future]"

    # Frontend → Control Plane
    ui -> nginx "HTTPS"
    nginx -> api "HTTP"

    # Control Plane
    api -> orchestrator "запрос на Q&A"
    api -> ingestion "запрос на ingestion"

    # Orchestrator → Data Plane
    orchestrator -> embeddings "векторизация запроса"
    orchestrator -> qdrant "векторный поиск с RBAC filter"
    orchestrator -> neo4j "graph traversal с RBAC"
    orchestrator -> vllm "генерация ответа"

    # Ingestion → Data Plane
    ingestion -> embeddings "векторизация чанков"
    ingestion -> qdrant "запись чанков"
    ingestion -> neo4j "запись графа сущностей"
    ingestion -> vllm "извлечение сущностей (JSON mode)"

    # Observability
    api -> prometheus "метрики запросов"
    orchestrator -> prometheus "метрики агента"
    orchestrator -> langfuse "трейсы нод"
    langfuse -> postgres "хранение трейсов"
    prometheus -> grafana "метрики"

    # Компоненты — поток данных внутри оркестратора (Multi-Agent, ADR-012)
    # Топология: input_guard (API/domain layer) → prepare_query → query_rewriter
    #            → [Send()] vector_retriever ──┐
    #            → [Send()] graph_retriever  ──┤→ merge_results → role_context → generator_agent
    #            → critic_agent → confidence_score_node → {generator-only retry / knowledge_gap / output_guard}
    input_guard -> agent_state "обновляет query, access_level в state (до LangGraph)"
    prepare_query_node -> query_rewriter_node "entities извлечены"
    query_rewriter_node -> vector_retriever "Send() — параллельно, query_rewritten (FR-45)"
    query_rewriter_node -> graph_retriever "Send() — параллельно, entities (FR-45)"
    vector_retriever -> qdrant_tool "векторный поиск + RBAC payload filter"
    graph_retriever -> neo4j_tool "graph traversal + RBAC WHERE + match_count/hop_distance"
    graph_retriever -> ontology_tool "нормализация сущностей (fuzzy match)"
    vector_retriever -> merge_results "vector_chunks"
    graph_retriever -> merge_results "graph_results"
    merge_results -> role_context_node "sources (RRF-merged)"
    role_context_node -> generator_agent "role_hint + sources"
    generator_agent -> vllm_tool "генерация ответа (gpu-demo)"
    generator_agent -> critic_agent "answer + sources + query (state transition)"
    critic_agent -> confidence_score_node "quality_score + critic_feedback → state"
    confidence_score_node -> output_guard "quality_score >= threshold (FR-48a)"
    confidence_score_node -> generator_agent "generator-only retry: Send(generator, state) (FR-48a/b)"
    confidence_score_node -> knowledge_gap "quality_score < 2 после max iterations (FR-31)"
    output_guard -> agent_state "финальный answer (PII-masked)"
    knowledge_gap -> langfuse_tool "gap_detected=True span"
    input_guard -> langfuse_tool "LangGraph callback trace"
    prepare_query_node -> langfuse_tool "LangGraph callback trace"
    query_rewriter_node -> langfuse_tool "LangGraph callback trace"
    vector_retriever -> langfuse_tool "LangGraph callback trace"
    graph_retriever -> langfuse_tool "LangGraph callback trace"
    generator_agent -> langfuse_tool "LangGraph callback trace"
    critic_agent -> langfuse_tool "LangGraph callback trace"
    output_guard -> langfuse_tool "LangGraph callback trace"
    generator_agent -> prometheus_tool "tokens_per_second, generation_seconds"
    api -> prometheus_tool "request_latency_seconds, request_count_total"

    # Deployment Local Lite
    deploymentEnvironment "LocalLite" {
      deploymentNode "Mac 8GB" "Рабочая машина: документация, frontend, unit-тесты, mock/stub сценарии" "macOS" {
        deploymentNode "Docker Desktop" "Docker Engine для Apple Silicon" "Docker Desktop 4.x" {
          deploymentNode "local-lite-network" "Лёгкая Docker сеть без полного LLM stack" "bridge network" {
            deploymentNode "nginx-container" "nginx:1.25-alpine" "Docker Container" {
              containerInstance nginx
            }
            deploymentNode "backend-container" "Python 3.12-slim, mock adapters" "Docker Container" {
              containerInstance api
              containerInstance orchestrator
            }
            deploymentNode "frontend-container" "node:18-alpine" "Docker Container" {
              containerInstance ui
            }
          }
        }
        deploymentNode "Ollama optional" "Local-lite fallback для LLM/embeddings; не основной runtime MVP" "Ollama native (optional)" {
          tags "OllamaDev"
          containerInstance embeddings
          containerInstance vllm
        }
      }
    }

    # Deployment GPU Dev
    deploymentEnvironment "GPUDev" {
      deploymentNode "GPU Dev VM" "64GB RAM, NVIDIA RTX 4090 24GB VRAM" "Ubuntu + NVIDIA Driver" {
        deploymentNode "Docker Engine GPU" "Docker с NVIDIA Container Toolkit" "Docker + CUDA 12.x" {
          deploymentNode "synapse-network" "Внутренняя Docker сеть" "bridge network" {
            deploymentNode "backend-container" "Python 3.12-slim" "Docker Container" {
              containerInstance api
              containerInstance orchestrator
              containerInstance ingestion
            }
            deploymentNode "frontend-container" "node:18-alpine / nginx" "Docker Container" {
              containerInstance ui
              containerInstance nginx
            }
            deploymentNode "vllm-container" "vLLM + Qwen2.5-14B-AWQ" "Docker Container + CUDA" {
              tags "GPU"
              containerInstance vllm
            }
            deploymentNode "embedding-container" "Embedding adapter + nomic-embed-text" "Docker Container" {
              containerInstance embeddings
            }
            deploymentNode "qdrant-container" "qdrant/qdrant:v1.9.0" "Docker Container" {
              containerInstance qdrant
            }
            deploymentNode "neo4j-container" "neo4j:5.18-community" "Docker Container" {
              containerInstance neo4j
            }
            deploymentNode "postgres-container" "postgres:16.14-alpine" "Docker Container" {
              containerInstance postgres
            }
            deploymentNode "langfuse-container" "langfuse/langfuse:2" "Docker Container" {
              containerInstance langfuse
            }
            deploymentNode "prometheus-container" "prom/prometheus:v2.x" "Docker Container" {
              containerInstance prometheus
            }
            deploymentNode "grafana-container" "grafana/grafana:10.x" "Docker Container" {
              containerInstance grafana
            }
          }
        }
      }
    }

    # Deployment Demo / Prod-like
    deploymentEnvironment "Prod" {
      deploymentNode "Yandex Cloud" "Облачная инфраструктура РФ" "Yandex Cloud" {
        deploymentNode "ru-central1-a" "Зона доступности" "Availability Zone" {
          deploymentNode "VPC synapse-net" "Виртуальная частная сеть" "Yandex VPC" {

            deploymentNode "DMZ" "Публичная зона — входящий трафик" "Security Group: порты 80, 443" {
              deploymentNode "vm-gateway" "2 vCPU, 4GB RAM" "Yandex Cloud VM" {
                containerInstance nginx
                containerInstance ui
              }
            }

            deploymentNode "Internal" "Внутренняя зона — закрыта от интернета" "Security Group: только внутренний трафик" {
              deploymentNode "vm-gpu" "gpu-standard-v3, T4 16GB VRAM, 8 CPU, 96GB RAM" "Yandex Cloud GPU VM" {
                tags "GPU"
                deploymentNode "Docker Engine GPU" "Docker с NVIDIA Container Toolkit" "Docker + CUDA 12.2" {
                  containerInstance api
                  containerInstance orchestrator
                  containerInstance ingestion
                  containerInstance vllm
                  containerInstance embeddings
                  containerInstance qdrant
                  containerInstance neo4j
                  containerInstance postgres
                  containerInstance langfuse
                  containerInstance prometheus
                  containerInstance grafana
                }
              }
            }
          }
        }

        deploymentNode "Yandex Object Storage" "S3-совместимое хранилище документов" "Yandex Cloud S3" {
          tags "Future"
        }
        deploymentNode "Yandex Lockbox" "Управление секретами" "Managed Secrets" {
          tags "Future"
        }
      }
    }

  }

  views {

    systemContext synapse "Context" "C4 Level 1 — Context Diagram" {
      include *
      autolayout lr
    }

    container synapse "Containers" "C4 Level 2 — Container Diagram" {
      include *
      autolayout lr
    }

    component orchestrator "Components" "C4 Level 3 — LangGraph Orchestrator" {
      include *
      autolayout lr
    }

    deployment synapse "LocalLite" "Deployment-LocalLite" "Local Lite — Mac 8GB + mocks" {
      include *
      autolayout lr
    }

    deployment synapse "GPUDev" "Deployment-GPUDev" "GPU Dev — RTX 4090 full stack" {
      include *
      autolayout lr
    }

    deployment synapse "Prod" "Deployment-DemoProdLike" "Demo / Prod-like — GPU server" {
      include *
      autolayout lr
    }

    styles {
      element "Person" {
        background #E6F1FB
        stroke #185FA5
        color #0C447C
        shape Person
      }
      element "Software System" {
        background #E1F5EE
        stroke #0F6E56
        color #085041
      }
      element "Frontend" {
        background #E6F1FB
        stroke #185FA5
        color #0C447C
      }
      element "ControlPlane" {
        background #E1F5EE
        stroke #0F6E56
        color #085041
      }
      element "DataPlane" {
        background #EEEDFE
        stroke #534AB7
        color #3C3489
      }
      element "Database" {
        shape Cylinder
      }
      element "Observability" {
        background #FAEEDA
        stroke #854F0B
        color #633806
      }
      element "Memory" {
        background #FAECE7
        stroke #993C1D
        color #712B13
      }
      element "Planner" {
        background #E1F5EE
        stroke #0F6E56
        color #085041
      }
      element "Tool" {
        background #EEEDFE
        stroke #534AB7
        color #3C3489
      }
      element "External" {
        background #F1EFE8
        stroke #5F5E5A
        color #444441
      }
      element "Future" {
        background #F1EFE8
        stroke #5F5E5A
        color #444441
        border dashed
      }
      element "GPU" {
        background #FAECE7
        stroke #993C1D
        color #712B13
      }
      element "OllamaDev" {
        background #FAEEDA
        stroke #854F0B
        color #633806
      }
    }
  }
}
