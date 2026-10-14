"""Extract user-provided documents without invoking models or executing macros."""
from __future__ import annotations

import hashlib
import io
import logging
import posixpath
import warnings as python_warnings
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

LOGGER = logging.getLogger(__name__)
SHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
SUPPORTED_SUFFIXES = {".docx", ".xlsx", ".pdf", ".txt", ".md", ".csv", ".json"}


def recovery_methods(suffix: str) -> list[str]:
    return ["retry", *({".xlsx": ["xlsx_xml"], ".docx": ["docx_xml"]}.get(suffix, [])), "mark_unreadable"]


def document_summary(document: dict) -> dict:
    return {key: document[key] for key in ("id", "name", "sha256", "extractionStatus", "warnings",
                                           "extractionMethod", "recovery") if key in document}


def _archive(content: bytes) -> zipfile.ZipFile:
    archive = zipfile.ZipFile(io.BytesIO(content))
    if len(archive.infolist()) > 10000 or sum(info.file_size for info in archive.infolist()) > 200 * 1024 * 1024:
        archive.close()
        raise ValueError("资料解压后过大，未继续读取")
    return archive


def _compatible_xlsx(content: bytes) -> tuple[io.BytesIO, int]:
    """Repair only empty fill entries in a transient copy, retaining number formats."""
    repaired = io.BytesIO()
    with _archive(content) as archive:
        styles = ET.fromstring(archive.read("xl/styles.xml"))
        fills = styles.find(f"{{{SHEET_NS}}}fills")
        empty = [fill for fill in fills if len(fill) == 0] if fills is not None else []
        if not empty:
            raise ValueError("未发现可自动兼容的空白填充样式")
        for fill in empty:
            ET.SubElement(fill, f"{{{SHEET_NS}}}patternFill", {"patternType": "none"})
        with zipfile.ZipFile(repaired, "w", compression=zipfile.ZIP_DEFLATED) as target:
            for info in archive.infolist():
                data = ET.tostring(styles, encoding="utf-8", xml_declaration=True) if info.filename == "xl/styles.xml" else archive.read(info)
                target.writestr(info, data)
    repaired.seek(0)
    return repaired, len(empty)


def _xlsx_sections(source, warnings: list[str]) -> list[dict]:
    from openpyxl import load_workbook
    sections = []
    with python_warnings.catch_warnings(record=True) as captured:
        python_warnings.simplefilter("always")
        book = load_workbook(source, read_only=True, data_only=True)
        try:
            for sheet in book:
                # Some exporters declare enormous dimensions for a small table.
                sheet.reset_dimensions()
                for index, row in enumerate(sheet.iter_rows(values_only=True)):
                    if index >= 100000:
                        raise ValueError("工作表超过100000行，未继续读取")
                    if any(value is not None for value in row):
                        sections.append({"reference": f"sheet:{sheet.title}:row:{index + 1}",
                                         "text": " | ".join("" if x is None else str(x) for x in row)})
        finally:
            book.close()
    if any("no default style" in str(item.message) for item in captured):
        warnings.append("表格缺少默认样式，读取时使用默认显示样式；原文件未修改")
    warnings.append("公式读取缓存值；未执行电子表格公式或宏")
    return sections


def _xlsx_xml_sections(content: bytes, warnings: list[str]) -> list[dict]:
    """A bounded alternative for an agent to select; never infer formatted units/dates."""
    ns = {"s": SHEET_NS}
    sections = []
    with _archive(content) as archive:
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared = ["".join(part.text or "" for part in [*item.findall("s:t", ns), *item.findall("s:r/s:t", ns)])
                      for item in ET.fromstring(archive.read("xl/sharedStrings.xml"))]
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relationships = {rel.attrib["Id"]: rel.attrib for rel in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))}
        for sheet in workbook.findall("s:sheets/s:sheet", ns):
            rel_id = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
            rel = relationships[rel_id]
            if rel.get("TargetMode") == "External":
                raise ValueError("不读取工作表的外部链接")
            target = rel["Target"]
            path = posixpath.normpath(target.lstrip("/") if target.startswith("/") else "xl/" + target)
            if not path.startswith("xl/"):
                raise ValueError("工作表路径无效")
            root = ET.fromstring(archive.read(path))
            for index, row in enumerate(root.findall("s:sheetData/s:row", ns)):
                if index >= 100000:
                    raise ValueError("工作表超过100000行，未继续读取")
                values = []
                for cell in row.findall("s:c", ns):
                    value = cell.find("s:v", ns)
                    text = value.text if value is not None and value.text is not None else ""
                    if cell.get("t") == "s" and text:
                        text = shared[int(text)]
                    elif cell.get("t") == "inlineStr":
                        text = "".join(item.text or "" for item in cell.findall("s:is//s:t", ns))
                    elif cell.find("s:f", ns) is not None and not text:
                        text = "[公式无缓存值，保持未知]"
                    if text:
                        values.append(f"{cell.get('r', '?')}: {text}")
                if values:
                    sections.append({"reference": f"sheet:{sheet.attrib['name']}:row:{row.get('r', str(index + 1))}",
                                     "text": " | ".join(values)})
    warnings.append("通过工作表XML恢复内容；数值为原始值，未解释日期、单位或显示格式；公式仅使用缓存值")
    return sections


def _docx_xml_sections(content: bytes, warnings: list[str]) -> list[dict]:
    ns = {"w": WORD_NS}
    sections = []
    with _archive(content) as archive:
        body = ET.fromstring(archive.read("word/document.xml")).find("w:body", ns)
        if body is None:
            raise ValueError("文档缺少正文")
        for index, paragraph in enumerate(body.findall("w:p", ns)):
            text = "".join(item.text or "" for item in paragraph.findall(".//w:t", ns))
            if text.strip():
                sections.append({"reference": f"paragraph:{index + 1}", "text": text})
        for table_index, table in enumerate(body.findall("w:tbl", ns)):
            for row_index, row in enumerate(table.findall("w:tr", ns)):
                text = " | ".join("".join(item.text or "" for item in cell.findall(".//w:t", ns)) for cell in row.findall("w:tc", ns))
                if text.strip():
                    sections.append({"reference": f"table:{table_index + 1}:row:{row_index + 1}", "text": text})
    warnings.append("通过文档XML恢复正文与表格；未恢复版式，未执行宏或外部链接")
    return sections


def extract_document(path: Path, original_name: str, document_id: str, *, method: str = "auto") -> dict:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError("支持 DOCX、XLSX、PDF、TXT、MD、CSV、JSON 资料")
    if method not in {"auto", *recovery_methods(suffix)} or method == "mark_unreadable":
        raise ValueError("此资料不支持指定的读取方式")
    content = path.read_bytes()
    sections = []
    warnings = []
    attempts = []
    used_method = "native" if method in {"auto", "retry"} else method
    def failed(attempt_method, exc):
        attempts.append({"method": attempt_method, "status": "failed", "errorType": type(exc).__name__, "message": str(exc)[:500]})
        LOGGER.warning("Document %s: %s extraction failed", document_id, attempt_method, exc_info=True)
    try:
        if method == "xlsx_xml":
            sections = _xlsx_xml_sections(content, warnings)
        elif method == "docx_xml":
            sections = _docx_xml_sections(content, warnings)
        elif suffix == ".docx":
            from docx import Document
            doc = Document(io.BytesIO(content))
            sections.extend({"reference": f"paragraph:{index + 1}", "text": p.text}
                            for index, p in enumerate(doc.paragraphs) if p.text.strip())
            for table_index, table in enumerate(doc.tables):
                for row_index, row in enumerate(table.rows):
                    text = " | ".join(cell.text for cell in row.cells)
                    if text.strip():
                        sections.append({"reference": f"table:{table_index + 1}:row:{row_index + 1}", "text": text})
        elif suffix == ".xlsx":
            try:
                sections = _xlsx_sections(io.BytesIO(content), warnings)
            except Exception as exc:
                failed("native", exc)
                repaired, count = _compatible_xlsx(content)
                used_method = "xlsx_empty_fill_compat"
                sections = _xlsx_sections(repaired, warnings)
                warnings.insert(0, f"已自动兼容处理 {count} 项空白填充样式；原始资料未修改")
        elif suffix == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(content))
            for index, page in enumerate(reader.pages):
                sections.append({"reference": f"page:{index + 1}", "text": page.extract_text() or ""})
        else:
            sections.append({"reference": "file", "text": content.decode("utf-8-sig")})
        attempts.append({"method": used_method, "status": "completed"})
    except Exception as exc:
        failed(used_method if used_method != "native" or not attempts else "xlsx_empty_fill_compat", exc)
        sections = []  # A partial read must not masquerade as complete evidence.
    # A page/row reference alone is not extracted content (e.g. a scanned PDF).
    sections = [section for section in sections if section["text"].strip()]
    # Bound model-facing text while leaving original bytes and section references intact.
    text = "\n".join(f"[{item['reference']}] {item['text']}" for item in sections)
    truncated = len(text) > 500_000
    if truncated:
        warnings.append("提取文本超过500000字符，返回前500000字符；原始文件保留")
    status = "extracted" if text.strip() else "needs_recovery" if attempts[-1]["status"] == "failed" else "needs_ocr" if suffix == ".pdf" else "empty"
    if status == "needs_recovery":
        warnings.append("原始资料已保存，内容待恢复；未读取到的工程参数保持未知")
    elif status == "needs_ocr":
        warnings.append("PDF没有可提取文字，可能为扫描件；当前未进行OCR")
    elif status == "empty":
        warnings.append("资料中未提取到非空内容")
    return {"id": document_id, "name": original_name,
            "sha256": hashlib.sha256(content).hexdigest(),
            "text": text[:500_000], "sections": sections if not truncated else [],
            "extractionStatus": status, "extractionMethod": used_method,
            "diagnostics": {"attempts": attempts, "availableRecoveryMethods": recovery_methods(suffix)},
            "recovery": {"status": "pending" if status in {"needs_recovery", "needs_ocr"} else "not_needed", "automaticAttempts": 0, "toolAttempts": 0},
            "warnings": warnings, "truncated": truncated}
