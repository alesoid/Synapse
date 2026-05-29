workspace "Synapse" "Корпоративная платформа интеллектуального анализа знаний" {

  model {

    u1 = person "Сотрудник" "Q&A"
    u2 = person "Администратор / аналитик" "Explorer, управление"

    fs = softwareSystem "Knowledge Sources" "Документы и сканы" {
      tags "External"
    }
    corp = softwareSystem "Corporate Systems" "ERP, CRM, HR, Confluence" {
      tags "External" "Future"
    }
    idp = softwareSystem "Identity Provider" "LDAP / AD" {
      tags "External" "Future"
    }

    synapse = softwareSystem "Synapse" "AI-платформа корпоративных знаний" {

      group "Frontend" {
        ui = container "Web UI" "Пользовательский интерфейс" "Vanilla JS + Tailwind" {
          tags "Frontend"
        }
      }

      group "Control Plane" {
        nginx = container "nginx" "Обратный прокси" "nginx" {
          tags "ControlPlane"
        }
        api = container "API Gateway" "REST API и RBAC" "FastAPI" {
          tags "Supporting"
        }
        orchestrator = container "LangGraph Orchestrator" "Q&A процесс: поиск, генерация, оценка" "LangGraph" {
          tags "ControlPlane"

          # ── Memory ──────────────────────────────────────────
          agent_state = component "AgentState" "Состояние процесса." "Python TypedDict" {
            tags "Memory"
          }

          # ── Security (API layer + domain layer — НЕ LangGraph ноды) ─────────────
          input_guard = component "InputGuard" "Проверка входного запроса." "api/schemas.py + query/service.py" {
            tags "Planner"
          }
          output_guard = component "OutputGuard" "Финальная маскировка ответа." "LangGraph Node" {
            tags "Planner"
          }

          # ── Agents ───────────────────────────────────────────
          prepare_query_node = component "prepare_query" "Подготовка запроса." "LangGraph Node" {
            tags "Planner"
          }
          query_rewriter_node = component "query_rewriter" "Переформулировка для поиска." "LangGraph Node" {
            tags "Planner"
          }
          dispatch_retrievers_edge = component "dispatch_retrievers" "Параллельный запуск поиска." "LangGraph Conditional Edge" {
            tags "Planner"
          }
          vector_retriever = component "vector_retriever" "Векторный поиск." "LangGraph Node" {
            tags "Planner"
          }
          graph_retriever = component "graph_retriever" "Поиск по графу." "LangGraph Node" {
            tags "Planner"
          }
          merge_results = component "merge_results" "Слияние источников." "LangGraph Node" {
            tags "Planner"
          }
          role_context_node = component "role_context" "Контекст роли." "LangGraph Node" {
            tags "Planner"
          }
          generator_agent = component "generator" "Генерация ответа." "LangGraph Node + LLM" {
            tags "Planner"
          }
          critic_agent = component "critic" "Оценка качества." "LangGraph Node" {
            tags "Planner"
          }
          confidence_score_node = component "ConfidenceScore" "Оценка уверенности и маршрутизация." "LangGraph Node" {
            tags "Planner"
          }
          knowledge_gap = component "knowledge_gap" "Фиксация пробела знаний." "LangGraph Node" {
            tags "Planner"
          }

          # ── Tools ────────────────────────────────────────────
          qdrant_tool = component "Qdrant Tool" "Поиск чанков." "qdrant-client" {
            tags "Tool"
          }
          neo4j_tool = component "Neo4j Tool" "Обход графа." "neo4j Python driver" {
            tags "Tool"
          }
          vllm_tool = component "vLLM Tool" "Инференс LLM." "OpenAI-compatible API" {
            tags "Tool"
          }
          ontology_tool = component "Ontology" "Нормализация сущностей." "Python lru_cache" {
            tags "Tool"
          }
          prometheus_tool = component "Prometheus Metrics" "Метрики запросов и LLM." "prometheus_client" {
            tags "Tool"
          }
        }

        ingestion = container "Ingestion Pipeline" "Чанкинг и извлечение сущностей" "Python + LangChain" {
          tags "ControlPlane"
        }
      }

      group "Data Plane" {
        vllm = container "vLLM Engine" "Инференс LLM" "vLLM" {
          tags "DataPlane"
        }
        embeddings = container "Embedding Service" "Векторизация текста" "Embedding adapter" {
          tags "DataPlane"
        }
        qdrant = container "Qdrant" "Векторное хранилище" "Qdrant" {
          tags "DataPlane" "Database"
        }
        neo4j = container "Neo4j" "Граф знаний" "Neo4j" {
          tags "DataPlane" "Database"
        }
        postgres = container "PostgreSQL" "Хранилище трейсов Langfuse" "PostgreSQL" {
          tags "DataPlane" "Database"
        }
      }

      group "Observability" {
        langfuse = container "Langfuse" "Трейсы и оценки LLM" "Langfuse" {
          tags "Supporting"
        }
        prometheus = container "Prometheus" "Сбор метрик" "Prometheus" {
          tags "Observability"
        }
        grafana = container "Grafana" "Дашборды" "Grafana" {
          tags "Observability"
        }
      }
    }

    # Люди → система (Level 1)
    u1 -> synapse "Q&A"
    u2 -> synapse "управление"

    # Люди → Frontend (Level 2)
    u1 -> ui "вопросы"
    u2 -> ui "администрирование"

    # Внешние системы (Level 1)
    synapse -> fs "читает документы"
    synapse -> corp "обмен данными [future]"
    corp -> synapse "контекст [future]"
    synapse -> idp "аутентификация [future]"

    # Внешние системы → контейнеры (Level 2)
    ingestion -> fs "загрузка"
    ingestion -> corp "читает данные [future]"
    api -> idp "аутентификация [future]"

    # Frontend → Control Plane
    ui -> nginx "HTTPS"
    nginx -> api "HTTP"

    # Control Plane
    api -> orchestrator "Q&A"
    api -> ingestion "загрузка"

    # Orchestrator → Data Plane
    orchestrator -> embeddings "векторизация запроса"
    orchestrator -> qdrant "векторный поиск"
    orchestrator -> neo4j "обход графа"
    orchestrator -> vllm "генерация"

    # Ingestion → Data Plane
    ingestion -> embeddings "векторизация чанков"
    ingestion -> qdrant "чанки"
    ingestion -> neo4j "сущности"
    ingestion -> vllm "извлечение сущностей"

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
    input_guard -> agent_state "запрос + уровень доступа"
    input_guard -> prepare_query_node "старт"
    prepare_query_node -> query_rewriter_node "сущности"
    query_rewriter_node -> dispatch_retrievers_edge "параллельный запуск"
    dispatch_retrievers_edge -> vector_retriever "поисковый запрос"
    dispatch_retrievers_edge -> graph_retriever "сущности"
    vector_retriever -> qdrant_tool "поиск с RBAC"
    graph_retriever -> neo4j_tool "обход графа"
    graph_retriever -> ontology_tool "нормализация"
    vector_retriever -> merge_results "векторные результаты"
    graph_retriever -> merge_results "графовые результаты"
    merge_results -> role_context_node "источники"
    role_context_node -> generator_agent "роль + источники"
    generator_agent -> vllm_tool "генерация"
    generator_agent -> critic_agent "ответ"
    critic_agent -> confidence_score_node "оценка качества"
    confidence_score_node -> output_guard "ответ принят"
    confidence_score_node -> generator_agent "повтор генерации"
    confidence_score_node -> knowledge_gap "низкое качество"
    output_guard -> agent_state "финальный ответ"
    prepare_query_node -> langfuse "трейсы нод"
    generator_agent -> prometheus_tool "метрики LLM"
    api -> prometheus_tool "метрики API"

    # Deployment On-premise / Prod-like
    deploymentEnvironment "Prod" {
      deploymentNode "On-premise Datacenter" "Контур заказчика" "ЦОД / серверная" {
        deploymentNode "synapse-net" "Изолированная сеть" "LAN / VLAN" {

          deploymentNode "DMZ" "Публичный контур" "Firewall segment" {
            deploymentNode "gateway-server" "Gateway server" "Linux VM / bare metal" {
              containerInstance nginx
              containerInstance ui
            }
          }

          deploymentNode "Internal" "Внутренний контур" "Firewall segment" {
            deploymentNode "gpu-server" "GPU server" "Linux + NVIDIA GPU" {
              tags "GPU"
              deploymentNode "Docker Engine GPU" "Контейнеры" "Docker + CUDA" {
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

        deploymentNode "Local Object Storage" "Хранилище документов" "S3-compatible / NAS" {
          tags "Future"
        }
        deploymentNode "Secrets Vault" "Секреты" "Vault / local KMS" {
          tags "Future"
        }
      }
    }

  }

  views {

    systemContext synapse "Context" "C4 Level 1 — Context Diagram" {
      include *
    }

    container synapse "Containers" "C4 Level 2 — Container Diagram" {
      include *
    }

    component orchestrator "Components" "C4 Level 3 — LangGraph Orchestrator" {
      include *
    }

    deployment synapse "Prod" "Deployment-DemoProdLike" "Deployment — on-premise GPU server" {
      include *
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
      element "Supporting" {
        background #F1F5F9
        stroke #64748B
        color #334155
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
    }
  }
}
