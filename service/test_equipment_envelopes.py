"""Spec checks for explicitly requested equivalent equipment geometry."""
import copy
from unittest.mock import patch

from service.test_geometry import GeometryWorkflowTests
from service.app import EquipmentEnvelopeRebuild
from service.equipment_envelopes import rebuild_equipment_envelopes
from service.geometry import bounds, export_project, read_shape, source_local
from service import storage as db


class EquipmentEnvelopeTests(GeometryWorkflowTests):
    def test_equivalent_envelope_replaces_contact_device_keeps_pose_and_source_defects(self):
        project = copy.deepcopy(self.projects["contact"])
        device = next(c for c in project["components"] if c["name"] == "Four_foot_device")
        device["sourceTopologyValid"] = False  # Imported source evidence must survive a new representation.
        poses = {c["id"]: copy.deepcopy(c["pose"]) for c in project["components"]}
        plan = {"id": "equivalent", "operations": [
            {"componentId": c["id"], "action": "box" if c["id"] == device["id"] else "preserve",
             "reason": "measured equipment envelope; preserve surrounding structure"} for c in project["components"]]}
        project["plans"].append({"id": "equivalent", "status": "proposed"})
        request = EquipmentEnvelopeRebuild(revision=0, planId="equivalent",
                    authorization="user_requested_equivalent_envelopes", thermalContacts="separately_defined",
                    reason="User requests equivalent geometry and separate thermal links")
        result = rebuild_equipment_envelopes(project, request, plan, self.job(project))
        self.assertEqual(device["strategy"], "box")
        self.assertFalse(device["sourceTopologyValid"])
        self.assertTrue(device["outputTopologyValid"])
        self.assertEqual(device["outputFaceCount"], 6)
        self.assertEqual(poses, {c["id"]: c["pose"] for c in result["components"]})
        self.assertEqual(result["checks"]["thermalStatus"], "thermal_network_pending")
        self.assertFalse(result["checks"]["sourceComplete"])
        self.assertTrue(result["checks"]["potentialEnvelopePairs"])
        exported = export_project(result, self.job(result))
        self.assertTrue(exported["lastExport"]["stepReadbackValid"])
        self.assertFalse(exported["lastExport"]["sourceTopologyValid"])
        self.assertEqual(exported["lastExport"]["invalidSourceComponentIds"], [device["id"]])
        self.assertEqual(exported["lastExport"]["invalidPreservedComponentIds"], [])

    def test_incomplete_plan_cannot_publish_a_partial_equivalent_assembly(self):
        project = copy.deepcopy(self.projects["contact"])
        request = EquipmentEnvelopeRebuild(revision=0, planId="incomplete",
                    authorization="user_requested_equivalent_envelopes", thermalContacts="separately_defined", reason="test")
        with self.assertRaisesRegex(ValueError, "全部工作组件"):
            rebuild_equipment_envelopes(project, request, {"id": "incomplete", "operations": []}, self.job(project))
