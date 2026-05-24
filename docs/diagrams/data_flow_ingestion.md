```mermaid
flowchart TD
    subgraph STATUS["Статус реализации"]
        IMPL["✅ Реализовано"]
        TBD["🔲 Не реализовано (TBD / ADR-013)"]
    end

    subgraph EXT["Knowledge Sources"]
        DOC_MD["Markdown-файл\n[.md]\n✅ Реализовано"]
        DOC_OTHER["PDF / DOCX / XLSX / скан / чертёж\n🔲 TBD (ADR-013)"]
    end

    subgraph PREP["Document Preparation Pipeline"]
        META["corpus_manifest.json\nметаданные: doc_id, access_level,\ndoc_type, last_updated, topics\n✅ load_markdown_corpus()"]
        VALID_META["access_level обязателен\n(в corpus_manifest — не HTTP-валидация)\n✅"]

        subgraph L1_IMPL["Слой 1 — реализован"]
            PARSE_MD["Чтение .md файла\n✅ corpus_loader.py"]
            CHUNK["Чанкинг\n500 токенов, overlap 50\nиерархический по заголовкам\n✅ chunker.py"]
        end

        subgraph L1_TBD["Слой 1 — TBD (ADR-013)"]
            PARSE_PDF["PyMuPDF get_text()\n🔲 PDF нативный"]
            PARSE_OCR["easyocr (ru+en)\n🔲 Скан / нет текста"]
            PARSE_STRUCT["python-docx / openpyxl\n🔲 DOCX / XLSX"]
        end

        subgraph L2_TBD["Слой 2: Vision — TBD (ADR-013)"]
            VISION["Qwen2.5-VL-7B\nОписание чертежей и схем\n🔲 при VISION_ENABLED=true"]
        end

        NORM["Нормализация терминов\nontology.json fuzzy match\n(resolve_entity — query-time)\n✅ в extract_entities()"]
    end

    subgraph CP["Ingestion Control Plane"]
        EXTRACT_RE["Извлечение сущностей\nregex + ontology matching\n✅ extract_entities() в pipeline.py"]
        EXTRACT_LLM["Извлечение сущностей\nLLM JSON mode → vLLM\n🔲 TBD (ADR-013)"]
    end

    subgraph DP["Data Plane"]
        EMB["Embedding Service\nnomic-embed-text / mock\n✅ embed_batch() — 1 HTTP round-trip"]
        QD[("Qdrant\nvector + payload\n✅ collection: chunks")]
        N4J[("Neo4j\nDocument · Section · Concept\nHAS_SECTION · REFERENCES\n✅ 5 batch UNWIND queries")]
    end

    subgraph OBS["Observability"]
        PROM["Prometheus\nrequest metrics\n✅ prometheus-fastapi-instrumentator"]
        LF["Langfuse\nCallbackHandler\n✅ если LANGFUSE_* env set"]
    end

    DOC_MD -->|"POST /ingest\n(manager+ role required)"| META
    DOC_OTHER -->|"🔲 TBD"| META

    META --> VALID_META
    VALID_META -->|"принят"| PARSE_MD
    VALID_META -->|"🔲 TBD"| PARSE_PDF
    VALID_META -->|"🔲 TBD"| PARSE_OCR
    VALID_META -->|"🔲 TBD"| PARSE_STRUCT

    PARSE_OCR -->|"🔲 token_count < 50"| VISION
    VISION -->|"🔲 описание"| NORM

    PARSE_MD --> CHUNK
    CHUNK --> EMB
    EMB -->|"vector [768]"| QD
    CHUNK -->|"text + access_level\n+ last_updated + topics"| QD

    CHUNK --> EXTRACT_RE
    EXTRACT_RE -->|"Document, Section, Concept nodes\n+ HAS_SECTION, REFERENCES edges"| N4J

    CHUNK -->|"🔲 TBD"| EXTRACT_LLM
    EXTRACT_LLM -->|"🔲 LLM-extracted entities"| N4J

    PARSE_MD --> PROM
    EMB --> PROM
    N4J --> LF
```

## Статус реализации

| Компонент | Статус | Файл |
|---|---|---|
| Чтение .md корпуса | ✅ реализовано | `backend/ingestion/corpus_loader.py` |
| Чанкинг (500 токенов, overlap 50) | ✅ реализовано | `backend/ingestion/chunker.py` |
| Batch embeddings (1 HTTP round-trip) | ✅ реализовано | `backend/embeddings/client.py` |
| Запись в Qdrant (batch upsert) | ✅ реализовано | `backend/ingestion/storage.py` |
| Запись в Neo4j (5 UNWIND batches) | ✅ реализовано | `backend/ingestion/storage.py` |
| Извлечение сущностей (regex + ontology) | ✅ реализовано | `backend/query/pipeline.py :: extract_entities` |
| PDF / DOCX / XLSX parser | 🔲 TBD | ADR-013 |
| OCR (easyocr) | 🔲 TBD | ADR-013 |
| Vision (Qwen2.5-VL-7B) | 🔲 TBD | ADR-013 |
| LLM entity extraction (JSON mode) | 🔲 TBD | ADR-013 |
| Single-document POST /ingest | 🔲 501 Not Implemented | `backend/api/routes.py` |
