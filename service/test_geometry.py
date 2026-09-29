"""Behavior tests against source CAD fixtures, not implementation snapshots."""
import copy
import json
import os
import struct
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path

from service import storage as db
from service.app import Simplification
from service.geometry import bounds, box_shape, check_geometry, cq_module, exact_pair, export_project, import_step, read_shape, simplify, world_shapes, write_shape
from service import geometry

FIXTURES = Path(__file__).resolve().parents[1] / "validation" / "fixtures"


class GeometryWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory(prefix="satcad-tests-")
        cls.previous_root = db.ROOT
        db.ROOT = Path(cls.folder.name)
        cls.projects = {}
        for name in ("instances", "contact"):
            project = db.new_project(name)
            job = db.new_job(project["id"], "test_import")
            cls.projects[name] = import_step(project, FIXTURES / f"{name}.step", job["id"])

    @classmethod
    def tearDownClass(cls):
        db.ROOT = cls.previous_root
        cls.folder.cleanup()

    def job(self, project, kind="test"):
        return db.new_job(project["id"], kind)["id"]

    def test_repeated_instances_keep_nested_world_poses_and_one_prototype(self):
        project = self.projects["instances"]
        self.assertEqual(len(project["components"]), 3)
        self.assertEqual(len({c["prototypeId"] for c in project["components"]}), 1)
        boxes = [bounds(shape) for shape in world_shapes(project).values()]
        actual = [min(box[i] for box in boxes) for i in range(3)] + [max(box[i] for box in boxes) for i in range(3, 6)]
        expected = json.loads((FIXTURES / "expected.json").read_text())[1]["boundsMm"]
        for observed, wanted in zip(actual, expected):
            self.assertAlmostEqual(observed, wanted, places=5)

    def test_contacts_are_measured_on_real_feet_not_full_envelope_face(self):
        project = copy.deepcopy(self.projects["contact"])
        report = check_geometry(project, self.job(project))
        self.assertTrue(report["sourceComplete"])
        self.assertEqual(report["sourceCollisions"], [])
        device_id = next(c["id"] for c in project["components"] if c["name"] == "Four_foot_device")
        patch = next(pair for pair in report["contacts"] if device_id in pair["componentIds"])
        self.assertAlmostEqual(patch["contactAreaMm2"], 36., places=5)

    def test_source_pair_cache_reuses_geometry_but_invalidates_changed_pose(self):
        project = copy.deepcopy(self.projects["contact"])
        check_geometry(project, self.job(project))
        with patch("service.geometry.exact_pair", wraps=exact_pair) as calculate:
            report = check_geometry(project, self.job(project))
            self.assertEqual(calculate.call_count, 0)
            self.assertEqual(report["sourcePairCacheHits"], report["evaluatedPairCount"])
            device = next(c for c in project["components"] if c["name"] == "Four_foot_device")
            device["pose"]["translationMm"][2] += .5
            report = check_geometry(project, self.job(project))
            self.assertGreater(calculate.call_count, 0)
            self.assertFalse(any(device["id"] in pair["componentIds"] for pair in report["contacts"]))

    def test_box_only_overlap_is_not_reported_as_real_interference(self):
        project = copy.deepcopy(self.projects["contact"])
        before = {c["id"]: copy.deepcopy(c["pose"]) for c in project["components"]}
        result = simplify(project, Simplification(revision=0, strategy="box", purpose="envelope", preserveContacts=False), self.job(project))
        self.assertEqual(result["checks"]["sourceCollisions"], [])
        names = {c["id"]: c["name"] for c in result["components"]}
        pairs = [{names[c] for c in pair["componentIds"]} for pair in result["envelopeRefinement"]["initialFalsePositivePairs"]]
        self.assertIn({"Four_foot_device", "Between_feet_sensor"}, pairs)
        self.assertEqual(result["checks"]["falsePositivePairs"], [])
        self.assertEqual(result["envelopeRefinement"]["status"], "resolved")
        device = next(c for c in result["components"] if c["name"] == "Four_foot_device")
        self.assertEqual(device["strategy"], "multibox")
        self.assertAlmostEqual(device["simplifiedVolumeMm3"], device["volumeMm3"], places=3)
        self.assertEqual(before, {c["id"]: c["pose"] for c in result["components"]})

    def test_thermal_mode_preserves_contact_source_shapes(self):
        project = copy.deepcopy(self.projects["contact"])
        result = simplify(project, Simplification(revision=0, purpose="thermal"), self.job(project))
        device = next(c for c in result["components"] if c["name"] == "Four_foot_device")
        self.assertEqual(device["strategy"], "original")
        self.assertTrue(device["preserved"])
        self.assertEqual(result["checks"]["thermalStatus"], "passed")

    def test_failed_envelope_refinement_restores_source_without_moving(self):
        project = copy.deepcopy(self.projects["contact"])
        before = {component["id"]: copy.deepcopy(component["pose"]) for component in project["components"]}
        with patch("service.geometry.refine_envelope", side_effect=ValueError("test unreliable slice")):
            result = simplify(project, Simplification(revision=0, strategy="box", purpose="envelope", preserveContacts=False), self.job(project))
        device = next(component for component in result["components"] if component["name"] == "Four_foot_device")
        self.assertEqual(device["strategy"], "original")
        self.assertIn("细化失败", device["preservationReason"])
        self.assertEqual(result["checks"]["falsePositivePairs"], [])
        self.assertEqual(before, {component["id"]: component["pose"] for component in result["components"]})

    def test_shape_cache_cannot_reuse_a_rewritten_candidate_file(self):
        path = Path(self.folder.name) / "rewrite.step"
        write_shape(box_shape([0, 0, 0, 2, 2, 2]), path)
        importer = cq_module().importers.importStep
        with patch("cadquery.importers.importStep", wraps=importer) as load:
            self.assertAlmostEqual(read_shape(path).Volume(), 8)
            self.assertAlmostEqual(read_shape(path).Volume(), 8)
            self.assertEqual(load.call_count, 0)
            write_shape(box_shape([0, 0, 0, 3, 3, 3]), path)
            self.assertAlmostEqual(read_shape(path).Volume(), 27)
            self.assertEqual(load.call_count, 0)
        geometry._read_shape_cached.cache_clear()
        with patch("cadquery.importers.importStep", side_effect=AssertionError("cold worker should read the native cache")):
            self.assertAlmostEqual(read_shape(path).Volume(), 27)

    def test_mixed_solid_and_loose_face_cannot_pass_solid_acceptance(self):
        cq = cq_module()
        solid = box_shape([0, 0, 0, 10, 10, 10])
        loose_face = cq.Face.makePlane(5, 5, basePnt=(20, 0, 0))
        mixed = cq.Compound.makeCompound([solid, loose_face])
        self.assertTrue(mixed.isValid())
        self.assertEqual(len(mixed.Solids()), 1)
        self.assertEqual(geometry.solid_face_coverage(mixed)["nonSolidFaceCount"], 1)
        project = db.new_project("mixed solid shell")
        path = db.project_dir(project["id"]) / "mixed.step"
        write_shape(mixed, path)
        project = import_step(project, path, self.job(project))
        self.assertTrue(any(not component["sourceValid"] for component in project["components"]))
        result = simplify(project, Simplification(revision=0, purpose="envelope", preserveContacts=False), self.job(project))
        self.assertEqual(result["checks"]["assemblyStatus"], "unknown")
        self.assertTrue(all(component["strategy"] == "original" for component in result["components"] if not component["sourceValid"]))

    @unittest.skipUnless(sys.platform.startswith("linux"), "per-pair hard timeout is guaranteed on Linux")
    def test_pair_timeout_keeps_unknown_continues_other_pairs_and_reaps_child(self):
        import multiprocessing
        project = copy.deepcopy(self.projects["contact"])
        (db.project_dir(project["id"]) / "cache" / "source-pairs.json").unlink(missing_ok=True)
        native = geometry._exact_pair_in_process
        def slow_contact_pair(left, right, tolerance):
            if min(abs(float(left.Volume())), abs(float(right.Volume()))) > 1000:
                time.sleep(1)
            return native(left, right, tolerance)
        job = self.job(project)
        children_before = {child.pid for child in multiprocessing.active_children()}
        with patch.dict(os.environ, {"SATCAD_PAIR_TIMEOUT_SECONDS": ".2", "SATCAD_CHECK_BUDGET_SECONDS": "5"}):
            with patch("service.geometry._exact_pair_in_process", side_effect=slow_contact_pair):
                report = check_geometry(project, job)
            self.assertEqual(report["unknownPairCounts"]["pairTimeouts"], 1)
            self.assertEqual(report["evaluatedPairCount"], 2)
            self.assertFalse(report["sourceComplete"])
            self.assertEqual(report["assemblyStatus"], "unknown")
            self.assertEqual(report["thermalStatus"], "unknown")
            with patch("service.geometry._exact_pair_in_process", side_effect=AssertionError("same job must not retry failed or cached pairs")):
                repeated = check_geometry(project, job)
            self.assertEqual(repeated["unknownPairCounts"]["pairTimeouts"], 1)
            self.assertEqual(repeated["sourcePairCacheHits"], 2)
            retried = check_geometry(project, self.job(project))
            self.assertTrue(retried["sourceComplete"])
        self.assertEqual({child.pid for child in multiprocessing.active_children()}, children_before)

    def test_exhausted_check_budget_keeps_source_instead_of_claiming_pass(self):
        project = copy.deepcopy(self.projects["contact"])
        (db.project_dir(project["id"]) / "cache" / "source-pairs.json").unlink(missing_ok=True)
        with patch.dict(os.environ, {"SATCAD_CHECK_BUDGET_SECONDS": ".000001"}):
            result = simplify(project, Simplification(revision=0, strategy="box", purpose="envelope", preserveContacts=False), self.job(project))
        self.assertGreater(result["checks"]["unknownPairCounts"]["checkBudgetPairs"], 0)
        self.assertEqual(result["checks"]["evaluatedPairCount"], 0)
        self.assertEqual(result["checks"]["thermalStatus"], "unknown")
        self.assertEqual(result["checks"]["assemblyStatus"], "unknown")
        self.assertTrue(all(component["strategy"] == "original" for component in result["components"]))

    def test_glb_is_standard_y_up_metres_with_component_identity(self):
        project = self.projects["instances"]
        raw = (db.project_dir(project["id"]) / "artifacts" / "original.glb").read_bytes()
        magic, version, length = struct.unpack_from("<4sII", raw)
        self.assertEqual((magic, version, length), (b"glTF", 2, len(raw)))
        chunk_length, chunk_type = struct.unpack_from("<I4s", raw, 12)
        self.assertEqual(chunk_type, b"JSON")
        document = json.loads(raw[20:20 + chunk_length])
        self.assertEqual({n["extras"]["componentId"] for n in document["nodes"]}, {c["id"] for c in project["components"]})
        positions = [a for a in document["accessors"] if a["type"] == "VEC3"]
        self.assertLess(max(max(a["max"]) for a in positions), .1)

    def test_step_export_retains_instance_count_and_check_status(self):
        project = copy.deepcopy(self.projects["instances"])
        previous_status = project["checks"]["assemblyStatus"]
        result = export_project(project, self.job(project))
        self.assertTrue(result["lastExport"]["stepReadbackValid"])
        self.assertTrue(result["lastExport"]["stepReadable"])
        self.assertTrue(result["lastExport"]["sourceTopologyValid"])
        self.assertEqual(result["lastExport"]["stepOccurrenceCount"], 3)
        self.assertEqual(result["lastExport"]["stepPrototypeCount"], 1)
        self.assertEqual(result["checks"]["assemblyStatus"], previous_status)
        properties = db.read_json(db.project_dir(project["id"]) / "artifacts" / "r0" / "properties.json")
        self.assertEqual(len(properties["components"]), 3)
        output = read_shape(db.project_dir(project["id"]) / "artifacts" / "r0" / "simplified.step")
        expected = json.loads((FIXTURES / "expected.json").read_text())[1]["boundsMm"]
        for observed, wanted in zip(bounds(output), expected):
            self.assertAlmostEqual(observed, wanted, places=5)

    def test_new_export_topology_failure_from_valid_inputs_is_not_published(self):
        project = copy.deepcopy(self.projects["instances"])
        native_read = geometry.read_shape
        def failed_readback(path):
            if Path(path).name == "simplified.step":
                # Model an OCCT serialization/readback failure while retaining
                # genuinely valid input fixtures. Source-defect allowance must
                # not silently turn this newly introduced failure into success.
                return SimpleNamespace(isValid=lambda: False)
            return native_read(path)
        with patch("service.geometry.read_shape", side_effect=failed_readback):
            with self.assertRaisesRegex(ValueError, "新的拓扑检查失败"):
                export_project(project, self.job(project))
        self.assertNotIn("bundle", project["artifacts"])
        self.assertNotIn("lastExport", project)


if __name__ == "__main__":
    unittest.main()
