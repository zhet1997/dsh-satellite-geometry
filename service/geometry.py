"""STEP-first geometry operations; model decisions cannot execute arbitrary code.

All source STEP files and source poses remain immutable. Candidate shapes are
stored in source-local coordinates and exported using explicit world placements.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import struct
import sys
import time
import uuid
from functools import lru_cache
from pathlib import Path

import numpy as np

from service.storage import artifact_url, atomic_json, now, progress, project_dir
from vendor.step_occurrences import is_structural_container_name, parse_step_occurrences, resolve_node_name


def cq_module():
    import cadquery as cq
    return cq


def identity_pose():
    return {"rotation": [[1., 0., 0.], [0., 1., 0.], [0., 0., 1.]], "translationMm": [0., 0., 0.]}


def shape_transform(shape, pose: dict, *, inverse=False):
    from OCP.gp import gp_Trsf
    from OCP.TopLoc import TopLoc_Location
    rotation = np.asarray(pose["rotation"], dtype=float)
    translation = np.asarray(pose["translationMm"], dtype=float)
    if inverse:
        rotation = rotation.T
        translation = -(rotation @ translation)
    trsf = gp_Trsf()
    trsf.SetValues(*(float(value) for row in np.column_stack((rotation, translation)) for value in row))
    return cq_module().Shape.cast(shape.wrapped.Moved(TopLoc_Location(trsf)))


def pose_from_location(location):
    trsf = location.Transformation()
    return {"rotation": [[float(trsf.Value(row, col)) for col in (1, 2, 3)] for row in (1, 2, 3)],
            "translationMm": [float(trsf.Value(row, 4)) for row in (1, 2, 3)]}


def location_from_pose(pose):
    from OCP.gp import gp_Trsf
    trsf = gp_Trsf()
    values = np.column_stack((np.asarray(pose["rotation"], dtype=float), np.asarray(pose["translationMm"], dtype=float)))
    trsf.SetValues(*(float(value) for row in values for value in row))
    return cq_module().Location(trsf)


def bounds(shape):
    if len(shape.Faces()) <= 400:
        box = shape.BoundingBox()
        return [float(box.xmin), float(box.ymin), float(box.zmin), float(box.xmax), float(box.ymax), float(box.zmax)]
    # A conservative BRep bound is sufficient for envelope containment and broad
    # phase checks. AddOptimal runs expensive numerical extrema searches on Creo
    # trimmed/transformed toroidal surfaces. Do not rely on preview triangulation.
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    box = Bnd_Box()
    BRepBndLib.Add_s(shape.wrapped, box, False)
    if box.IsVoid():
        raise ValueError("组件没有可计算包围盒的几何")
    return [float(value) for value in box.Get()]


def bounds_gap(a, b):
    return math.sqrt(sum(max(a[i] - b[i + 3], b[i] - a[i + 3], 0.) ** 2 for i in range(3)))


def broad_pairs(components, tolerance):
    """Sweep on x and retain AABB-near pairs; disjoint boxes are conservative."""
    ordered = sorted(components, key=lambda item: item["boundsMm"][0])
    for index, left in enumerate(ordered):
        for right in ordered[index + 1:]:
            if right["boundsMm"][0] > left["boundsMm"][3] + tolerance:
                break
            if bounds_gap(left["boundsMm"], right["boundsMm"]) <= tolerance:
                yield left, right


def source_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


_SHAPE_WRITE_GENERATIONS = {}


@lru_cache(maxsize=512)
def _read_shape_cached(absolute_path, modified_ns, byte_count, write_generation=0):
    cq = cq_module()
    path = Path(absolute_path)
    cache = brep_cache_path(path, modified_ns, byte_count)
    if cache.is_file():
        try:
            return cq.Shape.importBin(str(cache))
        except Exception:
            # A partial or stale cache never makes source STEP unreadable.
            pass
    result = cq.importers.importStep(absolute_path).val()
    if result is None or result.wrapped.IsNull():
        raise ValueError(f"STEP 几何为空：{Path(absolute_path).name}")
    save_brep_cache(path, result, cache)
    return result


def brep_cache_path(path, modified_ns=None, byte_count=None):
    import OCP
    path = Path(path).resolve()
    if modified_ns is None:
        stat = path.stat()
        modified_ns, byte_count = stat.st_mtime_ns, stat.st_size
    identity = [str(path), modified_ns, byte_count, getattr(OCP, "__version__", "unknown"), "binary-brep-v1"]
    key = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
    return path.parent / ".brep-cache" / f"{key}.brep.bin"


def save_brep_cache(path, shape, cache=None):
    cache = cache or brep_cache_path(path)
    temporary = cache.with_name(f".{cache.name}.{uuid.uuid4().hex}.tmp")
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        if not shape.exportBin(str(temporary)):
            return
        os.replace(temporary, cache)
    except (OSError, ValueError):
        # Read-only sources remain usable; conversion caching is optional.
        pass
    finally:
        temporary.unlink(missing_ok=True)


def read_shape(path):
    # One worker owns one job; source shapes are treated as immutable. Stat keys
    # also prevent a rewritten candidate/export file from reusing older geometry.
    path = Path(path).resolve()
    stat = path.stat()
    return _read_shape_cached(str(path), stat.st_mtime_ns, stat.st_size, _SHAPE_WRITE_GENERATIONS.get(str(path), 0))


def read_step_fresh(path):
    """Verify the serialized STEP, independently of any pre-export BRep cache."""
    path = Path(path).resolve()
    shape = cq_module().importers.importStep(str(path)).val()
    if shape is None or shape.wrapped.IsNull():
        raise ValueError(f"STEP 几何为空：{path.name}")
    invalidate_shape_cache(path)
    save_brep_cache(path, shape)
    return shape


def invalidate_shape_cache(path):
    # Some filesystems can give rapid equal-size rewrites the same timestamp.
    # Explicit writes must still invalidate an in-process cached shape.
    key = str(Path(path).resolve())
    _SHAPE_WRITE_GENERATIONS[key] = _SHAPE_WRITE_GENERATIONS.get(key, 0) + 1


def write_shape(shape, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    cq_module().exporters.export(shape, str(path), exportType="STEP")
    invalidate_shape_cache(path)
    save_brep_cache(path, shape)


def source_local(project, component):
    return read_shape(project_dir(project["id"]) / component["sourceFile"])


def solid_face_coverage(shape):
    """Do not certify a mixed solid/shell compound using only solid volume."""
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape
    all_faces, solid_faces = TopTools_IndexedMapOfShape(), TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape.wrapped, TopAbs_FACE, all_faces)
    for solid in shape.Solids():
        TopExp.MapShapes_s(solid.wrapped, TopAbs_FACE, solid_faces)
    missing = sum(not solid_faces.Contains(all_faces.FindKey(index)) for index in range(1, all_faces.Extent() + 1))
    return {"version": 1, "faceCount": all_faces.Extent(), "solidFaceCount": solid_faces.Extent(),
            "nonSolidFaceCount": missing, "completeSolidFaces": missing == 0 and all_faces.Extent() > 0}


def candidate_local(project, component):
    return read_shape(project_dir(project["id"]) / (component.get("candidateFile") or component["sourceFile"]))


def world_shapes(project, *, source=False, job_id=None, progress_range=(2, 15)):
    loaded = {}
    result = {}
    for index, component in enumerate(project["components"]):
        if job_id:
            progress(job_id, progress_range[0] + (progress_range[1] - progress_range[0]) * index / len(project["components"]),
                     f"加载组件几何 {index + 1}/{len(project['components'])}：{component['name']}")
        relative = component["sourceFile"] if source else component.get("candidateFile") or component["sourceFile"]
        if relative not in loaded:
            loaded[relative] = read_shape(project_dir(project["id"]) / relative)
        pose = component["originalPose"] if source else component["pose"]
        result[component["id"]] = shape_transform(loaded[relative], pose)
    return result


def import_step(project, path: Path, job_id: str):
    cq = cq_module()
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDataStd import TDataStd_Name
    from OCP.TDF import TDF_Label, TDF_LabelSequence
    from OCP.TDocStd import TDocStd_Document
    from OCP.TopLoc import TopLoc_Location
    from OCP.XCAFDoc import XCAFDoc_DocumentTool

    progress(job_id, 3, "读取 STEP 装配、名称和实例关系")
    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    reader.SetColorMode(True)
    # Working components do not consume XCAF presentation-layer labels. Creo
    # exports with many named faces make ReadLayers repeatedly search the whole
    # shape tree. Keep layers in the immutable source STEP, but omit their unused
    # XCAF indexing; geometry, names, colours and occurrence transforms still load.
    reader.SetLayerMode(False)
    if "RetDone" not in str(reader.ReadFile(str(path))):
        raise ValueError("无法读取 STEP 文件")
    progress(job_id, 7, "建立 STEP 几何装配文档（名称、颜色及原始实例位姿）")
    document = TDocStd_Document(TCollection_ExtendedString("satellite"))
    if not reader.Transfer(document):
        raise ValueError("无法建立 STEP 装配文档")
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    occurrence_tree = parse_step_occurrences(path)

    def referred(label):
        target = TDF_Label()
        return target if shape_tool.GetReferredShape_s(label, target) else label

    def label_name(label):
        value = TDataStd_Name()
        if label.FindAttribute(TDataStd_Name.GetID_s(), value):
            return value.Get().ToExtString()
        return ""

    nodes, shape_map = [], {}

    def visit(label, parent, location, definition_id, occurrence=None):
        node_id = f"N{len(nodes) + 1:05d}"
        target = referred(label)
        resolved = resolve_node_name(occurrence=occurrence, label_name=label_name(label),
                                     target_name=label_name(target), fallback=node_id)
        native = shape_tool.GetShape_s(label)
        world_location = location.Multiplied(native.Location())
        shape = cq.Shape.cast(native.Located(world_location))
        children = TDF_LabelSequence()
        if shape_tool.IsAssembly_s(target):
            shape_tool.GetComponents_s(target, children, False)
        node = {"id": node_id, "name": resolved.name, "parentId": parent, "children": [],
                "isLeaf": children.Length() == 0, "stepDefinitionId": definition_id,
                "pose": pose_from_location(world_location), "nameSource": resolved.source}
        if occurrence:
            node["stepOccurrenceId"] = occurrence.occurrence_id
        nodes.append(node)
        shape_map[node_id] = shape
        semantic = occurrence_tree.children(definition_id)
        semantic = semantic if len(semantic) == children.Length() else [None] * children.Length()
        for index in range(1, children.Length() + 1):
            relation = semantic[index - 1]
            child = visit(children.Value(index), node_id, world_location,
                          relation.child_definition_id if relation else None, relation)
            node["children"].append(child)
        return node_id

    roots = TDF_LabelSequence()
    shape_tool.GetFreeShapes(roots)
    counts = []
    for index in range(1, roots.Length() + 1):
        children = TDF_LabelSequence()
        shape_tool.GetComponents_s(referred(roots.Value(index)), children, False)
        counts.append(children.Length())
    definitions = occurrence_tree.match_root_definitions(counts)
    root_ids = [visit(roots.Value(i), None, TopLoc_Location(), definitions[i - 1]) for i in range(1, roots.Length() + 1)]
    by_id = {node["id"]: node for node in nodes}
    selected = []

    def select(node_id, is_root=False):
        node = by_id[node_id]
        if not node["children"] or (not is_root and not is_structural_container_name(node["name"])):
            selected.append(node)
        else:
            for child in node["children"]:
                select(child)

    leaf_nodes = [node for node in nodes if node["isLeaf"]]
    selection_strategy = "leaf-occurrences"
    if len(leaf_nodes) <= int(os.environ.get("SATCAD_MAX_LEAF_COMPONENTS", "128")):
        selected = leaf_nodes
    else:
        selection_strategy = "semantic-top-down-preserve-all-occurrences"
        for root_id in root_ids:
            select(root_id, True)

    def leaves(node_id):
        node = by_id[node_id]
        return [node_id] if node["isLeaf"] else [leaf for child in node["children"] for leaf in leaves(child)]

    components, prototypes = [], {}
    root = project_dir(project["id"])
    progress(job_id, 15, f"保存 {len(selected)} 个组件和原始位姿")
    for index, node in enumerate(selected):
        shape = shape_map[node["id"]]
        pose = node["pose"]
        local = shape_transform(shape, pose, inverse=True)
        key = node["stepDefinitionId"] or f"node:{node['id']}"
        prototype_id = prototypes.get(key)
        if prototype_id is None:
            prototype_id = f"P{len(prototypes) + 1:05d}"
            prototypes[key] = prototype_id
            write_shape(local, root / "source" / "prototypes" / f"{prototype_id}.step")
        local_bounds = bounds(local)
        world_bounds = bounds(shape)
        dimensions = [local_bounds[i + 3] - local_bounds[i] for i in range(3)]
        solid_count = len(local.Solids())
        shape_valid = bool(local.isValid())
        coverage = solid_face_coverage(local)
        volume = abs(float(local.Volume())) if solid_count else 0.
        component = {"id": node["id"], "name": node["name"], "parentId": node["parentId"],
                     "sourceNodeIds": leaves(node["id"]), "prototypeId": prototype_id,
                     "sourceFile": f"source/prototypes/{prototype_id}.step", "sourceHash": source_hash(root / "source" / "prototypes" / f"{prototype_id}.step"),
                     "localBoundsMm": local_bounds, "boundsMm": world_bounds, "dimensionsMm": dimensions,
                     "centerMm": [(world_bounds[i] + world_bounds[i + 3]) / 2 for i in range(3)],
                     "pose": copy.deepcopy(pose), "originalPose": copy.deepcopy(pose),
                     "strategy": "original", "preserved": True, "preservationReason": "导入时保留原始几何与装配位姿",
                     "volumeMm3": volume, "simplifiedVolumeMm3": volume, "faceCount": len(local.Faces()),
                     "solidCount": solid_count, "sourceTopologyValid": shape_valid,
                     "sourceValid": shape_valid and solid_count > 0 and volume > 0 and coverage["completeSolidFaces"],
                     "sourceGeometryCoverage": coverage,
                     "boundsMethod": "OCCT_optimal_small_conservative_BRep_Add_over_400_faces",
                     "metadata": {}, "geometryQuality": "original"}
        node["componentId"] = component["id"]
        components.append(component)
        progress(job_id, 15 + 50 * (index + 1) / max(1, len(selected)), f"组件 {index + 1}/{len(selected)}：{node['name']}")
    if not components:
        raise ValueError("STEP 未包含可用组件")
    project.update(tree=nodes, rootIds=root_ids, components=components, status="imported",
                   source={"name": path.name, "sha256": source_hash(path), "bytes": path.stat().st_size,
                           "importedAt": now(), "nodeCount": len(nodes), "componentCount": len(components),
                           "prototypeCount": len(prototypes), "instanceCount": len(components),
                           "selectionStrategy": selection_strategy})
    project["source"]["boundsMethod"] = "OCCT_optimal_small_conservative_BRep_Add_over_400_faces"
    project["sourceTree"] = copy.deepcopy(nodes)
    original = {component["id"]: shape_map[component["id"]] for component in components}
    glb_path = root / "artifacts" / "original.glb"
    write_glb(project, original, glb_path, job_id, progress_range=(66, 96))
    project["artifacts"]["originalGlb"] = artifact_url(project["id"], "original.glb")
    project["artifacts"]["sourceStep"] = artifact_url(project["id"], "source.step")
    project["checks"]["warnings"] = ["导入保留原布局；尚未进行真实实体干涉、热接触及包络检查"]
    return project


def _exact_pair_in_process(left, right, tolerance):
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    dist = BRepExtrema_DistShapeShape(left.wrapped, right.wrapped)
    dist.SetMultiThread(False)
    dist.Perform()
    if not dist.IsDone():
        raise ValueError("OCCT距离计算未完成")
    distance = float(dist.Value())
    volume, area = 0., None
    if distance <= min(tolerance, 1e-5):
        operation = BRepAlgoAPI_Common(left.wrapped, right.wrapped)
        operation.SetNonDestructive(True)
        operation.SetRunParallel(False)
        operation.SetFuzzyValue(1e-7)
        operation.Build()
        if not operation.IsDone():
            raise ValueError("OCCT实体求交未完成")
        common = cq_module().Shape.cast(operation.Shape())
        if not common.wrapped.IsNull():
            volume = abs(float(common.Volume())) if common.Solids() else 0.
            faces = common.Faces()
            area = sum(abs(float(face.Area())) for face in faces) if faces and volume <= 1e-5 else None
    if distance <= min(tolerance, 1e-5) and volume <= 1e-5 and (area is None or area <= 1e-7):
        area = planar_contact_area(left, right)
    return {"distanceMm": distance, "intersectionVolumeMm3": volume,
            "contactAreaMm2": area, "status": "interference" if volume > 1e-5 else "contact" if distance <= tolerance else "separate"}


class PairTimeout(ValueError):
    pass


class CheckBudgetExceeded(ValueError):
    pass


_PAIR_FAILURES = {}


def _pair_process(sender, left, right, tolerance, expected_parent):
    # This child stays in the CAD worker's process group. Explicit cancellation
    # kills the group; parent death also terminates the individual child.
    try:
        import ctypes
        import signal
        ctypes.CDLL(None).prctl(1, signal.SIGTERM)
        if os.getppid() != expected_parent:
            return
        sender.send({"ok": True, "result": _exact_pair_in_process(left, right, tolerance)})
    except BaseException as exc:
        sender.send({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
    finally:
        sender.close()


def exact_pair(left, right, tolerance, *, timeout_seconds=None):
    maximum = float(os.environ.get("SATCAD_PAIR_TIMEOUT_SECONDS", "10")) if timeout_seconds is None else timeout_seconds
    if not sys.platform.startswith("linux") or maximum <= 0:
        return _exact_pair_in_process(left, right, tolerance)
    import multiprocessing
    context = multiprocessing.get_context("fork")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_pair_process, args=(sender, left, right, tolerance, os.getpid()), daemon=True)
    process.start()
    sender.close()
    try:
        if not receiver.poll(maximum):
            raise PairTimeout(f"单对精确几何检查超过 {maximum:.3g} 秒；结果未知，相关组件保留原几何")
        try:
            message = receiver.recv()
        except EOFError as exc:
            raise ValueError("单对几何进程意外退出，结果未知") from exc
        if not message["ok"]:
            raise ValueError(message["error"])
        return message["result"]
    finally:
        receiver.close()
        process.join(timeout=.1)
        if process.is_alive():
            process.terminate()
            process.join(timeout=1)
        if process.is_alive():
            process.kill()
            process.join(timeout=1)
        process.close()


def planar_contact_area(left, right):
    """Measure shared planar contact patches; unknown curved contacts stay null."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    left_faces, right_faces = left.Faces(), right.Faces()
    if len(left_faces) * len(right_faces) > 100_000:
        return None
    area = 0.
    for a in left_faces:
        if a.geomType() != "PLANE":
            continue
        normal = np.array(a.normalAt().toTuple())
        a_bounds = bounds(a)
        for b in right_faces:
            if bounds_gap(a_bounds, bounds(b)) > 1e-5 or b.geomType() != "PLANE":
                continue
            other = np.array(b.normalAt().toTuple())
            if abs(float(normal @ other)) < 1 - 1e-7:
                continue
            common = BRepAlgoAPI_Common(a.wrapped, b.wrapped)
            common.SetNonDestructive(True)
            common.SetRunParallel(False)
            common.SetFuzzyValue(1e-7)
            common.Build()
            if common.IsDone() and not common.Shape().IsNull():
                value = cq_module().Shape.cast(common.Shape())
                area += sum(abs(float(face.Area())) for face in value.Faces())
    return area if area > 1e-7 else None


def check_geometry(project, job_id, *, tolerance=0.1, progress_range=(2, 90), source_only=False):
    """Separate real source/candidate-original geometry from simplification artifacts."""
    loading_end = progress_range[0] + (progress_range[1] - progress_range[0]) * .15
    candidate_shapes = world_shapes(project, job_id=job_id, progress_range=(progress_range[0], loading_end))
    # A moved component's real geometry is its immutable source at the candidate pose.
    source_cache, real_shapes = {}, {}
    for component in project["components"]:
        if component["strategy"] == "original":
            real_shapes[component["id"]] = candidate_shapes[component["id"]]
        else:
            relative = component["sourceFile"]
            if relative not in source_cache:
                source_cache[relative] = source_local(project, component)
            real_shapes[component["id"]] = shape_transform(source_cache[relative], component["pose"])
        # Existing imports predate this evidence field. Populate it on the first
        # check without reimporting the entire source assembly or losing poses.
        if "sourceGeometryCoverage" not in component:
            component["sourceGeometryCoverage"] = solid_face_coverage(real_shapes[component["id"]])
        if not component["sourceGeometryCoverage"]["completeSolidFaces"]:
            component["sourceValid"] = False
    candidates = []
    for component in project["components"]:
        candidate = dict(component)
        # Recipe candidates may extend beyond source dimensions. The broad
        # phase must cover both source and rebuilt geometry at the current pose.
        local = component["localBoundsMm"]
        corners = np.array([[local[x], local[y], local[z]] for x in (0, 3) for y in (1, 4) for z in (2, 5)])
        transformed = corners @ np.asarray(component["pose"]["rotation"]).T + np.asarray(component["pose"]["translationMm"])
        candidate["boundsMm"] = (transformed.min(axis=0) - 1e-5).tolist() + (transformed.max(axis=0) + 1e-5).tolist()
        if component.get("strategy") == "recipe":
            actual = bounds(candidate_shapes[component["id"]])
            candidate["boundsMm"] = [min(candidate["boundsMm"][i], actual[i]) for i in range(3)] + [max(candidate["boundsMm"][i], actual[i]) for i in range(3, 6)]
        candidates.append(candidate)
    pairs = list(broad_pairs(candidates, tolerance))
    # Source contacts repeat across simplification and metadata revisions. Cache
    # only completed exact results, keyed by immutable geometry and both poses.
    # A moved component or a tolerance/kernel change cannot reuse an old result.
    import OCP
    cache_path = project_dir(project["id"]) / "cache" / "source-pairs.json"
    try:
        source_pair_cache = json.loads(cache_path.read_text(encoding="utf-8"))
        if not isinstance(source_pair_cache, dict):
            source_pair_cache = {}
    except (OSError, ValueError):
        source_pair_cache = {}
    kernel_version = getattr(OCP, "__version__", "unknown")
    source_cache_hits, new_cached_pairs = 0, 0
    maximum = int(os.environ.get("SATCAD_MAX_EXACT_PAIRS", "1500"))
    source_collisions, envelope_collisions, false_positives, contacts, errors, surface_pairs = [], [], [], [], [], []
    uncertain = {component["id"] for component in project["components"] if not component["sourceValid"]}
    total = len(pairs)
    evaluated_pairs, completed_source_pairs = 0, 0
    started = time.monotonic()
    budget = max(.000001, float(os.environ.get("SATCAD_CHECK_BUDGET_SECONDS", "300")))
    pair_limit = float(os.environ.get("SATCAD_PAIR_TIMEOUT_SECONDS", "10"))
    unknown_counts = {"pairTimeouts": 0, "checkBudgetPairs": 0, "pairLimitPairs": max(0, total - maximum), "geometryErrorPairs": 0, "invalidSourcePairs": 0}

    def calculate(left_shape, right_shape):
        remaining = budget - (time.monotonic() - started)
        if remaining <= 0:
            raise CheckBudgetExceeded("单轮精确检查时间预算已用尽；该对未完成检查")
        return exact_pair(left_shape, right_shape, tolerance, timeout_seconds=min(pair_limit, remaining) if pair_limit > 0 else remaining)

    for index, (left, right) in enumerate(pairs):
        ids = [left["id"], right["id"]]
        if index >= maximum:
            uncertain.update(ids)
            continue
        progress(job_id, loading_end + (progress_range[1] - loading_end) * (index + 1) / max(1, min(total, maximum)),
                 f"真实 STEP 与候选几何检查 {index + 1}/{min(total, maximum)}")
        if not left["sourceValid"] or not right["sourceValid"]:
            errors.append({"componentIds": ids, "error": "组件不含完整有效闭合实体或包含未归属实体的面，无法确认全部源几何干涉"})
            unknown_counts["invalidSourcePairs"] += 1
            uncertain.update(ids)
            continue
        try:
            identity = [sorted([json.dumps({"hash": component["sourceHash"], "pose": component["pose"]}, sort_keys=True) for component in (left, right)]),
                        tolerance, kernel_version, "exact-pair-contact-area-v1"]
            cache_key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
            failure_key = (job_id, cache_key)
            if cache_key in source_pair_cache:
                real = source_pair_cache[cache_key]
                source_cache_hits += 1
            elif failure_key in _PAIR_FAILURES:
                error_type, message = _PAIR_FAILURES[failure_key]
                raise error_type(message)
            else:
                try:
                    real = calculate(real_shapes[ids[0]], real_shapes[ids[1]])
                except (PairTimeout, CheckBudgetExceeded, ValueError) as exc:
                    _PAIR_FAILURES[failure_key] = (type(exc), str(exc))
                    raise
                source_pair_cache[cache_key] = real
                new_cached_pairs += 1
                if new_cached_pairs % 10 == 0:
                    atomic_json(cache_path, source_pair_cache)
            entry = {"componentIds": ids, **real}
            completed_source_pairs += 1
            if real["status"] == "interference":
                source_collisions.append(entry)
            elif real["status"] == "contact":
                contacts.append({**entry, "kind": "geometric_contact_candidate", "thermalConductanceKnown": False,
                                 "source": "immutable_source_step_at_current_pose"})
            same_geometry = left["strategy"] == "original" and right["strategy"] == "original"
            envelope = real if same_geometry or source_only else calculate(candidate_shapes[ids[0]], candidate_shapes[ids[1]])
            if not source_only and any(c.get("outputRepresentation") == "surface_shell" for c in (left, right)):
                surface_pairs.append({"componentIds": ids, **envelope,
                                      "volumeInterferenceApplicable": False,
                                      "scope": "surface_distance_and_overlap_only_not_solid_penetration"})
            evaluated_pairs += 1
            if envelope["status"] == "interference":
                envelope_entry = {"componentIds": ids, **envelope,
                                  "realGeometryStatus": real["status"], "isFalsePositive": real["status"] != "interference"}
                envelope_collisions.append(envelope_entry)
                if envelope_entry["isFalsePositive"]:
                    false_positives.append(envelope_entry)
        except Exception as exc:
            category = "pairTimeouts" if isinstance(exc, PairTimeout) else "checkBudgetPairs" if isinstance(exc, CheckBudgetExceeded) else "geometryErrorPairs"
            unknown_counts[category] += 1
            errors.append({"componentIds": ids, "error": str(exc), "kind": category})
            uncertain.update(ids)
    if total > maximum:
        errors.append({"error": f"精确检查达到 {maximum} 对上限，未检查 {total - maximum} 对；涉及组件保留原几何"})
    if new_cached_pairs:
        atomic_json(cache_path, source_pair_cache)
    complete = not uncertain and not errors
    thermal_changed = [c["id"] for c in project["components"] if c["strategy"] != "original" and
                       (c.get("metadata", {}).get("thermalCritical") or any(c["id"] in p["componentIds"] for p in contacts))]
    checks = {"checkedAt": now(), "sourceCollisions": source_collisions,
              "envelopeCollisions": envelope_collisions, "falsePositivePairs": false_positives,
              "surfacePairs": surface_pairs, "surfacePenetrationCertified": False if surface_pairs else None,
              "contacts": contacts, "errors": errors, "uncertainComponentIds": sorted(uncertain),
              "sourceComplete": complete, "envelopeComplete": complete and not source_only,
              "evaluatedPairCount": evaluated_pairs, "completedSourcePairCount": completed_source_pairs, "candidatePairCount": total,
              "sourcePairCacheHits": source_cache_hits,
              "unknownPairCounts": unknown_counts,
              "limits": {"pairTimeoutSeconds": pair_limit, "exactCheckBudgetSeconds": budget,
                         "pairIsolation": "linux_fork" if sys.platform.startswith("linux") else "job_process_only"},
              "contactToleranceMm": tolerance, "sourceGeometry": "original STEP BRep at candidate pose",
              "assemblyStatus": "unknown" if not complete else "needs_review" if source_collisions else "passed",
              "thermalStatus": "unknown" if not complete else "needs_review" if thermal_changed else "passed",
              "thermalAcceptanceScope": "preservation of identified contact-bearing/critical source components; no thermal conductance certification",
              "assemblyAcceptanceScope": "component-to-component original STEP solid intersection; interfaces and full shell containment are separate",
              "warnings": ["接触识别来自几何距离；热接触导通、材料和紧固关系需要资料确认", "装配检查不包含电缆、孔位配合、安装顺序和全壳体包含性"]}
    if source_only:
        checks["envelopeComplete"] = False
    if surface_pairs:
        checks["thermalStatus"] = "needs_review" if complete else "unknown"
        checks["warnings"].append("面壳检查为距离/交叠检查，零实体体积不能证明壳体无穿透；须复核安装区域")
    project["checks"] = checks
    return checks


def box_shape(local_bounds):
    cq = cq_module()
    sizes = [max(1e-6, local_bounds[i + 3] - local_bounds[i]) for i in range(3)]
    return cq.Solid.makeBox(*sizes, pnt=cq.Vector(*local_bounds[:3]))


def multibox_shape(source):
    solids = source.Solids()
    if len(solids) < 2:
        return box_shape(bounds(source)), 1
    if len(solids) > 128:
        raise ValueError("实体数超过128，保留原几何，避免多盒融合耗时或丢失拓扑")
    boxes = [box_shape(bounds(solid)) for solid in solids]
    result = boxes[0]
    if len(boxes) > 1:
        result = result.fuse(*boxes[1:])
    return result, len(boxes)


def refine_envelope(source, current_volume, local_bounds):
    """One bounded attempt to keep voids using source solids or planar slabs."""
    cq = cq_module()
    solids = source.Solids()
    if 1 < len(solids) <= 64:
        candidate, count = multibox_shape(source)
        if candidate.isValid() and abs(float(candidate.Volume())) < current_volume * .999:
            return candidate, count, "source_solid_boxes"
    if len(source.Faces()) > 400:
        raise ValueError("复杂组件超过400面，有限细化退回原实体")
    levels = [{local_bounds[axis], local_bounds[axis + 3]} for axis in range(3)]
    for face in source.Faces():
        if face.geomType() != "PLANE":
            continue
        box = bounds(face)
        for axis in range(3):
            if abs(box[axis + 3] - box[axis]) <= 1e-6:
                value = round((box[axis] + box[axis + 3]) / 2, 6)
                if local_bounds[axis] + 1e-6 < value < local_bounds[axis + 3] - 1e-6:
                    levels[axis].add(value)
    options = [(len(values), 0 if axis == 2 else 1, axis, sorted(values))
               for axis, values in enumerate(levels) if 2 < len(values) <= 16]
    if not options:
        raise ValueError("没有可可靠分层的平面边界，退回原实体")
    _, _, axis, cuts = min(options)
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    boxes, recovered_volume = [], 0.
    for lower, upper in zip(cuts, cuts[1:]):
        if upper - lower <= 1e-6:
            continue
        slab_bounds = list(local_bounds)
        for other in range(3):
            if other != axis:
                slab_bounds[other] -= 1e-4
                slab_bounds[other + 3] += 1e-4
        slab_bounds[axis], slab_bounds[axis + 3] = lower, upper
        slab = box_shape(slab_bounds)
        operation = BRepAlgoAPI_Common(source.wrapped, slab.wrapped)
        operation.SetNonDestructive(True)
        operation.Build()
        if not operation.IsDone() or operation.Shape().IsNull():
            raise ValueError("分层求交未成功，退回原实体")
        section = cq.Shape.cast(operation.Shape())
        for solid in section.Solids():
            volume = abs(float(solid.Volume()))
            if volume > 1e-8:
                recovered_volume += volume
                boxes.append(box_shape(bounds(solid)))
        if len(boxes) > 64:
            raise ValueError("细化超过64盒上限，退回原实体")
    source_volume = abs(float(source.Volume()))
    if not boxes or abs(recovered_volume - source_volume) > max(1e-4, source_volume * 1e-6):
        raise ValueError("分层没有保全原实体体积，退回原实体")
    candidate = boxes[0].fuse(*boxes[1:]) if len(boxes) > 1 else boxes[0]
    if not candidate.isValid() or not candidate.Solids() or abs(float(candidate.Volume())) >= current_volume * .999:
        raise ValueError("细化没有得到更紧的有效包络，退回原实体")
    return candidate, len(boxes), "planar_slice_boxes_" + "XYZ"[axis]


def preserve_original(component, reason):
    component.pop("candidateFile", None)
    component.update(strategy="original", preserved=True, preservationReason=reason,
                     geometryQuality="original", simplifiedVolumeMm3=component["volumeMm3"])


def resolve_envelope_false_positives(project, job_id, tolerance, output_prefix):
    """Refine once, then restore unresolved source parts without changing poses."""
    initial = copy.deepcopy(project["checks"]["falsePositivePairs"])
    if not initial:
        project.pop("envelopeRefinement", None)
        return
    affected = {value for pair in initial for value in pair["componentIds"]}
    targets = [component for component in project["components"] if component["id"] in affected and component["strategy"] != "original"]
    changes = []
    for index, component in enumerate(targets):
        progress(job_id, 80 + 5 * index / max(1, len(targets)), f"细化包络假干涉 {index + 1}/{len(targets)}：{component['name']}")
        previous = component["strategy"]
        try:
            shape, count, method = refine_envelope(source_local(project, component), component["simplifiedVolumeMm3"], component["localBoundsMm"])
            relative = f"{output_prefix}/{component['id']}-refined.step"
            write_shape(shape, project_dir(project["id"]) / relative)
            component.update(strategy="multibox", preserved=False, candidateFile=relative, boxCount=count,
                             simplifiedVolumeMm3=abs(float(shape.Volume())), geometryQuality="conservative_refined_boxes",
                             preservationReason=None)
            changes.append({"componentId": component["id"], "from": previous, "to": "multibox", "method": method,
                            "reason": "包络与原始实体判定不一致，依据实体/平面分层细化"})
        except Exception as exc:
            reason = f"包络假干涉有限细化失败，保留原实体：{exc}"
            preserve_original(component, reason)
            changes.append({"componentId": component["id"], "from": previous, "to": "original", "method": "source_fallback", "reason": reason})
    check_geometry(project, job_id, tolerance=tolerance, progress_range=(85, 90))
    unresolved = {value for pair in project["checks"]["falsePositivePairs"] for value in pair["componentIds"]}
    unresolved.update(project["checks"].get("uncertainComponentIds", []))
    restored = False
    for component in project["components"]:
        if component["id"] in unresolved and component["strategy"] != "original":
            previous = component["strategy"]
            reason = "有限细化后包络假干涉/几何检查仍未解决，保留原实体与原位姿"
            preserve_original(component, reason)
            changes.append({"componentId": component["id"], "from": previous, "to": "original", "method": "source_fallback", "reason": reason})
            restored = True
    if restored:
        check_geometry(project, job_id, tolerance=tolerance, progress_range=(90, 93))
    project["envelopeRefinement"] = {"revision": project["revision"] + 1, "attempted": True, "initialFalsePositivePairs": initial, "changes": changes,
                                     "remainingFalsePositivePairs": copy.deepcopy(project["checks"]["falsePositivePairs"]),
                                     "poseChanged": False, "status": "resolved" if not project["checks"]["falsePositivePairs"] and project["checks"]["envelopeComplete"] else "needs_review"}
    project["checks"]["envelopeRefinement"] = project["envelopeRefinement"]


def simplify(project, request, job_id, plan=None):
    requested = set(request.componentIds or [c["id"] for c in project["components"]])
    by_id = {c["id"]: c for c in project["components"]}
    unknown = requested - by_id.keys()
    if unknown:
        raise ValueError(f"未知组件：{sorted(unknown)}")
    # Contacts must be assessed on unchanged BRep before selecting simplification.
    checks = check_geometry(project, job_id, tolerance=request.contactToleranceMm, progress_range=(3, 45), source_only=True)
    touching = {value for pair in checks["contacts"] + checks["sourceCollisions"] for value in pair["componentIds"]}
    uncertain = set(checks["uncertainComponentIds"])
    operations = {item["componentId"]: item for item in (plan or {}).get("operations", [])}
    output_prefix = f"candidates/r{project['revision'] + 1}"
    for index, component_id in enumerate(sorted(requested)):
        component = by_id[component_id]
        operation = operations.get(component_id, {})
        strategy = operation.get("action") or request.strategy
        metadata = component.get("metadata", {})
        preserve_reason = None
        if strategy == "preserve":
            preserve_reason = operation.get("reason") or "方案要求保留原几何"
        elif metadata.get("thermalCritical"):
            preserve_reason = "关键热接触组件保留完整原实体"
        elif component_id in uncertain:
            preserve_reason = "几何或接触检查未确定，保留完整原实体"
        elif request.preserveContacts and component_id in touching:
            preserve_reason = "检测到真实接触或干涉，保留原实体以保留接触细节"
        source = source_local(project, component)
        if preserve_reason:
            component.update(strategy="original", preserved=True, preservationReason=preserve_reason,
                             geometryQuality="original", simplifiedVolumeMm3=component["volumeMm3"])
            component.pop("candidateFile", None)
        else:
            try:
                simplified, count = (multibox_shape(source) if strategy == "multibox" else (box_shape(component["localBoundsMm"]), 1))
                if not simplified.isValid() or not simplified.Solids():
                    raise ValueError("候选不是有效实体")
                relative = f"{output_prefix}/{component_id}.step"
                write_shape(simplified, project_dir(project["id"]) / relative)
                component.update(strategy="multibox" if count > 1 else "box", preserved=False,
                                 candidateFile=relative, preservationReason=None, simplifiedVolumeMm3=abs(float(simplified.Volume())),
                                 geometryQuality="conservative_local_bounding_box", boxCount=count,
                                 planReason=operation.get("reason"))
            except Exception as exc:
                component.update(strategy="original", preserved=True, preservationReason=f"简化失败，保留原实体：{exc}", geometryQuality="original")
                component.pop("candidateFile", None)
        progress(job_id, 45 + 20 * (index + 1) / max(1, len(requested)), f"处理组件 {index + 1}/{len(requested)}")
    project["purpose"] = request.purpose
    project["status"] = "candidate"
    check_geometry(project, job_id, tolerance=request.contactToleranceMm, progress_range=(65, 80))
    resolve_envelope_false_positives(project, job_id, request.contactToleranceMm, output_prefix)
    relative = f"r{project['revision'] + 1}/simplified.glb"
    write_glb(project, world_shapes(project), project_dir(project["id"]) / "artifacts" / relative, job_id, progress_range=(94, 98))
    project["artifacts"]["simplifiedGlb"] = artifact_url(project["id"], relative)
    project["summary"] = {"componentCount": len(project["components"]),
                          "simplifiedCount": sum(c["strategy"] != "original" for c in project["components"]),
                          "preservedCount": sum(c["strategy"] == "original" for c in project["components"]),
                          "poseChangedCount": sum(c["pose"] != c["originalPose"] for c in project["components"])}
    return project


def write_glb(project, shapes, path, job_id, progress_range=(85, 98)):
    """Write standard glTF: metre units, right handed Y up, names and component IDs."""
    document = {"asset": {"version": "2.0", "generator": "dsh-satellite-geometry", "extras": {"sourceUnits": "mm", "upAxis": "Y"}},
                "scene": 0, "scenes": [{"nodes": []}], "nodes": [], "meshes": [], "buffers": [], "bufferViews": [], "accessors": [],
                "materials": [{"name": "Source", "pbrMetallicRoughness": {"baseColorFactor": [0.56, 0.68, 0.78, 1.], "metallicFactor": 0.12, "roughnessFactor": 0.65}, "doubleSided": True},
                              {"name": "Simplified", "pbrMetallicRoughness": {"baseColorFactor": [0.12, 0.63, 0.80, 1.], "metallicFactor": 0.05, "roughnessFactor": 0.7}, "doubleSided": True}]}
    blob = bytearray()

    def accessor(array, component_type, kind, target, extrema=False):
        while len(blob) % 4:
            blob.append(0)
        offset = len(blob)
        raw = array.tobytes()
        blob.extend(raw)
        view = len(document["bufferViews"])
        document["bufferViews"].append({"buffer": 0, "byteOffset": offset, "byteLength": len(raw), "target": target})
        result = {"bufferView": view, "componentType": component_type, "count": len(array), "type": kind}
        if extrema:
            result.update(min=array.min(axis=0).tolist(), max=array.max(axis=0).tolist())
        index = len(document["accessors"])
        document["accessors"].append(result)
        return index

    for index, component in enumerate(project["components"]):
        shape = shapes[component["id"]]
        dimensions = component["dimensionsMm"]
        tolerance = max(0.5, min(3., max(dimensions) / 250.))
        vertices, triangles = shape.tessellate(tolerance, 0.25)
        if not triangles:
            raise ValueError(f"组件 {component['id']} 未生成可显示网格")
        points = np.array([[v.x / 1000., v.z / 1000., -v.y / 1000.] for v in vertices], dtype="<f4")
        indices = np.asarray(triangles, dtype="<u4").reshape(-1)
        positions = accessor(points, 5126, "VEC3", 34962, True)
        elements = accessor(indices, 5125, "SCALAR", 34963)
        mesh = len(document["meshes"])
        document["meshes"].append({"name": component["name"], "primitives": [{"attributes": {"POSITION": positions}, "indices": elements,
                                                                                      "material": 0 if component["strategy"] == "original" else 1}]})
        node = len(document["nodes"])
        document["nodes"].append({"mesh": mesh, "name": f"{component['id']} {component['name']}",
                                  "extras": {"componentId": component["id"], "prototypeId": component["prototypeId"]}})
        document["scenes"][0]["nodes"].append(node)
        progress(job_id, progress_range[0] + (progress_range[1] - progress_range[0]) * (index + 1) / len(project["components"]), f"生成三维预览 {index + 1}/{len(project['components'])}")
    while len(blob) % 4:
        blob.append(0)
    document["buffers"] = [{"byteLength": len(blob)}]
    json_bytes = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    json_bytes += b" " * ((-len(json_bytes)) % 4)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.write(struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(json_bytes) + 8 + len(blob)))
        handle.write(struct.pack("<I4s", len(json_bytes), b"JSON"))
        handle.write(json_bytes)
        handle.write(struct.pack("<I4s", len(blob), b"BIN\x00"))
        handle.write(blob)


def export_project(project, job_id):
    from service.modeling import ensure_workbench, geometry_evidence
    ensure_workbench(project)
    cq = cq_module()
    revision = project["revision"]
    relative_root = f"r{revision}"
    target = project_dir(project["id"]) / "artifacts" / relative_root
    target.mkdir(parents=True, exist_ok=True)
    assembly = cq.Assembly(name="Satellite_simplified")
    local_shapes, shapes, topology_evidence = {}, {}, {}
    invalid_source_ids, invalid_preserved_ids = [], []
    for index, component in enumerate(project["components"]):
        progress(job_id, 2 + 10 * index / len(project["components"]), f"准备共享原型导出 {index + 1}/{len(project['components'])}：{component['name']}")
        relative = component.get("candidateFile") or component["sourceFile"]
        if relative not in local_shapes:
            local_shapes[relative] = read_shape(project_dir(project["id"]) / relative)
        local = local_shapes[relative]
        if component.get("strategy") == "recipe":
            evidence = geometry_evidence(local, component["recipe"]["representation"])
            if component["recipe"]["representation"] != "source" and not evidence["passed"]:
                raise ValueError(f"单机 {component['id']} 表示类型检查失败")
        shapes[component["id"]] = shape_transform(local, component["pose"])
        if relative not in topology_evidence:
            if component["strategy"] == "original" and "sourceTopologyValid" in component:
                topology_evidence[relative] = component["sourceTopologyValid"]
            elif component["strategy"] == "original" and component.get("sourceValid"):
                topology_evidence[relative] = True  # Earlier import already tested isValid().
            else:
                topology_evidence[relative] = bool(local.isValid())
        if component["strategy"] == "original":
            component["sourceTopologyValid"] = topology_evidence[relative]
        if not topology_evidence[relative]:
            if component["strategy"] != "original":
                raise ValueError(f"简化候选 {component['id']} 出现拓扑缺陷，未发布输出")
            invalid_preserved_ids.append(component["id"])
        if component.get("sourceTopologyValid") is False:
            invalid_source_ids.append(component["id"])
    by_id = {component["id"]: component for component in project["components"]}
    tree = {node["id"]: node for node in project["tree"]}
    exported_ids = set()

    def add_tree(node_id, parent):
        import re
        node = tree[node_id]
        name = re.sub(r"[^\w.-]+", "_", f"{node_id}_{node['name']}")
        if node_id in by_id:
            if node_id in exported_ids:
                raise ValueError("工作装配树重复引用同一组件")
            component = by_id[node_id]
            relative = component.get("candidateFile") or component["sourceFile"]
            # CadQuery/XCAF reuses a part only when the same local object is
            # referenced. Keep occurrence placement in Location instead of
            # creating a different world-located shape object for every copy.
            parent.add(local_shapes[relative], name=name, loc=location_from_pose(component["pose"]), color=cq.Color(0.3, 0.6, 0.8))
            exported_ids.add(node_id)
            progress(job_id, 12 + 8 * len(exported_ids) / len(by_id), "按工作装配树建立命名子装配与共享原型")
            return True
        group = cq.Assembly(name=name)
        populated = False
        for child_id in node["children"]:
            populated = add_tree(child_id, group) or populated
        if populated:
            # Working groups have identity transforms; leaf Locations contain
            # world placements, preserving the original/candidate poses.
            parent.add(group, name=name)
        return populated

    for node_id in project.get("rootIds", [n["id"] for n in project["tree"] if n["parentId"] is None]):
        add_tree(node_id, assembly)
    if exported_ids != by_id.keys():
        raise ValueError("工作装配树缺少组件，不能导出不完整装配")
    step_path = target / "simplified.step"
    assembly.export(str(step_path), exportType="STEP", mode="default")
    invalidate_shape_cache(step_path)
    # Verify named occurrence coverage independently of geometric validity.
    occurrence_tree = parse_step_occurrences(step_path)
    occurrence_ids, prototype_ids = [], set()
    for occurrence in occurrence_tree.occurrences:
        component_id = occurrence.relationship_name.split("_", 1)[0]
        if component_id in by_id:
            occurrence_ids.append(component_id)
            prototype_ids.add(occurrence.child_definition_id)
    if set(occurrence_ids) != set(by_id) or len(occurrence_ids) != len(by_id):
        raise ValueError("导出 STEP 实例映射缺失或重复，不能发布不完整装配")
    # A readable file and valid topology are different claims. Existing invalid
    # source parts may be exported for repair/review, with their defect retained
    # explicitly. A new failure from fully valid inputs remains a failed export.
    exported = read_step_fresh(step_path)
    readback_valid = bool(exported.isValid())
    source_topology_valid = not invalid_source_ids
    if not readback_valid and (not invalid_preserved_ids or project.get("equipmentEnvelopeRebuild")):
        raise ValueError("有效源几何导出后出现新的拓扑检查失败，未发布输出")
    expected_solids = sum(len(local_shapes[c.get("candidateFile") or c["sourceFile"]].Solids()) for c in project["components"])
    if len(exported.Solids()) != expected_solids:
        raise ValueError("STEP 回读实体数量发生变化，面壳/实体表示未保持")
    export_warnings = []
    if not source_topology_valid:
        export_warnings.append("原始输入已有拓扑缺陷，源证据完整保留；输出有效性按当前实体和STEP回读另行判断，不能据此宣称热工程验收通过")
    if not readback_valid:
        export_warnings.append("STEP 可读取，但回读拓扑检查未通过；没有认证所有源缺陷与输出缺陷一一对应")
    progress(job_id, 55, "STEP 可读取；源拓扑缺陷已记录，生成待复核产物" if not readback_valid else "STEP 回读检查完成，生成预览与属性/接触清单")
    write_glb(project, shapes, target / "simplified.glb", job_id, progress_range=(57, 86))
    attribute_report = {"schemaVersion": 2, "projectId": project["id"], "revision": revision,
                        "source": project["source"], "units": "mm", "coordinateSystem": project["coordinateSystem"],
                        "components": project["components"], "sourceTree": project.get("sourceTree", project["tree"]),
                        "workingTree": project["tree"], "checks": project["checks"],
                        "workflowBindings": project.get("workflowBindings", {}), "feedbackRecords": project.get("feedbackRecords", []),
                        "geometryVolumeIsPhysicalMassProxy": False,
                        "envelopeRefinement": project.get("envelopeRefinement"),
                        "equipmentEnvelopeRebuild": project.get("equipmentEnvelopeRebuild"),
                        "export": {"stepSha256": source_hash(step_path), "stepReadable": True, "stepReadbackValid": readback_valid,
                                   "sourceTopologyValid": source_topology_valid, "invalidSourceComponentIds": invalid_source_ids,
                                   "invalidPreservedComponentIds": invalid_preserved_ids,
                                   "outputFaceCount": len(exported.Faces()) if hasattr(exported, "Faces") else None,
                                   "outputSolidCount": len(exported.Solids()) if hasattr(exported, "Solids") else None,
                                   "stepOccurrenceCount": len(occurrence_ids), "stepPrototypeCount": len(prototype_ids),
                                   "instanceStructureVerified": True, "exportedAt": now(), "warnings": export_warnings,
                                   "representationReadbackVerified": True,
                                   "status": "equivalent_geometry_valid_thermal_network_pending" if readback_valid and project.get("equipmentEnvelopeRebuild") else "valid" if readback_valid and source_topology_valid else "source_and_output_invalid_review_required" if not readback_valid else "source_defects_review_required",
                                   "acceptanceIsSeparate": True}}
    atomic_json(target / "properties.json", attribute_report)
    atomic_json(target / "contacts.json", {"schemaVersion": 2, "revision": revision, "contacts": project["thermalContacts"],
                                          "sourceGeometricCandidates": project["checks"].get("contacts", []),
                                          "complete": project.get("contactDiscovery", {}).get("status") == "completed",
                                          "thermalContacts": project["checks"].get("thermalContacts", "source_geometry_candidates"),
                                          "potentialEnvelopePairs": project["checks"].get("potentialEnvelopePairs", []),
                                          "warnings": project["checks"].get("warnings", [])})
    atomic_json(target / "recipes.json", {"schemaVersion": 1, "revision": revision,
        "components": [{"id": c["id"], "displayName": c["displayName"], "recipe": c["recipe"],
                        "fingerprint": c["recipeFingerprint"], "pose": c["pose"],
                        "installationRegions": c.get("installationRegions", [])} for c in project["components"]]})
    from service.workbench import session_records
    atomic_json(target / "feedback.json", {"revision": revision, "autoSkillUpdate": False,
                                          "changes": project["feedbackRecords"], "sessionRecords": session_records(project["id"])})
    project["artifacts"].update(step=artifact_url(project["id"], f"{relative_root}/simplified.step"),
                                 simplifiedGlb=artifact_url(project["id"], f"{relative_root}/simplified.glb"),
                                 report=artifact_url(project["id"], f"{relative_root}/properties.json"),
                                 contacts=artifact_url(project["id"], f"{relative_root}/contacts.json"))
    project["artifacts"]["recipes"] = artifact_url(project["id"], f"{relative_root}/recipes.json")
    import zipfile
    archive = target / "satellite-package.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name in ("simplified.step", "simplified.glb", "properties.json", "contacts.json", "recipes.json", "feedback.json"):
            bundle.write(target / name, name)
    project["artifacts"]["bundle"] = artifact_url(project["id"], f"{relative_root}/satellite-package.zip")
    project["lastExport"] = attribute_report["export"]
    return project
