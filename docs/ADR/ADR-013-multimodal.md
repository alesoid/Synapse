# ADR-013: Document Preparation Pipeline — Multimodal (OCR + Vision)

**Статус:** Принято  
**Дата:** 11 мая 2026  
**Автор:** Алеся Мороз

---

## Scope

| Слой | Что реализовано | Приоритет | Статус |
|---|---|---|---|
| **Слой 1: pymupdf + easyocr** | Извлечение текста из сложных PDF, OCR отсканированных документов, парсинг таблиц | MVP — обязательно | ✅ Реализуется в первую очередь |
| **Слой 2: Qwen2.5-VL (vision)** | Описание чертежей и изображений через vision-модель — для страниц с недостаточным текстом | MVP — при наличии времени | 🔜 Добавляется поверх Слоя 1 без рефакторинга |
| **Scale** | Azure Document Intelligence / Tesseract 5 для промышленных сканов; автоматическая классификация `access_level` через LLM; коннекторы к Confluence и GitLab | Scale | 🔜 Вне скоупа MVP |

> **Важно:** Слой 2 не заменяет Слой 1 — добавляется поверх. Код Слоя 1 не переписывается при переходе к Слою 2.

---

## Контекст

Задание явно требует обработки неструктурированных данных: **сканы, чертежи, сложные PDF**. Исходное ТЗ Synapse относило мультимодальную обработку к Scale-этапу, что противоречит требованиям задания. Настоящий ADR переводит Document Preparation Pipeline в скоуп MVP.

Типы документов корпоративного корпуса и их сложность:

| Тип документа | Проблема | Решение |
|---|---|---|
| Текстовый PDF (native) | Нет проблем — текст извлекается напрямую | pymupdf (базовый случай) |
| Сложный PDF (колонки, таблицы, смешанная вёрстка) | pymupdf без настройки теряет структуру | pymupdf с `page.get_text("dict")` + структурный парсер |
| Отсканированный PDF (скан бумажного документа) | Нет машиночитаемого текста — только растровое изображение | easyocr / pytesseract поверх растеризованных страниц |
| Документ с чертежами / схемами | OCR не распознаёт смысл графических объектов | Qwen2.5-VL: vision-модель описывает изображение текстом |
| DOCX / XLSX | Структурированные форматы с таблицами | python-docx / openpyxl |

---

## Решение

### Архитектура двухслойного pipeline

```
Входящий документ (PDF / DOCX / XLSX / скан)
         │
         ▼
┌─────────────────────────────────────────────┐
│  СЛОЙ 1: Структурный парсер + OCR           │
│                                             │
│  pymupdf → извлечение текста и структуры    │
│  easyocr → OCR для отсканированных страниц  │
│  openpyxl / python-docx → таблицы и DOCX   │
└─────────────────────────────────────────────┘
         │
         ▼
    page_text, token_count
         │
         ├─ token_count >= 50 ──→ текст передаётся в Ingestion Pipeline
         │
         └─ token_count < 50  ──→ [СЛОЙ 2] Qwen2.5-VL
                                        │
                                        ▼
                               vision_description (текст)
                                        │
                                        ▼
                               передаётся в Ingestion Pipeline
         │
         ▼
┌─────────────────────────────────────────────┐
│  Ingestion Pipeline (без изменений)         │
│  chunking → embeddings → Qdrant + Neo4j     │
└─────────────────────────────────────────────┘
```

### Слой 1: pymupdf + easyocr

```python
import fitz          # pymupdf
import easyocr
from PIL import Image
import io

reader = easyocr.Reader(['ru', 'en'], gpu=False)  # CPU OCR при ingestion

def process_pdf(file_path: str) -> list[dict]:
    """Обрабатывает PDF: нативный текст или OCR для сканов."""
    doc = fitz.open(file_path)
    pages = []

    for page_num, page in enumerate(doc):
        # Попытка 1: нативный текст (работает для text-based PDF)
        text = page.get_text("text").strip()

        if len(text.split()) < 50:
            # Попытка 2: OCR (страница — скан или изображение)
            pix = page.get_pixmap(dpi=300)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            img_bytes = io.BytesIO()
            img.save(img_bytes, format="PNG")

            ocr_result = reader.readtext(img_bytes.getvalue(), detail=0)
            text = " ".join(ocr_result)

        pages.append({
            "page_num": page_num + 1,
            "text": text,
            "token_count": len(text.split()),
            "source": "native" if len(text.split()) >= 50 else "ocr"
        })

    return pages


def process_table_pdf(file_path: str) -> list[dict]:
    """Парсинг сложной вёрстки: колонки, таблицы."""
    doc = fitz.open(file_path)
    pages = []

    for page_num, page in enumerate(doc):
        # get_text("dict") сохраняет структуру блоков и строк
        blocks = page.get_text("dict")["blocks"]
        text_blocks = [
            " ".join([span["text"] for line in b.get("lines", [])
                      for span in line.get("spans", [])])
            for b in blocks if b["type"] == 0  # type 0 = text block
        ]
        text = "\n".join(text_blocks).strip()

        pages.append({
            "page_num": page_num + 1,
            "text": text,
            "token_count": len(text.split()),
            "source": "structured"
        })

    return pages
```

### Слой 2: Qwen2.5-VL (vision) — добавляется поверх Слоя 1

```python
# Слой 2 активируется только если VISION_ENABLED=true в .env
# и только для страниц где Слой 1 вернул < 50 токенов

VISION_PROMPT = """Ты технический эксперт. Опиши подробно что изображено на этом документе.
Если это чертёж — перечисли все элементы, размеры, обозначения, надписи.
Если это схема — опиши связи между элементами.
Если это таблица — воспроизведи её содержимое текстом.
Отвечай только на русском языке."""

def process_with_vision(page_image: bytes, llm_client) -> str:
    """
    Слой 2: Qwen2.5-VL описывает изображение/чертёж текстом.
    Запускается только при ingestion — не конкурирует с основной моделью за VRAM.
    """
    import base64
    image_b64 = base64.b64encode(page_image).decode()

    response = llm_client.chat.completions.create(
        model="Qwen/Qwen2.5-VL-7B-Instruct",
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
                {"type": "text", "text": VISION_PROMPT}
            ]
        }],
        max_tokens=500
    )
    return response.choices[0].message.content


def process_document(file_path: str, llm_client=None) -> list[dict]:
    """
    Единая точка входа Document Preparation Pipeline.
    Слой 2 активируется автоматически если vision_client передан.
    """
    pages = process_pdf(file_path)  # Слой 1 всегда

    vision_enabled = os.getenv("VISION_ENABLED", "false") == "true"

    if vision_enabled and llm_client:
        doc = fitz.open(file_path)
        for i, page_data in enumerate(pages):
            if page_data["token_count"] < 50:  # порог: мало текста → чертёж/скан
                pix = doc[i].get_pixmap(dpi=200)
                img_bytes = pix.tobytes("png")
                page_data["text"] = process_with_vision(img_bytes, llm_client)
                page_data["source"] = "vision"
                page_data["token_count"] = len(page_data["text"].split())

    return pages
```

### Конфигурация через env

```bash
# Слой 1 всегда активен
OCR_LANGUAGE=ru,en
OCR_DPI=300
OCR_TEXT_THRESHOLD=50        # токенов — порог для fallback на OCR/vision

# Слой 2 — активируется при наличии времени
VISION_ENABLED=false          # true для активации Qwen2.5-VL
VISION_MODEL=Qwen/Qwen2.5-VL-7B-Instruct
VISION_ENDPOINT=http://vllm:8002  # отдельный порт — не конкурирует с основной моделью
```

### Решение конфликта VRAM (T4 16GB)

Qwen2.5-14B-AWQ занимает ~12GB VRAM в inference. Qwen2.5-VL-7B потребует ещё ~5GB. На одной T4 они не поместятся вместе.

**Решение — временное разделение:** vision-модель используется **только при ingestion** (загрузке документов), а не при обработке пользовательских запросов. Ingestion запускается оператором вручную, когда система не обрабатывает запросы.

```bash
# docker-compose.yml — два профиля
# Профиль inference (всегда запущен):
vllm-main:
  image: vllm/vllm-openai:v0.4.0
  command: --model Qwen/Qwen2.5-14B-Instruct-AWQ --port 8001

# Профиль ingestion (запускается вручную: docker compose --profile ingest up):
vllm-vision:
  profiles: ["ingest"]
  image: vllm/vllm-openai:v0.4.0
  command: --model Qwen/Qwen2.5-VL-7B-Instruct --port 8002
```

---

## Альтернативы рассмотрены

| Вариант | Плюсы | Минусы | Решение |
|---|---|---|---|
| **Azure Document Intelligence** | Высокое качество для сложных документов, таблиц, рукописей | Облачный сервис — данные покидают периметр, нарушает ФЗ-152 | **Отклонён** (блокер по безопасности) |
| **Tesseract 5 (вместо easyocr)** | Зрелый OCR движок, хорошая поддержка русского | Ниже качество на рукописном тексте и низком DPI, сложнее установка | **Отклонён**, easyocr предпочтительнее для MVP |
| **LLaVA вместо Qwen2.5-VL** | Self-hosted vision модель | Хуже поддержка русского языка в описаниях | **Отклонён** |
| **Только pymupdf без OCR** | Проще реализация | Не работает для отсканированных документов — требование задания не закрыто | **Отклонён** |
| **Unstructured.io** | Универсальный парсер всех форматов | Облачная версия нарушает on-premise; self-hosted версия тяжелее стека | **Отклонён для MVP** |

---

## Trade-offs

**Плюсы двухслойного подхода:**
- Слой 1 закрывает требование задания минимальными средствами за 2-3 дня
- Слой 2 добавляется поверх без рефакторинга — `VISION_ENABLED=true` в .env
- Разделение ingestion/inference по времени решает проблему VRAM без дополнительного железа
- easyocr поддерживает русский и английский из коробки, GPU не обязателен для OCR

**Минусы:**
- easyocr на CPU медленный (~5-15 сек на страницу) — для демо достаточно, для production нужен GPU OCR
- Порог 50 токенов для определения «страница с чертежом» — эвристика, может ошибаться
- Vision-модель запускается отдельно от основной — усложняет docker-compose конфигурацию
- Ingestion с vision нельзя запускать одновременно с inference на одной T4

---

## Последствия

- Document Preparation Pipeline реализован в `/backend/ingestion/document_processor.py`
- Новые зависимости: `pymupdf`, `easyocr`, `Pillow` — добавляются в `requirements.txt`
- Метаданные чанка расширяются полем `source`: `native` / `ocr` / `vision` — для аудита качества извлечения
- Langfuse трейс ingestion логирует `source` каждой страницы — видно сколько страниц прошло через OCR/vision
- FR-10 (парсинг PDF/DOCX/XLSX) и FR-16 (ingestion форматов) выполняются полностью
- CONCEPT.md и TECHNICAL_SPEC.md требуют обновления: мультимодальная обработка переносится из Scale в MVP (Слой 1 обязательно, Слой 2 при наличии времени)

---

## Compliance & Ethics

**Регуляторное соответствие:**
- pymupdf, easyocr, Qwen2.5-VL — все компоненты работают локально, данные не покидают периметр, **ФЗ-152** соблюдён
- easyocr — лицензия Apache 2.0; pymupdf — AGPL (допустимо для внутреннего корпоративного использования); Qwen2.5-VL — Apache 2.0

**Этические риски и меры снижения:**
- Риск некачественного OCR → галлюцинации LLM на основе искажённого текста. Мера: поле `source=ocr` в метаданных чанка позволяет фильтровать низкокачественные источники; `confidence_score` учитывает `source` при расчёте актуальности
- Риск того что vision-модель неверно интерпретирует чертёж и создаёт ложные узлы в Knowledge Graph. Мера: описания от vision-модели помечаются тегом `extracted_by=vision` в Neo4j — Admin может проверить и скорректировать в Explorer режиме
- Риск извлечения PII из отсканированных документов (паспортные данные на скане). Мера: Output Guardrail проверяет текст после OCR/vision перед передачей в Ingestion Pipeline — аналогично текстовым документам (FR-27)
