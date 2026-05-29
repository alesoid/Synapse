```mermaid
flowchart TD
    subgraph SRC["Источники знаний"]
        MD["Markdown\nреализовано"]
        OTHER["PDF / DOCX / XLSX / сканы\nTBD"]
    end

    subgraph PREP["Подготовка документа"]
        MANIFEST["corpus_manifest.json\nметаданные и доступ"]
        PARSE["Парсинг документа"]
        CHUNK["Чанкинг\nтекстовые фрагменты"]
        NORM["Нормализация терминов\nontology.json"]
    end

    subgraph EXTRACT["Извлечение знаний"]
        RULES["Regex + ontology\nреализовано"]
        LLM_EXT["LLM extraction\nTBD"]
        VISION["Vision для сканов\nTBD"]
    end

    subgraph DATA["Data Plane"]
        EMB["Embedding Service"]
        QD[("Qdrant\nчанки + векторы")]
        N4J[("Neo4j\nдокументы, секции, концепты")]
    end

    subgraph OBS["Observability"]
        PROM["Prometheus"]
        LF["Langfuse"]
    end

    MD --> MANIFEST
    OTHER --> MANIFEST
    MANIFEST --> PARSE
    PARSE --> CHUNK
    CHUNK --> NORM

    CHUNK --> EMB
    EMB --> QD
    CHUNK --> QD

    NORM --> RULES
    RULES --> N4J
    CHUNK --> LLM_EXT
    LLM_EXT --> N4J
    OTHER --> VISION
    VISION --> NORM

    PARSE --> PROM
    N4J --> LF
```

## Статус реализации

| Компонент | Статус | Файл |
|---|---|---|
| Markdown corpus | реализовано | `backend/ingestion/corpus_loader.py` |
| Чанкинг | реализовано | `backend/ingestion/chunker.py` |
| Embeddings batch | реализовано | `backend/embeddings/client.py` |
| Запись в Qdrant | реализовано | `backend/ingestion/storage.py` |
| Запись в Neo4j | реализовано | `backend/ingestion/storage.py` |
| Regex + ontology extraction | реализовано | `backend/query/pipeline.py` |
| PDF / DOCX / XLSX / OCR / Vision | TBD | ADR-013 |
