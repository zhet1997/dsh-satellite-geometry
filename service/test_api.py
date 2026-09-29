"""Public operation tests for constraints, provenance and semantic assemblies."""
import copy
import io
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from fastapi import HTTPException, UploadFile

from service import storage as db
from service.app import (EXECUTOR, ComponentMetadata, Metadata, MotionConstraints, PoseChange, Restore,
                         SemanticOperation, Semantics, SourceReference, update_metadata,
                         update_pose, update_semantics, restore_component, cancel_job, submit, health, import_model)
from service.geometry import check_geometry, export_project, import_step

FIXTURES = Path(__file__).resolve().parents[1] / "validation" / "fixtures"


class ApiBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="satcad-api-tests-")
        cls.previous = db.ROOT
        db.ROOT = Path(cls.temp.name)
        cls.imports = {}
        for name in ("instances", "contact"):
            project = db.new_project(name)
            job = db.new_job(project["id"], "test")
            cls.imports[name] = import_step(project, FIXTURES / f"{name}.step", job["id"])

    @classmethod
    def tearDownClass(cls):
        EXECUTOR.submit(lambda: None).result(timeout=30)
        db.ROOT = cls.previous
        cls.temp.cleanup()

    def project(self, name):
        project = copy.deepcopy(self.imports[name])
        return db.save_project(project)

    def wait(self, response):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            job = db.get_job(response["jobId"])
            if job["status"] not in {"queued", "running"}:
                # A worker can finish before its supervising thread reaps it.
                # Drain the serial executor before a test swaps the data root.
                EXECUTOR.submit(lambda: None).result(timeout=30)
                return db.get_job(response["jobId"])
            time.sleep(.05)
        self.fail("test geometry job timed out")

    def test_move_requires_explicit_constraints_and_rejects_forbidden_axis(self):
        project = self.project("instances")
        component = project["components"][0]
        pose = copy.deepcopy(component["pose"])
        pose["translationMm"][0] += 1
        request = PoseChange(revision=0, **pose, reason="test", authorization="user_requested")
        with self.assertRaisesRegex(ValueError, "缺少明确移动约束"):
            update_pose(project["id"], component["id"], request)
        project = update_metadata(project["id"], Metadata(revision=0, components=[ComponentMetadata(id=component["id"], motionConstraints=MotionConstraints(allowedTranslationAxes=["Z"], maxTranslationMm=2, reason="只允许Z"))]))
        with self.assertRaisesRegex(ValueError, "未允许沿世界 X"):
            update_pose(project["id"], component["id"], request.model_copy(update={"revision": project["revision"]}))

    def test_permitted_pose_change_and_original_pose_restore(self):
        project = self.project("instances")
        component = project["components"][0]
        original = copy.deepcopy(component["pose"])
        project = update_metadata(project["id"], Metadata(revision=0, components=[ComponentMetadata(id=component["id"], motionConstraints=MotionConstraints(allowedTranslationAxes=["X"], maxTranslationMm=2, reason="允许小范围沿X调整"))]))
        pose = copy.deepcopy(original)
        pose["translationMm"][0] += 1
        job = self.wait(update_pose(project["id"], component["id"], PoseChange(revision=1, **pose, reason="明确布局微调", authorization="user_requested")))
        self.assertEqual(job["status"], "completed", job.get("error"))
        current = db.load_project(project["id"])
        changed = next(c for c in current["components"] if c["id"] == component["id"])
        self.assertEqual(changed["originalPose"], original)
        self.assertEqual(changed["pose"], pose)
        self.assertEqual(changed["poseChange"]["rotationDeltaDeg"], 0.)
        job = self.wait(restore_component(project["id"], component["id"], Restore(revision=current["revision"])))
        self.assertEqual(job["status"], "completed", job.get("error"))
        self.assertEqual(next(c for c in db.load_project(project["id"])["components"] if c["id"] == component["id"])["pose"], original)

    def test_contact_breaking_pose_is_rejected_without_changing_model(self):
        project = self.project("contact")
        component = next(c for c in project["components"] if c["name"] == "Four_foot_device")
        original = copy.deepcopy(component["pose"])
        project = update_metadata(project["id"], Metadata(revision=0, components=[ComponentMetadata(id=component["id"], motionConstraints=MotionConstraints(allowedTranslationAxes=["Z"], maxTranslationMm=2, reason="验证接触保护"))]))
        moved = copy.deepcopy(original)
        moved["translationMm"][2] += 1
        job = self.wait(update_pose(project["id"], component["id"], PoseChange(revision=1, **moved, reason="测试接触保护", authorization="user_requested")))
        self.assertEqual(job["status"], "failed")
        self.assertIn("接触关系", job["error"])
        current = db.load_project(project["id"])
        self.assertEqual(current["revision"], 1)
        self.assertEqual(next(c for c in current["components"] if c["id"] == component["id"])["pose"], original)

    def test_group_is_present_in_step_and_original_tree_is_preserved(self):
        project = self.project("instances")
        original_tree = copy.deepcopy(project["sourceTree"])
        ids = [c["id"] for c in project["components"][:2]]
        project = update_semantics(project["id"], Semantics(revision=0, operations=[SemanticOperation(action="group", componentIds=ids, name="ReviewGroup", reason="功能组整理")]))
        self.assertEqual(project["sourceTree"], original_tree)
        project = export_project(project, db.new_job(project["id"], "export_test")["id"])
        exported_path = db.project_dir(project["id"]) / "artifacts" / "r1" / "simplified.step"
        imported = db.new_project("roundtrip")
        imported = import_step(imported, exported_path, db.new_job(imported["id"], "roundtrip")["id"])
        self.assertEqual(len(imported["components"]), 3)
        self.assertTrue(any("ReviewGroup" in n["name"] and n["children"] for n in imported["tree"]))

    def test_false_document_quote_cannot_be_recorded_as_provenance(self):
        project = self.project("instances")
        document = {"id": "testdoc", "name": "requirements.txt", "text": "器件质量为 3 kg"}
        db.atomic_json(db.project_dir(project["id"]) / "documents" / "testdoc.parsed.json", document)
        with self.assertRaisesRegex(ValueError, "引用文字不在资料"):
            update_metadata(project["id"], Metadata(revision=0, components=[ComponentMetadata(id=project["components"][0]["id"], massKg=99, sources=[SourceReference(documentId="testdoc", quote="质量为99kg", field="massKg")])]))
        self.assertEqual(db.load_project(project["id"])["revision"], 0)

    def test_regroup_and_ungroup_restore_existing_parents_without_losing_components(self):
        project = self.project("instances")
        ids = [component["id"] for component in project["components"]]
        project = update_semantics(project["id"], Semantics(revision=0, operations=[SemanticOperation(action="group", componentIds=ids[:2], name="G1", reason="first")]))
        first = next(node["id"] for node in project["tree"] if node.get("semanticGroup"))
        project = update_semantics(project["id"], Semantics(revision=1, operations=[SemanticOperation(action="group", componentIds=[ids[0], ids[2]], name="G2", reason="second")]))
        second = next(node["id"] for node in project["tree"] if node.get("semanticGroup") and node["id"] != first)
        project = update_semantics(project["id"], Semantics(revision=2, operations=[SemanticOperation(action="ungroup", groupId=first, reason="remove old"), SemanticOperation(action="ungroup", groupId=second, reason="restore")]))
        tree = {node["id"]: node for node in project["tree"]}
        for component_id in ids:
            parent_id = tree[component_id]["parentId"]
            self.assertTrue(parent_id is None or parent_id in tree)
            if parent_id:
                self.assertEqual(tree[parent_id]["children"].count(component_id), 1)
        self.assertEqual(project["sourceTree"], self.imports["instances"]["sourceTree"])

    def test_upload_does_not_overwrite_source_reserved_during_transfer(self):
        project = db.new_project("concurrent import")
        source = db.project_dir(project["id"]) / "source" / "original.step"
        class InterleavedUpload(io.BytesIO):
            def read(self, size=-1):
                if self.tell() == 0:
                    current = db.load_project(project["id"])
                    current["activeJobId"] = "other_import"
                    db.save_project(current)
                    source.write_bytes(b"source reserved by the first import")
                return super().read(size)
        file = UploadFile(filename="candidate.step", file=InterleavedUpload(b"a different incoming step"))
        with self.assertRaises(HTTPException) as caught:
            import_model(project["id"], file)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(source.read_bytes(), b"source reserved by the first import")
        self.assertEqual(list(source.parent.glob(".upload-*")), [])

    def test_automatic_collision_repair_rejects_a_worse_existing_interference(self):
        project = self.project("contact")
        sensor = next(component for component in project["components"] if component["name"] == "Between_feet_sensor")
        sensor["pose"]["translationMm"][2] -= 1
        sensor["metadata"]["motionConstraints"] = MotionConstraints(allowedTranslationAxes=["Z"], maxTranslationMm=2, preserveContacts=False, reason="test permitted repair").model_dump()
        check_geometry(project, db.new_job(project["id"], "baseline")["id"])
        self.assertTrue(any(sensor["id"] in pair["componentIds"] for pair in project["checks"]["sourceCollisions"]))
        db.save_project(project)
        worse = copy.deepcopy(sensor["pose"])
        worse["translationMm"][2] -= .5
        result = self.wait(update_pose(project["id"], sensor["id"], PoseChange(revision=0, **worse, reason="try collision repair", authorization="verified_source_collision")))
        self.assertEqual(result["status"], "failed", result.get("error"))
        self.assertIn("加重已有干涉", result["error"])
        self.assertEqual(db.load_project(project["id"])["revision"], 0)

    def test_running_cad_worker_can_be_cancelled_without_committing(self):
        project = db.new_project("cancel import")
        destination = db.project_dir(project["id"]) / "source" / "original.step"
        destination.parent.mkdir(parents=True)
        shutil.copyfile(FIXTURES / "contact.step", destination)
        response = submit(project, "import", {"originalName": "contact.step"})
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            state = db.get_job(response["jobId"])
            if state.get("workerPid"):
                break
            time.sleep(.01)
        self.assertIn("workerPid", state)
        self.assertEqual(health()["status"], "ok")
        cancel_job(response["jobId"])
        result = self.wait(response)
        self.assertEqual(result["status"], "cancelled", result.get("error"))
        self.assertEqual(db.load_project(project["id"])["revision"], 0)
        self.assertNotIn("activeJobId", db.load_project(project["id"]))
        if os.name != "nt":
            with self.assertRaises(ProcessLookupError):
                os.kill(state["workerPid"], 0)

    def test_document_values_require_field_evidence_including_false_flags(self):
        project = self.project("instances")
        component_id = project["components"][0]["id"]
        document = {"id": "testdoc", "name": "requirements.txt", "text": "质量 3 kg，功耗 7 W"}
        db.atomic_json(db.project_dir(project["id"]) / "documents" / "testdoc.parsed.json", document)
        with self.assertRaisesRegex(ValueError, "fixed"):
            update_metadata(project["id"], Metadata(revision=0, components=[ComponentMetadata(id=component_id, origin="document", fixed=False)]))
        with self.assertRaisesRegex(ValueError, "powerW"):
            update_metadata(project["id"], Metadata(revision=0, components=[ComponentMetadata(id=component_id, origin="document", massKg=3, powerW=7, sources=[SourceReference(documentId="testdoc", quote="质量 3 kg", field="massKg")])]))
        self.assertEqual(db.load_project(project["id"])["revision"], 0)

    def test_manual_change_removes_only_its_old_document_reference(self):
        project = self.project("instances")
        component_id = project["components"][0]["id"]
        document = {"id": "testdoc", "name": "requirements.txt", "text": "质量 3 kg，功耗 7 W"}
        db.atomic_json(db.project_dir(project["id"]) / "documents" / "testdoc.parsed.json", document)
        update_metadata(project["id"], Metadata(revision=0, components=[ComponentMetadata(id=component_id, origin="document", massKg=3, powerW=7, sources=[SourceReference(documentId="testdoc", quote="质量 3 kg", field="massKg"), SourceReference(documentId="testdoc", quote="功耗 7 W", field="powerW")])]))
        project = update_metadata(project["id"], Metadata(revision=1, components=[ComponentMetadata(id=component_id, origin="manual", changedFields=["massKg"], massKg=4)]))
        metadata = next(c["metadata"] for c in project["components"] if c["id"] == component_id)
        self.assertEqual(metadata["massKg"], 4)
        self.assertEqual(metadata["powerW"], 7)
        self.assertEqual(metadata["provenance"]["massKg"]["origin"], "manual")
        self.assertEqual(metadata["provenance"]["powerW"]["origin"], "document")
        self.assertEqual([ref["field"] for ref in metadata["sources"]], ["powerW"])
        project = update_metadata(project["id"], Metadata(revision=2, components=[ComponentMetadata(id=component_id, origin="manual", changedFields=["massKg"], massKg=None)]))
        metadata = next(c["metadata"] for c in project["components"] if c["id"] == component_id)
        self.assertNotIn("massKg", metadata)
        self.assertEqual(metadata["provenance"]["massKg"]["state"], "unknown")


if __name__ == "__main__":
    unittest.main()
