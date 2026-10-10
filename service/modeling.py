"""Rebuildable equipment recipes. Source BRep and occurrence poses stay immutable."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import time

from service import storage as db


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def default_recipe(component):
    from service.workbench import Recipe
    bounds = component["localBoundsMm"]
    strategy = component.get("strategy", "original")
    kind = "box" if strategy == "box" else "source"
    return Recipe.model_validate({"schemaVersion": 1, "representation": "solid" if kind == "box" else "source",
            "parts": [{"id": "body", "name": "主体", "kind": kind,
                       **({"centerMm": [(bounds[i] + bounds[i + 3]) / 2 for i in range(3)],
                           "sizeMm": [bounds[i + 3] - bounds[i] for i in range(3)]} if kind == "box" else {})}],
            "thermal": {"thicknessMm": None, "material": component.get("metadata", {}).get("material"),
                        "massKg": component.get("metadata", {}).get("massKg"), "specificHeatJPerKgK": None,
                        "conductivityWPerMK": None, "powerW": component.get("metadata", {}).get("powerW")},
            "regions": [], "dimensionBasis": "源 STEP 局部包围尺寸" if kind == "box" else "源 STEP 几何",
            "notes": "", "legacyCandidateFile": component.get("candidateFile") if strategy not in {"original", "box"} else None}).model_dump()


def ensure_workbench(project):
    """Lazy addition keeps old projects and their current geometry intact."""
    for component in project.get("components", []):
        component.setdefault("sourceName", component["name"])
        component.setdefault("recipe", default_recipe(component))
        component.setdefault("recipeFingerprint", fingerprint(component["recipe"]))
        component.setdefault("recipeCopies", [])
        if "displayName" not in component:
            # Only accept an existing Chinese name. Codes are not identity evidence.
            chinese = any("\u4e00" <= char <= "\u9fff" for char in component["name"])
            component["displayName"] = component["name"][:32] if chinese else f"待识别单机 {component['id'][1:]}"
            component["nameStatus"] = "source_name" if chinese else "unidentified"
        component.setdefault("engineeringGroup", "待分类")
        component.setdefault("nameStatus", "source_name" if any("\u4e00" <= char <= "\u9fff" for char in component["name"]) else "unidentified")
    project.setdefault("thermalContacts", [])
    project.setdefault("feedbackRecords", [])
    project.setdefault("workflowBindings", {})
    project.setdefault("purpose", "thermal")
    return project


def record_change(project, action, component_ids, reason, context=None, **details):
    context = context or {}
    session_id = context.get("sessionId")
    binding = project.get("workflowBindings", {}).get(session_id, {}) if session_id else {}
    if session_id and not binding:
        raise ValueError("请先绑定该 DSH 会话到当前工程和 Skill")
    if context.get("skillFingerprint") and context["skillFingerprint"] != binding.get("skillFingerprint"):
        raise ValueError("操作 Skill 指纹与会话绑定不一致")
    project.setdefault("feedbackRecords", []).append({
        "id": __import__("uuid").uuid4().hex, "at": db.now(), "action": action,
        "componentIds": list(component_ids), "reason": reason,
        "revision": project["revision"] + 1, "context": context,
        "skill": {k: binding.get(k) for k in ("skillId", "skillFingerprint")},
        "softwareVersion": "0.3.0", "autoSkillUpdate": False, **details})


def geometry_evidence(shape, representation):
    from service.geometry import solid_face_coverage
    faces, solids = shape.Faces(), shape.Solids()
    valid = bool(shape.isValid())
    area = sum(abs(float(face.Area())) for face in faces)
    volume = sum(abs(float(solid.Volume())) for solid in solids)
    surface = representation == "surface_shell"
    passed = valid and area > 1e-7 and (not solids if surface else bool(solids) and volume > 1e-7 and solid_face_coverage(shape)["completeSolidFaces"])
    return {"representation": representation, "valid": valid, "passed": bool(passed),
            "faceCount": len(faces), "solidCount": len(solids), "areaMm2": area,
            "volumeMm3": 0.0 if surface else volume, "volumeIsPhysicalMassProxy": False}


def build_recipe(project, component, recipe):
    from service.geometry import box_shape, cq_module, source_local
    cq = cq_module()
    parts = {}
    for item in recipe["parts"]:
        center = item.get("centerMm", [0, 0, 0])
        if item["kind"] == "source":
            if recipe.get("legacyCandidateFile"):
                from service.geometry import read_shape
                shape = read_shape(db.project_dir(project["id"]) / recipe["legacyCandidateFile"])
            else:
                shape = source_local(project, component)
        elif item["kind"] == "box":
            size = item["sizeMm"]
            shape = box_shape([center[i] - size[i] / 2 for i in range(3)] + [center[i] + size[i] / 2 for i in range(3)])
        else:
            axis = item.get("axis", [0, 0, 1])
            length = math.sqrt(sum(v * v for v in axis))
            if length < 1e-8:
                raise ValueError("圆柱轴向不能为零")
            axis = [v / length for v in axis]
            base = cq.Vector(*[center[i] - axis[i] * item["heightMm"] / 2 for i in range(3)])
            shape = cq.Solid.makeCylinder(item["radiusMm"], item["heightMm"], base, cq.Vector(*axis))
        if not shape.Faces():
            raise ValueError("方案组成未包含有效面")
        parts[item["id"]] = shape
    shapes = list(parts.values())
    shape = shapes[0]
    for other in shapes[1:]:
        shape = shape.fuse(other)
    if recipe["representation"] != "source":
        shape = shape.clean()
    if recipe["representation"] == "surface_shell":
        # Discard all solids intentionally. Even a closed shell remains a surface model.
        shape = cq.Compound.makeCompound(shape.Faces())
    elif recipe["representation"] == "source" and len(shapes) != 1:
        raise ValueError("源几何表示仅支持单一 source 组成")
    evidence = geometry_evidence(shape, recipe["representation"])
    if recipe["representation"] != "source" and not evidence["passed"]:
        raise ValueError("方案重建未通过表示类型对应的拓扑检查")
    return shape, parts, evidence


def face_record(face, face_id, pose):
    from service.geometry import bounds, shape_transform
    world = shape_transform(face, pose)
    vertices, triangles = world.tessellate(max(.2, math.sqrt(abs(float(world.Area()))) / 60), .3)
    normal = list(world.normalAt().toTuple()) if world.geomType() == "PLANE" else None
    return {"id": face_id, "geometryType": world.geomType(), "areaMm2": abs(float(world.Area())),
            "centerMm": list(world.Center().toTuple()), "normal": normal, "boundsMm": bounds(world),
            "verticesMm": [list(v.toTuple()) for v in vertices] if len(vertices) <= 1000 else [],
            "triangles": [list(t) for t in triangles] if len(vertices) <= 1000 else []}


def selected_faces(shape, selector):
    faces = shape.Faces()
    if selector == "all":
        return faces
    axis = {"xmin": (0, -1), "xmax": (0, 1), "ymin": (1, -1), "ymax": (1, 1), "zmin": (2, -1), "zmax": (2, 1)}
    if selector == "lateral":
        return [face for face in faces if face.geomType() == "CYLINDER"]
    dim, sign = axis[selector]
    values = [(list(face.Center().toTuple())[dim], face) for face in faces if face.geomType() == "PLANE"]
    if not values:
        return []
    limit = (min if sign == -1 else max)(v for v, _ in values)
    return [face for v, face in values if abs(v - limit) < 1e-5]


def exposed_region_faces(selected, output):
    """Clip primitive selectors to the final boundary, excluding buried faces."""
    from service.geometry import bounds, bounds_gap, cq_module
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    patches = []
    for face in selected:
        for index, boundary in enumerate(output.Faces()):
            if bounds_gap(bounds(face), bounds(boundary)) > 1e-5:
                continue
            if face.isSame(boundary):
                patches.append((boundary, index))
                break
            common = BRepAlgoAPI_Common(face.wrapped, boundary.wrapped)
            common.SetNonDestructive(True)
            common.SetRunParallel(False)
            common.Build()
            if not common.IsDone():
                raise ValueError("安装区域与最终输出边界的映射计算失败")
            if not common.Shape().IsNull():
                clipped = cq_module().Shape.cast(common.Shape())
                patches.extend((patch, index) for patch in clipped.Faces() if patch.Area() > 1e-7)
    return patches


def invalidate_contacts(project, changed, reason):
    """All geometry entry points invalidate contact decisions using the same rule."""
    ensure_workbench(project)
    for contact in project["thermalContacts"]:
        if any(side["componentId"] in changed for side in (contact["a"], contact["b"])):
            contact.update(mappingStatus="needs_review", previousStatus=contact["status"],
                           status="needs_review", mappingReason=reason)


def rebuild(project, changes, job_id, context=None, reason="重建单机方案"):
    from service.geometry import (bounds, read_step_fresh, shape_transform, source_hash,
                                  world_shapes, write_glb, write_shape)
    ensure_workbench(project)
    changed = []
    for index, change in enumerate(changes):
        component = next(c for c in project["components"] if c["id"] == change["componentId"])
        recipe = change["recipe"]
        local, parts, evidence = build_recipe(project, component, recipe)
        sha = fingerprint(recipe)
        relative = f"candidates/recipes/{component['id']}/{sha}.step"
        path = db.project_dir(project["id"]) / relative
        if not path.exists():
            write_shape(local, path)
        # Verify actual STEP representation, not just the in-memory shape.
        readback = geometry_evidence(read_step_fresh(path), recipe["representation"])
        if recipe["representation"] != "source" and not readback["passed"]:
            raise ValueError(f"单机 {component['id']} 的实际 STEP 回读未通过 {recipe['representation']} 表示检查；候选未提交")
        regions = []
        for region in recipe.get("regions", []):
            selected = selected_faces(parts[region["partId"]], region["selector"])
            if not selected:
                raise ValueError(f"安装区域未找到对应面：{region['id']}")
            exposed = exposed_region_faces(selected, local)
            if not exposed:
                raise ValueError(f"安装区域位于融合后的内部，未保留在输出边界：{region['id']}")
            regions.append({**region, "faces": [{**face_record(face, f"{region['id']}:{i}", component["pose"]),
                                                 "outputFaceIndex": boundary} for i, (face, boundary) in enumerate(exposed)],
                            "selectedAreaMm2": sum(abs(float(face.Area())) for face in selected),
                            "exposedAreaMm2": sum(abs(float(face.Area())) for face, _ in exposed),
                            "recipeFingerprint": sha, "mappingStatus": "mapped"})
        before = component["recipeFingerprint"]
        metadata = component.setdefault("metadata", {})
        for key in ("material", "massKg", "powerW"):
            value = recipe["thermal"].get(key)
            if value == metadata.get(key):
                continue
            if value is None:
                metadata.pop(key, None)
            else:
                metadata[key] = value
            metadata.setdefault("provenance", {})[key] = {"origin": "engineer_recipe", "state": "unknown" if value is None else "known", "at": db.now()}
            metadata["sources"] = [s for s in metadata.get("sources", []) if s.get("field", "").split(".")[0] != key]
        component.update(recipe=recipe, recipeFingerprint=sha, candidateFile=relative,
                         strategy="recipe", preserved=recipe["representation"] == "source",
                         preservationReason=None, geometryQuality="engineer_recipe",
                         outputGeometry=readback, outputRepresentation=recipe["representation"],
                         outputFaceCount=readback["faceCount"], outputSolidCount=readback["solidCount"],
                         outputTopologyValid=readback["valid"], simplifiedVolumeMm3=readback["volumeMm3"],
                         installationRegions=regions, recipeStepSha256=source_hash(path))
        world = shape_transform(local, component["pose"])
        component["candidateBoundsMm"] = bounds(world)
        changed.append(component["id"])
        record_change(project, "rebuild_recipe", [component["id"]], change.get("reason", reason), context,
                      beforeFingerprint=before, afterFingerprint=sha, recipe=recipe)
        db.progress(job_id, 5 + 60 * (index + 1) / len(changes), f"重建单机 {index + 1}/{len(changes)}")
    invalidate_contacts(project, changed, "关联单机方案已改变，安装区域及热接触需复核")
    # Old collision results describe another candidate. Never carry a pass forward.
    project["checks"].update(envelopeComplete=False, thermalStatus="needs_review",
                              envelopeCollisions=[], falsePositivePairs=[],
                              candidateCheckStatus="not_checked_after_recipe_change")
    relative = f"r{project['revision'] + 1}/simplified.glb"
    write_glb(project, world_shapes(project), db.project_dir(project["id"]) / "artifacts" / relative, job_id, (68, 98))
    project["artifacts"]["simplifiedGlb"] = db.artifact_url(project["id"], relative)
    project.update(status="candidate", purpose="thermal")
    return project


def contact_candidates(project, job_id, *, patch_budget_seconds=30, max_patch_pairs=3000):
    """Attach actual source face patches; geometric candidates remain unconfirmed."""
    from service.geometry import bounds, bounds_gap, cq_module, source_local, shape_transform
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    ensure_workbench(project)
    sources = {c["id"]: shape_transform(source_local(project,c),c["pose"]) for c in project["components"]}
    output = project["thermalContacts"]
    started=time.monotonic()
    patch_pairs=0
    seen = set()
    incomplete = 0
    for entry in project["checks"].get("contacts", []):
        ids = entry["componentIds"]
        contact_id = "TC-" + fingerprint(sorted(ids))[:16]
        seen.add(contact_id)
        existing = next((item for item in output if item["id"] == contact_id), None)
        if existing and existing.get("origin") != "geometry":
            continue
        patches = []
        left, right = sources[ids[0]].Faces(), sources[ids[1]].Faces()
        patch_status = "completed"
        patch_reason = None
        if any(face.geomType() != "PLANE" for face in left + right):
            patch_status, patch_reason = "partial", "仅映射平面接触；曲面区域待复核"
        if len(left) * len(right) <= 50000:
            for i, a in enumerate(left):
                if time.monotonic()-started>patch_budget_seconds or patch_pairs>=max_patch_pairs:
                    patch_status, patch_reason = "partial", "接触面映射达到计算预算"
                    break
                if a.geomType() != "PLANE":
                    continue
                for j, b in enumerate(right):
                    if time.monotonic()-started>patch_budget_seconds or patch_pairs>=max_patch_pairs:
                        patch_status, patch_reason = "partial", "接触面映射达到计算预算"
                        break
                    if b.geomType() != "PLANE" or bounds_gap(bounds(a), bounds(b)) > 1e-5:
                        continue
                    patch_pairs+=1
                    common = BRepAlgoAPI_Common(a.wrapped, b.wrapped)
                    common.SetNonDestructive(True)
                    common.SetRunParallel(False)
                    common.Build()
                    if not common.IsDone():
                        patch_status, patch_reason = "partial", "部分接触面求交失败"
                    elif not common.Shape().IsNull():
                        shape = cq_module().Shape.cast(common.Shape())
                        for n, face in enumerate(shape.Faces()):
                            if face.Area() > 1e-7:
                                from service.geometry import identity_pose
                                patches.append({"aSourceFace": i, "bSourceFace": j,
                                                **face_record(face, f"{contact_id}:{i}:{j}:{n}", identity_pose())})
        else:
            patch_status, patch_reason = "partial", "源面组合数量超过接触映射预算"
        if not patches:
            patch_status = "partial"
            patch_reason = patch_reason or "尚未取得可显示的源接触面区域"
        incomplete += patch_status != "completed"
        value = {"id": contact_id, "a": {"componentId": ids[0], "regionId": None},
                 "b": {"componentId": ids[1], "regionId": None}, "status": "candidate",
                 "mappingStatus": "source_patch_only", "origin": "geometry",
                 "areaMm2": entry.get("contactAreaMm2"), "conductanceWPerK": None,
                 "evidence": "源 STEP 按当前装配位姿的几何接触；未认证热导通", "patches": patches,
                 "patchDiscovery": {"status": patch_status, "reason": patch_reason, "scope": "planar_faces"},
                 "sourcePoseFingerprint": fingerprint({cid: next(c["pose"] for c in project["components"] if c["id"] == cid) for cid in ids}),
                 "unknownFields": ["conductanceWPerK", "installation_constraints"], "updatedAt": db.now()}
        if existing:
            if existing["status"] != "candidate":
                continue  # A later source check never silently overwrites engineering decisions.
            existing.update(value)
        else:
            output.append(value)
        db.progress(job_id, 92, "整理源安装接触区域")
    if project["checks"].get("sourceComplete"):
        for item in output:
            if item.get("origin") == "geometry" and item["id"] not in seen:
                item.update(status="needs_review", mappingStatus="needs_review",
                            mappingReason="当前源几何检查未再次发现此接触，需工程师复核")
    project["contactDiscovery"] = {"status": "completed" if project["checks"].get("sourceComplete") and not incomplete else "partial",
                                   "sourceGeometryComplete": project["checks"].get("sourceComplete", False),
                                   "incompletePatchContacts": incomplete, "patchPairs": patch_pairs,
                                   "sourceRevision": project["revision"], "at": db.now()}
