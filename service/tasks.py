"""Serializable task dispatch, executed only inside an isolated CAD process."""
from __future__ import annotations

import copy

from service import storage as db


def execute(kind: str, project: dict, payload: dict, job_id: str) -> dict:
    from service.geometry import (bounds, check_geometry, export_project, import_step,
                                  simplify, world_shapes, write_glb)
    from service.app import Simplification

    if kind == "import":
        path = db.project_dir(project["id"]) / "source" / "original.step"
        result = import_step(project, path, job_id)
        result["source"]["name"] = payload["originalName"]
        return result
    if kind in {"simplify", "apply_plan"}:
        previous = {c["id"]: (c.get("strategy"), c.get("candidateFile")) for c in project["components"]}
        request = Simplification.model_validate(payload["request"])
        result = simplify(project, request, job_id, payload.get("plan"))
        from service.modeling import default_recipe, fingerprint, contact_candidates, invalidate_contacts
        ids = set(request.componentIds or [c["id"] for c in result["components"]])
        ids.update(c["id"] for c in result["components"] if previous[c["id"]] != (c.get("strategy"), c.get("candidateFile")))
        for c in result["components"]:
            if c["id"] in ids:
                c["recipe"] = default_recipe(c)
                c["recipeFingerprint"] = fingerprint(c["recipe"])
                c.pop("outputRepresentation", None)
                c.pop("installationRegions", None)
                c.pop("outputGeometry", None)
        invalidate_contacts(result, ids, "关联单机已重新简化，接触区域需复核")
        contact_candidates(result, job_id)
        if kind == "apply_plan":
            for item in result["plans"]:
                if item["id"] == payload["plan"]["id"]:
                    item["status"] = "applied"
        return result
    if kind == "check":
        check_geometry(project, job_id)
        from service.modeling import contact_candidates
        contact_candidates(project, job_id)
        return project
    if kind == "recipes":
        from service.modeling import rebuild
        return rebuild(project, payload["changes"], job_id, payload.get("context"))
    if kind == "equipment_envelopes":
        from service.app import EquipmentEnvelopeRebuild
        from service.equipment_envelopes import rebuild_equipment_envelopes
        result = rebuild_equipment_envelopes(project, EquipmentEnvelopeRebuild.model_validate(payload["request"]),
                                            payload["plan"], job_id)
        from service.modeling import default_recipe, fingerprint, invalidate_contacts
        for c in result["components"]:
            c["recipe"] = default_recipe(c)
            c["recipeFingerprint"] = fingerprint(c["recipe"])
            c.pop("installationRegions", None)
            c.pop("outputRepresentation", None)
            c.pop("outputGeometry", None)
        invalidate_contacts(result, [c["id"] for c in result["components"]], "关联单机已重建等效包络，接触区域需复核")
        return result
    if kind == "export":
        return export_project(project, job_id)
    component = next(c for c in project["components"] if c["id"] == payload["componentId"])
    request = payload["request"]
    if kind == "restore":
        if request["restoreGeometry"]:
            component.pop("candidateFile", None)
            component.update(strategy="original", preserved=True, preservationReason="用户要求保留原几何",
                             simplifiedVolumeMm3=component["volumeMm3"], geometryQuality="original")
            from service.modeling import default_recipe, fingerprint
            component["recipe"] = default_recipe(component)
            component["recipeFingerprint"] = fingerprint(component["recipe"])
            component.pop("outputRepresentation", None)
            component.pop("installationRegions", None)
            component.pop("outputGeometry", None)
        if request["restorePose"]:
            component["pose"] = copy.deepcopy(component["originalPose"])
        check_geometry(project, job_id, progress_range=(3, 75))
    elif kind == "pose":
        check_geometry(project, job_id, progress_range=(2, 36))
        if not project["checks"]["sourceComplete"]:
            raise ValueError("基线真实几何检查未完成，暂不移动")
        baseline = copy.deepcopy(project["checks"])
        previous_pose = copy.deepcopy(component["pose"])
        component["pose"] = {"rotation": request["rotation"], "translationMm": request["translationMm"]}
        component["poseChange"] = {"reason": request["reason"], "authorization": request["authorization"], "at": db.now(),
                                  "before": previous_pose, "after": copy.deepcopy(component["pose"]),
                                  "translationDeltaMm": payload["translationDeltaMm"], "rotationDeltaDeg": payload["rotationDeltaDeg"]}
        check_geometry(project, job_id, progress_range=(37, 77))
        if not project["checks"]["sourceComplete"]:
            raise ValueError("移动后的真实实体检查未完成，位姿未提交")
        before_pairs = {tuple(sorted(p["componentIds"])) for p in baseline["sourceCollisions"]}
        new_pairs = {tuple(sorted(p["componentIds"])) for p in project["checks"]["sourceCollisions"]} - before_pairs
        if new_pairs:
            raise ValueError(f"候选移动造成新的真实干涉，位姿未提交：{sorted(new_pairs)}")
        before_volumes = {tuple(sorted(pair["componentIds"])): pair["intersectionVolumeMm3"] for pair in baseline["sourceCollisions"]}
        after_volumes = {tuple(sorted(pair["componentIds"])): pair["intersectionVolumeMm3"] for pair in project["checks"]["sourceCollisions"]}
        component["poseChange"]["sourceInterferenceVolumeMm3"] = {"before": sum(before_volumes.values()), "after": sum(after_volumes.values())}
        if request["authorization"] == "verified_source_collision":
            worsened = any(volume > before_volumes.get(pair, 0) + 1e-5 for pair, volume in after_volumes.items())
            improved = sum(after_volumes.values()) < sum(before_volumes.values()) - 1e-5
            if worsened or not improved:
                raise ValueError("自动干涉修复候选没有减少真实干涉，或加重已有干涉；位姿未提交")
        before_contacts = {tuple(sorted(p["componentIds"])): p for p in baseline["contacts"] if component["id"] in p["componentIds"]}
        after_contacts = {tuple(sorted(p["componentIds"])): p for p in project["checks"]["contacts"] if component["id"] in p["componentIds"]}
        changes = []
        for pair in before_contacts.keys() | after_contacts.keys():
            left, right = before_contacts.get(pair), after_contacts.get(pair)
            before_area, after_area = (left or {}).get("contactAreaMm2"), (right or {}).get("contactAreaMm2")
            if left is None or right is None or (before_area is not None and after_area is not None and abs(before_area - after_area) > max(1e-4, before_area * .01)):
                changes.append({"componentIds": list(pair), "before": left, "after": right})
        component["poseChange"]["contactChanges"] = changes
        constraints = component["metadata"]["motionConstraints"]
        if changes and (constraints.get("preserveContacts", True) or component["metadata"].get("thermalCritical")):
            raise ValueError("候选移动改变了需要保留的真实接触关系/面积，位姿未提交")
        project["checks"]["thermalStatus"] = "needs_review"
    else:
        raise ValueError(f"不支持的任务：{kind}")
    from service.modeling import invalidate_contacts, contact_candidates, build_recipe, selected_faces, exposed_region_faces, face_record
    if kind == "pose" or request.get("restorePose"):
        if component.get("installationRegions"):
            local, parts, _ = build_recipe(project, component, component["recipe"])
            for region in component["installationRegions"]:
                exposed = exposed_region_faces(selected_faces(parts[region["partId"]], region["selector"]), local)
                region["faces"] = [{**face_record(face, f"{region['id']}:{i}", component["pose"]),
                                     "outputFaceIndex": boundary} for i, (face, boundary) in enumerate(exposed)]
    invalidate_contacts(project, [component["id"]], "关联单机几何或装配位姿已改变，接触需复核")
    contact_candidates(project, job_id)
    shapes = world_shapes(project)
    component["boundsMm"] = bounds(shapes[component["id"]])
    component["centerMm"] = [(component["boundsMm"][i] + component["boundsMm"][i + 3]) / 2 for i in range(3)]
    relative = f"r{project['revision'] + 1}/simplified.glb"
    write_glb(project, shapes, db.project_dir(project["id"]) / "artifacts" / relative, job_id, progress_range=(80, 98))
    project["artifacts"]["simplifiedGlb"] = db.artifact_url(project["id"], relative)
    return project
