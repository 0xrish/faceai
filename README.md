# EasyOCR Text Extractor — Apify Actor

Extract text from **images and PDFs** using [EasyOCR](https://github.com/JaidedAI/EasyOCR).  
Supports **80+ languages**, multi-page PDFs, and outputs a rich structured dataset with per-page blocks, bounding boxes, and confidence scores.

---

## Supported Input Formats

| Format | Extensions |
|--------|-----------|
| Images | `.jpg` `.jpeg` `.png` `.bmp` `.tiff` `.tif` `.webp` `.gif` |
| Documents | `.pdf` (each page rendered at 200 DPI) |

---

## Input

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `fileUrls` | `string[]` | `[]` | Public URLs of images or PDFs |
| `base64Files` | `object[]` | `[]` | Base64-encoded files `[{filename, data}]` |
| `languages` | `string[]` | `["en"]` | EasyOCR language codes (e.g. `["en","hi","fr"]`) |
| `gpu` | `boolean` | `false` | Enable GPU acceleration |

### Example input (JSON)

```json
{
  "fileUrls": [
    "https://example.com/invoice.pdf",
    "https://example.com/scan.jpg"
  ],
  "languages": ["en"],
  "gpu": false
}
```

### base64Files format

```json
{
  "base64Files": [
    {
      "filename": "receipt.png",
      "data": "data:image/png;base64,iVBORw0KGgo..."
    }
  ]
}
```

---

## Output Dataset Structure

Each file processed produces **one dataset item**:

```json
{
  "source_file": "invoice.pdf",
  "file_type": "pdf",
  "total_pages": 3,
  "languages_used": ["en"],
  "combined_text": "Full text across all pages...",
  "total_word_count": 412,
  "pages": [
    {
      "page_number": 1,
      "full_text": "INVOICE #1042 ...",
      "word_count": 138,
      "blocks": [
        {
          "text": "INVOICE #1042",
          "confidence": 0.9871,
          "bounding_box": {
            "top_left": [42, 18],
            "top_right": [310, 18],
            "bottom_right": [310, 52],
            "bottom_left": [42, 52]
          }
        }
      ]
    }
  ]
}
```

---

## Supported Languages

EasyOCR supports 80+ scripts. Pass the language code(s) in the `languages` array.  
Full list: https://www.jaided.ai/easyocr/

Common codes: `en`, `hi`, `zh_sim`, `zh_tra`, `ar`, `fr`, `de`, `ja`, `ko`, `ru`, `es`, `pt`

---

## Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run with Apify CLI
apify run --input '{"fileUrls": ["https://example.com/sample.jpg"], "languages": ["en"]}'
```

---

## Notes

- First run downloads EasyOCR model weights (~100 MB for English). Subsequent runs use cache.
- GPU mode requires a GPU-enabled Apify actor plan and CUDA-enabled torch install.
- PDF pages are rendered at 200 DPI for best OCR accuracy.