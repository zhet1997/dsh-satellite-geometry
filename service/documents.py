"""Extract user-provided documents without invoking models or executing macros."""
from __future__ import annotations

import hashlib
from pathlib import Path


def extract_document(path: Path, original_name: str, document_id: str) -> dict:
    suffix = path.suffix.lower()
    sections = []
    warnings = []
    if suffix == ".docx":
        from docx import Document
        doc = Document(path)
        sections.extend({"reference": f"paragraph:{index + 1}", "text": p.text}
                        for index, p in enumerate(doc.paragraphs) if p.text.strip())
        for table_index, table in enumerate(doc.tables):
            for row_index, row in enumerate(table.rows):
                text = " | ".join(cell.text for cell in row.cells)
                if text.strip():
                    sections.append({"reference": f"table:{table_index + 1}:row:{row_index + 1}", "text": text})
    elif suffix == ".xlsx":
        from openpyxl import load_workbook
        book = load_workbook(path, read_only=True, data_only=True)
        try:
            for sheet in book:
                for index, row in enumerate(sheet.iter_rows(values_only=True)):
                    if any(value is not None for value in row):
                        sections.append({"reference": f"sheet:{sheet.title}:row:{index + 1}",
                                         "text": " | ".join("" if x is None else str(x) for x in row)})
        finally:
            book.close()
        warnings.append("公式读取缓存值；未执行电子表格公式或宏")
    elif suffix == ".pdf":
        from pypdf import PdfReader
        for index, page in enumerate(PdfReader(path).pages):
            sections.append({"reference": f"page:{index + 1}", "text": page.extract_text() or ""})
        if not any(x["text"].strip() for x in sections):
            warnings.append("PDF没有可提取文字，可能为扫描件；当前未进行OCR")
    elif suffix in {".txt", ".md", ".csv", ".json"}:
        sections.append({"reference": "file", "text": path.read_text(encoding="utf-8-sig", errors="replace")})
    else:
        raise ValueError("支持 DOCX、XLSX、PDF、TXT、MD、CSV、JSON 资料")
    # Bound model-facing text while leaving original bytes and section references intact.
    text = "\n".join(f"[{item['reference']}] {item['text']}" for item in sections)
    truncated = len(text) > 500_000
    if truncated:
        warnings.append("提取文本超过500000字符，返回前500000字符；原始文件保留")
    return {"id": document_id, "name": original_name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "text": text[:500_000], "sections": sections if not truncated else [],
            "extractionStatus": "extracted" if text.strip() else "needs_ocr",
            "warnings": warnings, "truncated": truncated}
