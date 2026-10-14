"""File recovery regressions: values/provenance, durable dispatch and HTTP failures."""
from datetime import datetime
import hashlib
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

from fastapi.testclient import TestClient
from openpyxl import Workbook
from pypdf import PdfWriter

from service import storage as db
from service.app import app
from service.documents import extract_document, SHEET_NS


def workbook_bytes(*, broken_fills=False, broken_styles=False):
    book = Workbook()
    sheet = book.active
    sheet.title = "设备清单"
    sheet.append(["设备", "功耗", "日期", "计算值", "未缓存公式"])
    sheet.append(["陀螺仪", 12.5, datetime(2026, 10, 14), "=5+7", "=1+2"])
    sheet["C2"].number_format = "yyyy-mm-dd"
    book.create_sheet("备份").append(["壳体", False, 0])
    original = io.BytesIO()
    book.save(original)
    result = io.BytesIO()
    with zipfile.ZipFile(original) as archive, zipfile.ZipFile(result, "w") as target:
        for info in archive.infolist():
            content = archive.read(info)
            if info.filename == "xl/styles.xml":
                if broken_styles:
                    content = b"<invalid-styles"
                elif broken_fills:
                    root = ET.fromstring(content)
                    fills = root.find(f"{{{SHEET_NS}}}fills")
                    ET.SubElement(fills, f"{{{SHEET_NS}}}fill")
                    ET.SubElement(fills, f"{{{SHEET_NS}}}fill")
                    fills.set("count", str(len(fills)))
                    content = ET.tostring(root)
            elif info.filename == "xl/worksheets/sheet1.xml":
                root = ET.fromstring(content)
                cell = root.find(f".//{{{SHEET_NS}}}c[@r='D2']")
                cell.find(f"{{{SHEET_NS}}}v").text = "12"
                content = ET.tostring(root)
            target.writestr(info, content)
    return result.getvalue()


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="document-extraction-")
        self.folder = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def extract(self, data, name="example.xlsx", **kwargs):
        path = self.folder / name
        path.write_bytes(data)
        result = extract_document(path, name, "testdoc", **kwargs)
        self.assertEqual(path.read_bytes(), data)
        self.assertEqual(result["sha256"], hashlib.sha256(data).hexdigest())
        return result

    def test_compatibility_preserves_dates_cached_formulas_values_and_source_references(self):
        normal = self.extract(workbook_bytes())
        repaired = self.extract(workbook_bytes(broken_fills=True))
        self.assertEqual(normal["extractionStatus"], "extracted")
        self.assertEqual(normal["extractionMethod"], "native")
        self.assertEqual(repaired["extractionMethod"], "xlsx_empty_fill_compat")
        self.assertEqual(normal["sections"], repaired["sections"])
        self.assertIn("2026-10-14", repaired["text"])
        self.assertIn("12.5", repaired["text"])
        self.assertIn("False | 0", repaired["text"])
        self.assertNotIn("=5+7", repaired["text"])
        self.assertEqual(repaired["sections"][1]["reference"], "sheet:设备清单:row:2")
        self.assertTrue(any("2 项" in warning for warning in repaired["warnings"]))

    def test_corrupt_file_is_retained_without_partial_text(self):
        result = self.extract(b"not a spreadsheet")
        self.assertEqual(result["extractionStatus"], "needs_recovery")
        self.assertEqual(result["text"], "")
        self.assertEqual(result["sections"], [])
        self.assertIn("xlsx_xml", result["diagnostics"]["availableRecoveryMethods"])

    def test_xml_recovery_reads_original_cells_without_inferring_dates_or_missing_formulas(self):
        data = workbook_bytes(broken_styles=True)
        self.assertEqual(self.extract(data)["extractionStatus"], "needs_recovery")
        result = self.extract(data, method="xlsx_xml")
        self.assertEqual(result["extractionStatus"], "extracted")
        self.assertIn("B2: 12.5", result["text"])
        self.assertIn("D2: 12", result["text"])
        self.assertIn("公式无缓存值", result["text"])
        self.assertNotIn("2026-10-14", result["text"])
        self.assertTrue(any("未解释日期" in warning for warning in result["warnings"]))

    def test_docx_package_failure_can_recover_body_and_table_xml(self):
        archive = io.BytesIO()
        xml = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
               '<w:body><w:p><w:r><w:t>材料为铝</w:t></w:r></w:p><w:tbl><w:tr>'
               '<w:tc><w:p><w:r><w:t>质量</w:t></w:r></w:p></w:tc>'
               '<w:tc><w:p><w:r><w:t>3 kg</w:t></w:r></w:p></w:tc>'
               '</w:tr></w:tbl></w:body></w:document>')
        with zipfile.ZipFile(archive, "w") as target:
            target.writestr("word/document.xml", xml)
        data = archive.getvalue()
        self.assertEqual(self.extract(data, "manual.docx")["extractionStatus"], "needs_recovery")
        recovered = self.extract(data, "manual.docx", method="docx_xml")
        self.assertEqual(recovered["extractionStatus"], "extracted")
        self.assertIn("材料为铝", recovered["text"])
        self.assertIn("质量 | 3 kg", recovered["text"])

    def test_scanned_pdf_and_empty_text_have_distinct_honest_states(self):
        pdf = PdfWriter()
        pdf.add_blank_page(width=100, height=100)
        output = io.BytesIO()
        pdf.write(output)
        self.assertEqual(self.extract(output.getvalue(), "scan.pdf")["extractionStatus"], "needs_ocr")
        self.assertEqual(self.extract(b"", "empty.txt")["extractionStatus"], "empty")


class DocumentHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="document-http-")
        self.previous = db.ROOT
        db.ROOT = Path(self.temp.name)
        self.client = TestClient(app, raise_server_exceptions=False)
        self.project = db.new_project("资料恢复回归")
        self.project_id = self.project["id"]
        self.base = f"/api/projects/{self.project_id}"
        self.addCleanup(self.restore)

    def restore(self):
        self.client.close()
        db.ROOT = self.previous
        self.temp.cleanup()

    def upload(self, data, name="example.xlsx"):
        response = self.client.post(f"{self.base}/documents", files={"file": (name, data)})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def bind(self, session="session-a"):
        project = self.client.get(self.base).json()
        skill_id = self.client.get("/api/skills").json()["defaultSkillId"]
        response = self.client.post(f"{self.base}/workflow-bindings", json={"sessionId": session, "revision": project["revision"], "skillId": skill_id})
        self.assertEqual(response.status_code, 200, response.text)

    def claim(self, document_ids, request_id="request-a", action="claim"):
        return self.client.post(f"{self.base}/documents/recovery-request", json={"sessionId":"session-a", "requestId":request_id, "documentIds":document_ids, "action":action})

    def test_bad_file_does_not_block_other_uploads_and_original_is_downloadable(self):
        bad = self.upload(b"not a spreadsheet")
        self.assertEqual(bad["document"]["extractionStatus"], "needs_recovery")
        doc_id = bad["document"]["id"]
        self.assertEqual(self.client.get(f"{self.base}/documents/{doc_id}/file").content, b"not a spreadsheet")
        good = self.upload("壳体材料为铝".encode(), "requirements.txt")
        self.assertEqual(good["document"]["extractionStatus"], "extracted")
        self.assertEqual(len(self.client.get(self.base).json()["documents"]), 2)
        duplicate = self.upload(b"not a spreadsheet", "renamed.xlsx")
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(duplicate["revision"], good["revision"])
        self.assertEqual(duplicate["document"]["id"], doc_id)

    def test_claim_survives_reload_and_recovery_is_bound_bounded_and_honest(self):
        doc = self.upload(b"not a spreadsheet")["document"]
        self.bind()
        response = self.claim([doc["id"]])
        self.assertEqual(len(response.json()["documents"]), 1)
        self.assertEqual(self.claim([doc["id"]], "request-b").json()["documents"], [])
        self.assertEqual(self.claim([doc["id"]], action="submitted").status_code, 200)
        self.assertEqual(self.client.get(self.base).json()["documents"][0]["recovery"]["status"], "queued")
        route = f"{self.base}/documents/{doc['id']}/recover"
        wrong = self.client.post(route, json={"revision":1,"method":"retry","sessionId":"wrong-session"})
        self.assertEqual(wrong.status_code,400)
        for revision in (1, 2):
            result = self.client.post(route,json={"revision":revision,"method":"retry","sessionId":"session-a"})
            self.assertEqual(result.status_code,200,result.text)
            self.assertEqual(result.json()["document"]["extractionStatus"],"needs_recovery")
        self.assertEqual(self.client.post(route,json={"revision":3,"method":"retry","sessionId":"session-a"}).status_code,400)
        result = self.client.post(route,json={"revision":3,"method":"mark_unreadable","sessionId":"session-a","reason":"文件不是可读取的XLSX"})
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()["document"]["extractionStatus"],"unreadable")
        self.assertEqual(result.json()["document"]["text"],"")
        self.assertEqual(self.claim([doc["id"]],"request-c").json()["documents"],[])

    def test_xml_recovery_keeps_hash_and_rejects_invented_document_text(self):
        data = workbook_bytes(broken_styles=True)
        doc = self.upload(data)["document"]
        self.bind()
        self.claim([doc["id"]])
        route = f"{self.base}/documents/{doc['id']}/recover"
        invented = self.client.post(route,json={"revision":1,"method":"xlsx_xml","sessionId":"session-a","text":"质量99kg"})
        self.assertEqual(invented.status_code,422)
        result = self.client.post(route,json={"revision":1,"method":"xlsx_xml","sessionId":"session-a","reason":"原始XML读取"})
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()["document"]["sha256"],doc["sha256"])
        self.assertEqual(result.json()["document"]["extractionStatus"],"extracted")
        self.assertEqual(result.json()["document"]["recovery"]["status"],"resolved")
        self.assertEqual(self.client.get(f"{self.base}/documents/{doc['id']}/file").content,data)

    def test_invalid_batch_does_not_consume_a_valid_documents_automatic_attempt(self):
        doc = self.upload(b"not a spreadsheet")["document"]
        self.bind()
        self.assertEqual(self.claim([doc["id"], "missing"]).status_code,404)
        state = self.client.get(f"{self.base}/documents/{doc['id']}").json()
        self.assertEqual(state["recovery"]["automaticAttempts"],0)

    def test_unexpected_server_failure_still_returns_json(self):
        with patch("service.app.extract_document",side_effect=RuntimeError("synthetic unexpected failure")):
            response = self.client.post(f"{self.base}/documents",files={"file":("notes.txt",b"content")})
        self.assertEqual(response.status_code,500)
        self.assertIn("detail",response.json())
        self.assertNotIn("synthetic unexpected failure",response.text)


if __name__ == "__main__":
    unittest.main()
