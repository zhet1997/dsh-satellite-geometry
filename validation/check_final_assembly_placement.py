"""Independent read-only XCAF placement/bounds audit for the exported assembly."""
from pathlib import Path
import hashlib
import itertools
import json
import re

import cadquery as cq
import numpy as np
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDF import TDF_Label, TDF_LabelSequence
from OCP.TDocStd import TDocStd_Document
from OCP.TopLoc import TopLoc_Location
from OCP.XCAFDoc import XCAFDoc_DocumentTool
from OCP.gp import gp_Trsf

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "validation/artifacts/satellite-assembly-container"


def read_json(path):
    raw = path.read_bytes()
    return json.loads(raw.decode("utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"))


def matrix(location):
    t = location.Transformation()
    return np.array([[t.Value(r, c) for c in range(1, 5)] for r in range(1, 4)])


def pose_location(pose):
    t = gp_Trsf()
    t.SetValues(*np.column_stack((pose["rotation"], pose["translationMm"])).reshape(-1).tolist())
    return TopLoc_Location(t)


def geometric_bounds(shape):
    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape.wrapped, box, False, False)
    return list(box.Get())


def transformed_box(box, pose):
    corners = np.array(list(itertools.product(*zip(box[:3], box[3:]))))
    points = corners @ np.array(pose["rotation"]).T + pose["translationMm"]
    return points.min(0).tolist() + points.max(0).tolist()


def max_delta(a, b):
    return float(np.max(np.abs(np.asarray(a) - np.asarray(b))))


properties = read_json(ART / "properties.json")
components = {c["id"]: c for c in properties["components"]}
project_root = ROOT / "data/projects" / properties["projectId"]
raw_cad = read_json(ROOT / "validation/assembly-final-all.raw.json")
cad_leaves = {}
for token in raw_cad["tokens"]:
    selected = token["selections"][0]
    cid = re.match(r"N\d+", selected["summary"])[0]
    cad_leaves[cid] = selected

reader = STEPCAFControl_Reader()
reader.SetNameMode(True)
assert "RetDone" in str(reader.ReadFile(str(ART / "simplified.step")))
document = TDocStd_Document(TCollection_ExtendedString("independent-validation"))
assert reader.Transfer(document)
shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
leaves = {}


def label_name(label):
    attr = TDataStd_Name()
    return attr.Get().ToExtString() if label.FindAttribute(TDataStd_Name.GetID_s(), attr) else ""


def visit(label, parent):
    referred = TDF_Label()
    target = referred if shape_tool.GetReferredShape_s(label, referred) else label
    native = shape_tool.GetShape_s(label)
    world = parent.Multiplied(native.Location())
    children = TDF_LabelSequence()
    if shape_tool.IsAssembly_s(target):
        shape_tool.GetComponents_s(target, children, False)
    if children.Length():
        for i in range(1, children.Length() + 1):
            visit(children.Value(i), world)
    else:
        name = label_name(label) or label_name(target)
        cid = re.match(r"N\d+", name)[0]
        assert cid not in leaves
        leaves[cid] = (name, cq.Shape.cast(native.Located(world)), world)


roots = TDF_LabelSequence()
shape_tool.GetFreeShapes(roots)
for i in range(1, roots.Length() + 1):
    visit(roots.Value(i), TopLoc_Location())
assert set(leaves) == set(components) == set(cad_leaves)
print(f"Read final STEP: {len(leaves)} named leaf instances", flush=True)

loaded = {}
records = []
for i, (cid, component) in enumerate(components.items(), 1):
    name, actual, world = leaves[cid]
    pose = component["pose"]
    expected_matrix = np.column_stack((pose["rotation"], pose["translationMm"]))
    selected = cad_leaves[cid]["positioning"]
    cad_matrix = np.array(selected["transform"]).reshape(4, 4)[:3]
    cad_bounds = selected["bbox"]["min"] + selected["bbox"]["max"]
    actual_bounds = geometric_bounds(actual)
    relative = component.get("candidateFile") or component["sourceFile"]
    source = project_root / relative
    if component.get("candidateFile") and not source.exists():
        source = ART / "candidates" / Path(relative).name
    record = {
        "id": cid, "name": component["name"], "strategy": component["strategy"],
        "relativeShapeFile": relative,
        "xcafPoseMaxAbsDelta": max_delta(matrix(world), expected_matrix),
        "cadRoundedPoseMaxAbsDelta": max_delta(cad_matrix, expected_matrix),
        "cadConservativeBoundsMm": cad_bounds,
        "actualGeometricBoundsMm": actual_bounds,
        "projectStoredBoundsMm": component["boundsMm"],
        "cadVsActualBoundsMaxAbsDeltaMm": max_delta(cad_bounds, actual_bounds),
        "actualVsStoredBoundsMaxAbsDeltaMm": max_delta(actual_bounds, component["boundsMm"]),
    }
    if source.exists():
        if relative not in loaded:
            shape = cq.importers.importStep(str(source)).val()
            loaded[relative] = shape
            source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            if not component.get("candidateFile"):
                assert source_hash == component["sourceHash"], f"source mismatch {relative}"
        local = loaded[relative]
        expected = cq.Shape.cast(local.wrapped.Moved(pose_location(pose)))
        expected_bounds = geometric_bounds(expected)
        transformed_local = transformed_box(geometric_bounds(local), pose)
        record.update(
            expectedGeometricBoundsMm=expected_bounds,
            geometricBoundsMaxAbsDeltaMm=max_delta(actual_bounds, expected_bounds),
            localShapeLocationMatrix=matrix(local.wrapped.Location()).tolist(),
            transformedLocalAabbMm=transformed_local,
            transformedAabbVsCadBoundsMaxAbsDeltaMm=max_delta(transformed_local, cad_bounds),
            expectedFaceCount=len(expected.Faces()), actualFaceCount=len(actual.Faces()),
        )
    else:
        record["geometryComparisonMissing"] = str(source)
    records.append(record)
    if i % 25 == 0:
        print(f"Compared {i}/{len(components)}", flush=True)

complete = [r for r in records if "geometricBoundsMaxAbsDeltaMm" in r]
max_pose = max(r["xcafPoseMaxAbsDelta"] for r in records)
max_bounds = max(r["geometricBoundsMaxAbsDeltaMm"] for r in complete)
max_cad_pose = max(r["cadRoundedPoseMaxAbsDelta"] for r in records)
same_faces = all(r["actualFaceCount"] == r["expectedFaceCount"] for r in complete)
report = {
    "method": "Independent OCP STEPCAF read; all named leaf world matrices vs project pose; BRepBndLib.AddOptimal(useTriangulation=False,useShapeTolerance=False) on final world BRep and independently imported source/candidate moved exactly once by project pose.",
    "stepSha256": hashlib.sha256((ART / "simplified.step").read_bytes()).hexdigest(),
    "artifact": "validation/artifacts/satellite-assembly-container/simplified.step",
    "leafCount": len(leaves), "geometryComparedCount": len(complete),
    "maxWorldMatrixAbsoluteDelta": max_pose,
    "maxCadRoundedMatrixAbsoluteDelta": max_cad_pose,
    "maxWorldGeometricBoundsAbsoluteDeltaMm": max_bounds,
    "allComparedFaceCountsMatch": same_faces,
    "worldGeometryPlacementVerified": len(complete) == len(records) and max_pose < 1e-8 and max_bounds < 1e-3 and same_faces,
    "units": "mm",
    "boundsMethodExplanation": "CAD inspector transforms each prototype local AABB, a conservative box under rotation; these bounds need not equal the tight bounds measured on transformed BRep geometry. CAD curve/mesh prototype bounds can differ additionally.",
    "highestInstances": sorted(records, key=lambda r: r["actualGeometricBoundsMm"][5], reverse=True)[:4],
    "instances": records,
}
assert report["stepSha256"] == properties["export"]["stepSha256"] == raw_cad["tokens"][0]["stepHash"]
report["stepSha256MatchesPropertiesAndExportAndCadInspection"] = True
report["actualMergedGeometricBoundsMm"] = [min(r["actualGeometricBoundsMm"][i] for r in records) for i in range(3)] + [max(r["actualGeometricBoundsMm"][i] for r in records) for i in range(3, 6)]
report["allLocalShapeRootLocationsIdentity"] = all(max(abs(value - (1 if row == col else 0)) for row, values in enumerate(r["localShapeLocationMatrix"]) for col, value in enumerate(values)) < 1e-12 for r in complete)
(ROOT / "validation/assembly-final-placement-check.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps({k: v for k, v in report.items() if k not in ("instances", "highestInstances")}, indent=2), flush=True)
