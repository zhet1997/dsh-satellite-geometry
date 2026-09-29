"""Exercise the actual public HTTP workflow and save verifiable evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("case", type=Path)
    parser.add_argument("--url", default="http://127.0.0.1:8787")
    parser.add_argument("--name", default="HTTP end-to-end validation")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--documents", action="store_true")
    parser.add_argument("--existing-project", help="Resume validation of an already imported project")
    parser.add_argument("--export-only", action="store_true", help="Revalidate export of an existing completed simplification")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    evidence = {"case": str(args.case), "url": args.url, "name": args.name, "jobs": [], "assertions": []}
    started = time.monotonic()
    client = httpx.Client(base_url=args.url, timeout=300, trust_env=False)

    def persist():
        evidence["elapsedSeconds"] = round(time.monotonic() - started, 2)
        (args.output / "http-validation.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")

    def request(method, path, **kwargs):
        response = client.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json()

    def wait_job(submission):
        job_id = submission["jobId"]
        checkpoint = time.monotonic()
        previous = None
        while time.monotonic() - checkpoint < 3600:
            result = request("GET", f"/api/jobs/{job_id}")
            state = result["status"], result.get("message")
            if state != previous:
                print(json.dumps({"jobId": job_id, "status": state[0], "message": state[1], "progress": result.get("progress")}, ensure_ascii=False), flush=True)
                previous = state
            if result["status"] in {"completed", "failed", "cancelled"}:
                evidence["jobs"].append(result)
                persist()
                assert result["status"] == "completed", result
                return result
            time.sleep(1)
        raise TimeoutError(f"Job {job_id} exceeded one-hour validation limit")

    try:
        evidence["health"] = request("GET", "/api/health")
        project = (request("GET", "/api/projects/" + args.existing_project) if args.existing_project
                   else request("POST", "/api/projects", json={"name": args.name}))
        project_id = evidence["projectId"] = project["id"]
        base = f"/api/projects/{project_id}"
        persist()
        if not args.existing_project:
            with args.case.open("rb") as handle:
                wait_job(request("POST", base + "/import", files={"file": (args.case.name, handle, "application/step")}))
        project = request("GET", base)
        before = {item["id"]: item["pose"] for item in project["components"]}
        evidence["import"] = {"revision": project["revision"], "componentCount": len(before), "treeNodeCount": len(project["tree"]), "source": project.get("source"), "reusedExistingImport": bool(args.existing_project)}
        assert before, "No components imported"
        assert len(before) == len(project["components"]), "Duplicate component IDs"
        if args.documents:
            evidence["documents"] = []
            for path in sorted(args.case.parent.iterdir()):
                if path.suffix.lower() not in {".docx", ".xlsx", ".pdf", ".txt"}:
                    continue
                if any(d["name"] == path.name for d in project.get("documents", [])):
                    continue
                with path.open("rb") as handle:
                    document = request("POST", base + "/documents", files={"file": (path.name, handle)})
                evidence["documents"].append(document)
            project = request("GET", base)
        if args.export_only:
            assert args.existing_project, "--export-only requires --existing-project"
            assert project.get("summary"), "No completed simplification to export"
            evidence["reusedCompletedSimplification"] = True
        else:
            wait_job(request("POST", base + "/simplify", json={"revision": project["revision"], "purpose": "thermal", "strategy": "conservative", "preserveContacts": True}))
        project = request("GET", base)
        after = {item["id"]: item["pose"] for item in project["components"]}
        assert before == after, "Default simplification changed a source pose"
        assert all(item["pose"] == item["originalPose"] for item in project["components"]), "A source pose was not retained"
        evidence["assertions"].append("all original component poses retained")
        stale = client.post(base + "/simplify", json={"revision": 0, "purpose": "thermal"})
        assert stale.status_code == 409, f"Stale revision not rejected: {stale.status_code}"
        evidence["assertions"].append("stale revision rejected with HTTP 409")
        evidence["checks"] = project["checks"]
        evidence["summary"] = project.get("summary")
        evidence["preservedCount"] = sum(c["strategy"] == "original" for c in project["components"])
        evidence["simplifiedCount"] = sum(c["strategy"] != "original" for c in project["components"])
        wait_job(request("POST", base + "/export", json={"revision": project["revision"]}))
        project = request("GET", base)
        evidence["revision"] = project["revision"]
        evidence["artifacts"] = {}
        for key in ("step", "report", "contacts", "simplifiedGlb"):
            url = project["artifacts"][key]
            target = args.output / {"step": "simplified.step", "report": "properties.json", "contacts": "contacts.json", "simplifiedGlb": "simplified.glb"}[key]
            digest = hashlib.sha256()
            with client.stream("GET", url) as response, target.open("wb") as handle:
                response.raise_for_status()
                for block in response.iter_bytes():
                    digest.update(block)
                    handle.write(block)
            evidence["artifacts"][key] = {"url": url, "path": str(target), "bytes": target.stat().st_size, "sha256": digest.hexdigest()}
        report = json.loads((args.output / "properties.json").read_text(encoding="utf-8"))
        assert report["revision"] == project["revision"], "Export references wrong project revision"
        exported = evidence["export"] = report["export"]
        assert exported.get("stepReadable") is True, "Export STEP could not be reloaded"
        assert exported.get("instanceStructureVerified") is True, "Export occurrence structure not verified"
        assert exported.get("stepOccurrenceCount") == len(project["components"]), "Export lost or duplicated components"
        assert exported["stepSha256"] == evidence["artifacts"]["step"]["sha256"], "Downloaded STEP checksum differs"
        if exported["stepReadbackValid"] is False:
            assert exported.get("sourceTopologyValid") is False, "Export introduced invalid topology from valid inputs"
            assert exported.get("invalidSourceComponentIds"), "Review export is missing source defect evidence"
            assert exported.get("warnings"), "Review export is missing user-visible warnings"
            assert exported.get("status") == "source_and_output_invalid_review_required", "Invalid geometry must be marked for review"
            evidence["assertions"].append("invalid source/output topology explicitly marked for review, not accepted as valid")
        else:
            assert exported["stepReadbackValid"] is True, "STEP topology outcome missing"
            evidence["assertions"].append("exported STEP topology readback passed")
        evidence["assertions"].extend(["export revision matches current project", "exported STEP readable with all named occurrences", "download SHA256 matches service export record"])
        if args.case.name == "contact.step":
            assert not project["checks"]["sourceCollisions"], "Fixture source must not intersect"
            foot = next(c for c in project["components"] if "Four_foot" in c["name"])
            plate = next(c for c in project["components"] if "Mounting_plate" in c["name"])
            contact = next(c for c in project["checks"]["contacts"] if set(c["componentIds"]) == {foot["id"], plate["id"]})
            assert abs(contact["contactAreaMm2"] - 36) < 1e-4, contact
            assert foot["strategy"] == "original", "Contact-bearing geometry was changed"
            evidence["assertions"].extend(["four-foot contact area is 36 mm²", "contact-bearing source geometry retained"])
        evidence["status"] = "passed"
    except BaseException as exc:
        evidence["status"] = "failed"
        evidence["error"] = f"{type(exc).__name__}: {exc}"
        persist()
        raise
    finally:
        persist()
        client.close()
    print(json.dumps({k: evidence.get(k) for k in ("status", "projectId", "elapsedSeconds", "simplifiedCount", "preservedCount", "assertions")}, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
