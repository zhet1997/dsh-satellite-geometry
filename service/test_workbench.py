"""Acceptance tests for rebuildable equipment, surface STEP and isolated workflows."""
import copy
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from service import storage as db
from service.app import app, EXECUTOR
from service.geometry import import_step, read_shape, export_project, check_geometry
from service.modeling import rebuild, ensure_workbench, contact_candidates, build_recipe, selected_faces, exposed_region_faces
from service.workbench import Recipe

FIXTURE = Path(__file__).resolve().parents[1] / "validation" / "fixtures" / "contact.step"


def recipe(representation="solid"):
    return Recipe.model_validate({"representation": representation,
        "parts": [{"id": "base", "name": "矩形底座", "kind": "box", "centerMm": [0, 0, 1], "sizeMm": [10, 10, 2]},
                  {"id": "body", "name": "圆柱主体", "kind": "cylinder", "centerMm": [0, 0, 5], "radiusMm": 3, "heightMm": 6}],
        "regions": [{"id": "mount", "name": "底座安装面", "partId": "base", "selector": "zmin"}],
        "thermal": {"thicknessMm": .8 if representation == "surface_shell" else None},
        "dimensionBasis": "验收小样例指定尺寸；非真实卫星参数"}).model_dump()


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="satcad-workbench-")
        self.previous_root = db.ROOT
        db.ROOT = Path(self.temp.name)
        p = db.new_project("热工作台验收")
        job = db.new_job(p["id"], "fixture")
        self.project = ensure_workbench(import_step(p, FIXTURE, job["id"]))
        db.save_project(self.project)
        self.http = TestClient(app)

    def tearDown(self):
        EXECUTOR.submit(lambda: None).result(timeout=30)
        db.ROOT = self.previous_root
        self.temp.cleanup()

    def wait(self, response):
        self.assertEqual(response.status_code, 200, response.text)
        job_id = response.json()["jobId"]
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            state = db.get_job(job_id)
            if state["status"] not in {"queued", "running"}:
                EXECUTOR.submit(lambda: None).result(timeout=30)
                self.assertEqual(state["status"], "completed", state)
                return db.load_project(self.project["id"])
            time.sleep(.04)
        self.fail("任务超时")

    def rebuild_http(self, p, definition, context=None):
        return self.wait(self.http.post(f"/api/projects/{p['id']}/recipes/rebuild", json={
            "revision": p["revision"], "changes": [{"componentId": p["components"][1]["id"], "recipe": definition,
            "reason": "工程师要求圆柱加矩形底座"}], **({"context": context} if context else {})}))

    def test_compound_rebuild_preserves_pose_and_exact_engineering_dimensions(self):
        p = self.rebuild_http(self.project, recipe())
        c = p["components"][1]
        self.assertEqual(c["pose"], c["originalPose"])
        local = read_shape(db.project_dir(p["id"]) / c["candidateFile"])
        self.assertAlmostEqual(local.Volume(), 200 + 3.141592653589793 * 9 * 6, places=4)
        self.assertTrue(c["outputGeometry"]["passed"])
        self.assertEqual(c["recipe"]["thermal"]["massKg"], None)
        self.assertEqual(len(c["installationRegions"][0]["faces"]), 1)

    def test_surface_shell_export_readback_contains_faces_and_no_shell_solid(self):
        p = self.rebuild_http(self.project, recipe("surface_shell"))
        c = p["components"][1]
        self.assertEqual(c["outputGeometry"]["solidCount"], 0)
        self.assertGreater(c["outputGeometry"]["areaMm2"], 0)
        exported = export_project(p, db.new_job(p["id"], "export")["id"])
        local = read_shape(db.project_dir(p["id"]) / c["candidateFile"])
        self.assertEqual(len(local.Solids()), 0)
        self.assertTrue(local.isValid())
        step = read_shape(db.artifact_path(p["id"], exported["artifacts"]["step"].split("/artifacts/")[1]))
        expected = sum(len(read_shape(db.project_dir(p["id"]) / other["sourceFile"]).Solids()) for other in p["components"] if other["id"] != c["id"])
        self.assertEqual(len(step.Solids()), expected)
        self.assertTrue(exported["lastExport"]["representationReadbackVerified"])

    def test_actual_step_readback_rejects_invalid_serialization_despite_cached_brep(self):
        from service import geometry
        def invalid_step(_shape, path):
            # Deliberately serialize an edge only, while caching a valid box BRep.
            cq = geometry.cq_module()
            path.parent.mkdir(parents=True, exist_ok=True)
            cq.exporters.export(cq.Edge.makeLine(cq.Vector(0,0,0), cq.Vector(1,0,0)), str(path), exportType="STEP")
            geometry.invalidate_shape_cache(path)
            geometry.save_brep_cache(path, _shape)
        with patch.object(geometry, "write_shape", side_effect=invalid_step):
            with self.assertRaisesRegex(ValueError, "实际 STEP 回读未通过"):
                rebuild(copy.deepcopy(self.project), [{"componentId": self.project["components"][1]["id"],
                    "recipe": recipe(), "reason": "磁盘回读必须真实"}], db.new_job(self.project["id"], "faulty-step")["id"])
        self.assertEqual(db.load_project(self.project["id"])["revision"], 0)

    def test_recipe_copy_restores_without_source_file_duplication(self):
        p = self.rebuild_http(self.project, recipe())
        cid = p["components"][1]["id"]
        saved = self.http.post(f"/api/projects/{p['id']}/components/{cid}/recipe-copies", json={"revision": p["revision"], "name": "圆柱基线"})
        self.assertEqual(saved.status_code, 200, saved.text)
        p = db.load_project(p["id"])
        altered = recipe()
        altered["parts"][1]["radiusMm"] = 2
        p = self.rebuild_http(p, altered)
        p = self.wait(self.http.post(f"/api/projects/{p['id']}/components/{cid}/recipe-copies/{saved.json()['copy']['id']}/load", json={"revision": p["revision"]}))
        self.assertEqual(p["components"][1]["recipeFingerprint"], saved.json()["copy"]["fingerprint"])
        self.assertEqual(len(list((db.project_dir(p["id"]) / "source").glob("original.step"))), 0)  # Direct fixture import shares prototypes.
        self.assertEqual(len(p["components"][1]["recipeCopies"]), 1)

    def test_skill_session_pin_is_immutable_and_two_sessions_are_independent(self):
        default = self.http.get("/api/skills").json()["defaultSkillId"]
        other = self.http.post("/api/skills", json={"label": "候选", "content": "保留圆柱", "resources": {"notes/a.md": "样例"}}).json()
        path = f"/api/projects/{self.project['id']}/workflow-bindings"
        bind = {"revision": 0, "sessionId": "test-session-a", "skillId": default}
        self.assertEqual(self.http.post(path, json=bind).status_code, 200)
        changed = self.http.post(path, json={**bind, "skillId": other["id"]})
        self.assertEqual(changed.status_code, 400)
        self.assertEqual(self.http.post(path, json={**bind, "sessionId": "test-session-b", "skillId": other["id"]}).status_code, 200)
        context = self.http.get(f"/api/projects/{self.project['id']}/context").json()
        self.assertNotEqual(context["workflowBindings"]["test-session-a"]["skillFingerprint"], context["workflowBindings"]["test-session-b"]["skillFingerprint"])

    def test_revision_and_invalid_recipe_rejected_before_work(self):
        request = {"revision": 9, "changes": [{"componentId": self.project["components"][1]["id"], "recipe": recipe(), "reason": "测试"}]}
        self.assertEqual(self.http.post(f"/api/projects/{self.project['id']}/recipes/rebuild", json=request).status_code, 409)
        request["revision"] = 0
        request["changes"][0]["recipe"]["parts"][0]["sizeMm"] = [0, 1, 1]
        self.assertEqual(self.http.post(f"/api/projects/{self.project['id']}/recipes/rebuild", json=request).status_code, 422)
        self.assertNotIn("activeJobId", db.load_project(self.project["id"]))

    def test_uncertain_identity_remains_candidate_in_evidence(self):
        cid = self.project["components"][1]["id"]
        route = f"/api/projects/{self.project['id']}/identities"
        item = {"componentId": cid, "displayName": "候选陀螺仪", "basis": "配套表有相似设备，但源尺寸不符，待核实"}
        response = self.http.post(route, json={"revision": 0, "components": [item]})
        self.assertEqual(response.status_code, 200, response.text)
        saved = next(c for c in response.json()["components"] if c["id"] == cid)
        self.assertEqual(saved["nameStatus"], "candidate")
        measured = self.http.get(f"/api/projects/{self.project['id']}/evidence").json()
        self.assertEqual(next(c for c in measured["components"] if c["id"] == cid)["nameStatus"], "candidate")
        item.update(displayName="待识别单机", nameStatus="unidentified")
        response = self.http.post(route, json={"revision": 1, "components": [item]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(next(c for c in response.json()["components"] if c["id"] == cid)["nameStatus"], "unidentified")

    def test_real_feet_contact_patches_remain_geometric_candidates(self):
        p = self.project
        job = db.new_job(p["id"], "contacts")["id"]
        check_geometry(p, job)
        contact_candidates(p, job)
        device = next(c["id"] for c in p["components"] if c["name"] == "Four_foot_device")
        self.assertAlmostEqual(next(t["areaMm2"] for t in p["thermalContacts"] if device in [t["a"]["componentId"], t["b"]["componentId"]]), 36, places=4)
        self.assertTrue(all(t["status"] == "candidate" for t in p["thermalContacts"]))
        self.assertGreater(sum(len(t["patches"]) for t in p["thermalContacts"]), 0)

    def test_installation_region_clips_fused_primitive_and_rejects_buried_face(self):
        definition = recipe()
        output, parts, _ = build_recipe(self.project, self.project["components"][1], definition)
        exposed = exposed_region_faces(selected_faces(parts["base"], "zmax"), output)
        self.assertAlmostEqual(sum(face.Area() for face, _ in exposed), 100 - 3.141592653589793 * 9, places=4)
        definition["parts"][1].update(radiusMm=10, heightMm=8, centerMm=[0,0,4])
        definition["regions"][0]["selector"] = "zmax"
        output, parts, _ = build_recipe(self.project, self.project["components"][1], definition)
        self.assertEqual(exposed_region_faces(selected_faces(parts["base"], "zmax"), output), [])
        response = self.http.post(f"/api/projects/{self.project['id']}/recipes/rebuild", json={
            "revision": 0, "changes": [{"componentId": self.project["components"][1]["id"], "recipe": definition, "reason": "内部面拒绝验收"}]})
        job_id = response.json()["jobId"]
        while db.get_job(job_id)["status"] in {"queued", "running"}:
            time.sleep(.04)
        self.assertEqual(db.get_job(job_id)["status"], "failed")
        self.assertEqual(db.load_project(self.project["id"])["revision"], 0)

    def test_contact_budget_reports_unknown_patch_coverage(self):
        job = db.new_job(self.project["id"], "contacts")["id"]
        check_geometry(self.project, job)
        contact_candidates(self.project, job, max_patch_pairs=0)
        self.assertEqual(self.project["contactDiscovery"]["status"], "partial")
        self.assertTrue(all(c["patchDiscovery"]["status"] == "partial" for c in self.project["thermalContacts"]))

    def test_recipe_change_invalidates_confirmed_contact_and_requires_two_regions(self):
        p = self.rebuild_http(self.project, recipe())
        cid = p["components"][1]["id"]
        other = p["components"][0]["id"]
        value = {"id": "manual-test", "a": {"componentId": cid, "regionId": "mount"},
                 "b": {"componentId": other}, "status": "confirmed", "origin": "manual", "evidence": "工程师验收说明"}
        response = self.http.post(f"/api/projects/{p['id']}/thermal-contacts", json={"revision": p["revision"], "contacts": [value]})
        self.assertEqual(response.status_code, 400)
        value["status"] = "candidate"
        p = self.http.post(f"/api/projects/{p['id']}/thermal-contacts", json={"revision": p["revision"], "contacts": [value]}).json()
        p = self.rebuild_http(p, recipe("surface_shell"))
        contact = next(c for c in p["thermalContacts"] if c["id"] == "manual-test")
        self.assertEqual(contact["status"], "needs_review")
        self.assertEqual(contact["mappingStatus"], "needs_review")

    def test_external_flow_returns_feedback_and_unknown_fields_without_ui(self):
        sid = "external-run-a"
        skill = self.http.get("/api/skills").json()["defaultSkillId"]
        self.http.post(f"/api/projects/{self.project['id']}/workflow-bindings", json={"revision": 0, "sessionId": sid, "skillId": skill})
        p = self.rebuild_http(self.project, recipe("surface_shell"), {"sessionId": sid, "feedback": "这个计算机只建面壳"})
        self.wait(self.http.post(f"/api/projects/{p['id']}/export", json={"revision": p["revision"]}))
        result = self.http.get(f"/api/projects/{p['id']}/evidence").json()
        self.assertEqual(result["scoring"], "external")
        self.assertIn("massKg", result["components"][1]["unknownThermalFields"])
        self.assertEqual(result["feedbackRecords"][-1]["context"]["sessionId"], sid)
        self.assertFalse(result["feedbackRecords"][-1]["autoSkillUpdate"])
        self.assertEqual(self.http.get(result["artifacts"]["bundle"]).status_code, 200)


if __name__ == "__main__":
    unittest.main()
