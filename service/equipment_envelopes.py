"""Explicit equivalent equipment geometry; thermal links are defined separately.

This is a representation change, not the contact-preserving simplifier. Bounds
come from the immutable source import; original placement and evidence survive.
"""
from __future__ import annotations

import copy
import math

from service.storage import artifact_url, now, progress, project_dir


def rebuild_equipment_envelopes(project, request, plan, job_id):
    from service.geometry import (bounds, box_shape, broad_pairs, candidate_local,
                                  shape_transform, solid_face_coverage, write_glb,
                                  write_shape)

    components = project["components"]
    operations = {op["componentId"]: op for op in plan["operations"]}
    if set(operations) != {c["id"] for c in components}:
        raise ValueError("等效包络方案必须逐一覆盖全部工作组件")
    if any(op["action"] not in {"preserve", "box"} for op in operations.values()):
        raise ValueError("等效包络重建仅接受 preserve/box 明确方案")
    if any(c["pose"] != c["originalPose"] for c in components):
        raise ValueError("等效重建要求组件处于原始位姿；不会自动移动组件")
    old_checks = copy.deepcopy(project.get("checks", {}))
    prefix = f"candidates/r{project['revision'] + 1}"
    shapes, records = {}, []
    for index, component in enumerate(components):
        operation = operations[component["id"]]
        measured = component["localBoundsMm"]
        if len(measured) != 6 or not all(math.isfinite(v) for v in measured):
            raise ValueError(f"无有效实测局部包围尺寸：{component['id']}")
        if operation["action"] == "preserve":
            component.pop("candidateFile", None)
            component.update(strategy="original", preserved=True,
                             preservationReason=operation["reason"], geometryQuality="original",
                             simplifiedVolumeMm3=component["volumeMm3"])
            local = candidate_local(project, component)
        else:
            if any(measured[i + 3] - measured[i] <= 1e-6 for i in range(3)):
                raise ValueError(f"设备包络尺寸必须为正：{component['id']}")
            local = box_shape(measured)
            relative = f"{prefix}/{component['id']}.step"
            write_shape(local, project_dir(project["id"]) / relative)
            component.update(strategy="box", preserved=False, candidateFile=relative,
                             preservationReason=None, geometryQuality="equivalent_equipment_envelope",
                             simplifiedVolumeMm3=abs(float(local.Volume())), boxCount=1,
                             planReason=operation["reason"])
            actual = bounds(local)
            if max(abs(a - b) for a, b in zip(actual, measured)) > 1e-4:
                raise ValueError(f"包络与实测局部尺寸不一致：{component['id']}")
        coverage = solid_face_coverage(local)
        valid = bool(local.isValid())
        solids = local.Solids()
        if not valid or not coverage["completeSolidFaces"] or not solids or any(s.Volume() <= 0 for s in solids):
            raise ValueError(f"输出不是拓扑有效、闭合、正体积实体：{component['id']}")
        world = shape_transform(local, component["originalPose"])
        shapes[component["id"]] = world
        component.update(outputTopologyValid=valid, outputGeometryCoverage=coverage,
                         outputFaceCount=len(local.Faces()), outputSolidCount=len(solids),
                         candidateBoundsMm=bounds(world))
        records.append({"componentId": component["id"], "action": operation["action"],
                        "sourceLocalBoundsMm": measured, "originalPose": component["originalPose"],
                        "poseUnchanged": True, "sourceTopologyValid": component.get("sourceTopologyValid"),
                        "outputTopologyValid": valid, "outputFaceCount": len(local.Faces()),
                        "outputSolidCount": len(solids), "reason": operation["reason"]})
        progress(job_id, 2 + 60 * (index + 1) / len(components), f"重建设备等效几何 {index + 1}/{len(components)}")
    potential = [{"componentIds": [left["id"], right["id"]],
                  "meaning": "world_AABB_proximity_only_not_real_collision_or_thermal_contact"}
                 for left, right in broad_pairs(
                     [{"id": c["id"], "boundsMm": c["candidateBoundsMm"]} for c in components], 0.1)]
    project["equipmentEnvelopeRebuild"] = {
        "mode": "equivalent_equipment_envelopes", "authorization": request.authorization,
        "reason": request.reason, "thermalContacts": request.thermalContacts,
        "planId": plan["id"], "createdAt": now(), "componentRecords": records,
        "sourceBaselineChecks": old_checks, "volumeIsPhysicalMassProxy": False}
    project["purpose"] = "thermal_network_geometry"
    project["status"] = "candidate"
    project.pop("envelopeRefinement", None)
    project["checks"] = {
        "mode": "equivalent_equipment_envelopes", "sourceComplete": False,
        "envelopeComplete": False, "outputTopologyValid": True, "outputSolidCoverageComplete": True,
        "poseChangedCount": 0, "thermalStatus": "thermal_network_pending",
        "assemblyStatus": "source_collision_and_contact_checks_not_certified",
        "contacts": [], "sourceCollisions": [], "falsePositivePairs": [],
        "potentialEnvelopePairs": potential, "pairInterpretation": "AABB_candidates_only",
        "sourcePairChecksCurrent": False, "thermalContacts": "separately_defined_pending",
        "warnings": ["设备为源外形测得的等效包络；包络相交不能用作真实干涉或热接触判据",
                     "原始输入缺陷保留在源证据；输出闭合实体另行验证",
                     "材料、质量、功耗、热容、光学参数及热接触网络需另行定义；包络体积不是物理质量依据"]}
    project["summary"] = {
        "componentCount": len(components),
        "simplifiedCount": sum(c["strategy"] != "original" for c in components),
        "preservedCount": sum(c["strategy"] == "original" for c in components),
        "poseChangedCount": 0,
        "sourceFaceCount": sum(c["faceCount"] for c in components),
        "outputFaceCount": sum(c["outputFaceCount"] for c in components),
        "outputSolidCount": sum(c["outputSolidCount"] for c in components)}
    relative = f"r{project['revision'] + 1}/simplified.glb"
    write_glb(project, shapes, project_dir(project["id"]) / "artifacts" / relative,
              job_id, progress_range=(64, 98))
    project["artifacts"]["simplifiedGlb"] = artifact_url(project["id"], relative)
    for item in project["plans"]:
        if item["id"] == plan["id"]:
            item["status"] = "applied_equivalent_envelopes"
    return project
