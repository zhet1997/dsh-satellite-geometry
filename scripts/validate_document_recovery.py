"""Validate real file recovery and STEP continuity against an isolated HTTP service."""
import argparse
import hashlib
import json
import time
import uuid
from pathlib import Path
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--xlsx", type=Path, required=True)
    parser.add_argument("--step", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    base = args.api_url.rstrip("/")

    def request(path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        with urlopen(Request(base + path, data=data, headers={"Content-Type": "application/json"}), timeout=60) as response:
            return json.load(response)

    def upload(path, name, content):
        boundary = "satcad-" + uuid.uuid4().hex
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
                'Content-Type: application/octet-stream\r\n\r\n').encode() + content + f"\r\n--{boundary}--\r\n".encode()
        with urlopen(Request(base + path, data=body, headers={"Content-Type": "multipart/form-data; boundary=" + boundary}), timeout=60) as response:
            assert response.status == 200
            return json.load(response)

    health = request("/health")
    assert health["version"] == "0.3.1", health
    project = request("/projects", {"name": "0.3.1资料恢复隔离验收"})
    prefix = f"/projects/{project['id']}"
    original = args.xlsx.read_bytes()
    parsed = upload(prefix + "/documents", "previously-failed-upload.xlsx", original)["document"]
    assert parsed["extractionStatus"] == "extracted"
    assert parsed["extractionMethod"] == "xlsx_empty_fill_compat"
    assert parsed["sha256"] == hashlib.sha256(original).hexdigest()
    bad_bytes = b"synthetic invalid XLSX package for recovery validation"
    bad = upload(prefix + "/documents", "unreadable-test.xlsx", bad_bytes)["document"]
    assert bad["extractionStatus"] == "needs_recovery"
    good = upload(prefix + "/documents", "requirements.txt", "壳体材料为铝".encode())["document"]
    assert good["extractionStatus"] == "extracted"
    duplicate = upload(prefix + "/documents", "duplicate.xlsx", original)
    assert duplicate["duplicate"] and duplicate["document"]["id"] == parsed["id"]
    imported = upload(prefix + "/import", args.step.name, args.step.read_bytes())
    deadline = time.monotonic() + 60
    while True:
        job = request("/jobs/" + imported["jobId"])
        if job["status"] not in {"queued", "running"}:
            break
        assert time.monotonic() < deadline, "STEP import timed out"
        time.sleep(.25)
    assert job["status"] == "completed", job
    project = request(prefix)
    assert project["components"] and len(project["documents"]) == 3
    geometry_before = [(c["id"], c["pose"]) for c in project["components"]]
    session_id = "isolated-recovery-session"
    request(prefix + "/workflow-bindings", {"sessionId": session_id, "revision": project["revision"], "skillId": request("/skills")["defaultSkillId"]})
    claim = {"sessionId": session_id, "documentIds": [bad["id"]], "requestId": "isolated-request-a", "action": "claim"}
    assert len(request(prefix + "/documents/recovery-request", claim)["documents"]) == 1
    assert request(prefix + "/documents/recovery-request", {**claim, "requestId": "isolated-request-b"})["documents"] == []
    request(prefix + "/documents/recovery-request", {**claim, "action": "submitted"})
    failed = request(prefix + f"/documents/{bad['id']}/recover", {"revision": project["revision"], "sessionId": session_id, "method": "xlsx_xml", "reason": "按原包结构恢复"})
    assert failed["document"]["extractionStatus"] == "needs_recovery"
    final = request(prefix + f"/documents/{bad['id']}/recover", {"revision": failed["revision"], "sessionId": session_id, "method": "mark_unreadable", "reason": "测试文件不是有效的XLSX，原件保留，字段未知"})
    assert final["document"]["extractionStatus"] == "unreadable" and not final["document"]["text"]
    current = request(prefix)
    assert geometry_before == [(c["id"], c["pose"]) for c in current["components"]]
    for doc, expected in ((parsed, original), (bad, bad_bytes)):
        with urlopen(base + prefix + f"/documents/{doc['id']}/file", timeout=10) as response:
            assert response.read() == expected
    assert args.xlsx.read_bytes() == original
    report = {"serviceVersion": health["version"], "projectId": project["id"], "sourceXlsxSha256": parsed["sha256"],
              "sourceXlsxBytes": len(original), "recoveredRows": len(parsed["sections"]),
              "worksheetReferences": sorted({s["reference"].split(":row:")[0] for s in parsed["sections"]}),
              "extractionMethod": parsed["extractionMethod"], "badFileRetained": True, "subsequentTextRead": True,
              "stepAfterBadDocument": job["status"], "componentCount": len(current["components"]),
              "geometryUnchangedByRecovery": True, "duplicateUploadDeduplicated": True,
              "duplicateAutomaticClaimRejected": True, "unrecoverableStatus": final["document"]["extractionStatus"],
              "originalBytesUnchanged": True, "passed": True}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True))


if __name__ == "__main__":
    main()
