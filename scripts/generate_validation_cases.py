"""Small, auditable CAD cases for behavior checks, alongside real source cases.

Units: mm; Z up. The contact case deliberately distinguishes source contact
from envelope contact and includes an object inside a false envelope collision.
"""
from pathlib import Path
import json
import cadquery as cq

TARGET = Path(__file__).resolve().parents[1] / "validation" / "fixtures"
TARGET.mkdir(parents=True, exist_ok=True)


def contact_case():
    assembly = cq.Assembly(name="Contact_preservation_case")
    plate = cq.Workplane("XY").box(100, 100, 4).translate((0, 0, 2)).val()
    device = cq.Workplane("XY").box(40, 40, 20).translate((0, 0, 20))
    for x in (-16, 16):
        for y in (-16, 16):
            foot = cq.Workplane("XY").box(3, 3, 6).translate((x, y, 7))
            device = device.union(foot)
    between_feet = cq.Workplane("XY").box(8, 8, 3).translate((0, 0, 5.5)).val()
    assembly.add(plate, name="Mounting_plate")
    assembly.add(device.val(), name="Four_foot_device")
    assembly.add(between_feet, name="Between_feet_sensor")
    assembly.export(str(TARGET / "contact.step"), exportType="STEP")
    return {
        "file": "contact.step", "units": "mm", "componentCount": 3,
        "sourceCollisionCount": 0,
        "footContactAreaMm2": 36,
        "knownFalseEnvelopePair": ["Four_foot_device", "Between_feet_sensor"],
        "boundsMm": [-50, -50, 0, 50, 50, 30],
        "required": "Preserve the 4-foot thermal connection; never move a source component to fix envelope-only overlap.",
    }


def instances_case():
    part = cq.Workplane("XY").box(10, 6, 4).val()
    children = cq.Assembly(name="Rotated_subassembly", loc=cq.Location((20, 10, 5), (0, 0, 1), 30))
    children.add(part, name="Repeated_A", loc=cq.Location((0, 0, 0)))
    children.add(part, name="Repeated_B", loc=cq.Location((0, 18, 0)))
    assembly = cq.Assembly(name="Instance_pose_case")
    assembly.add(children)
    assembly.add(part, name="Repeated_C", loc=cq.Location((-20, -10, 5), (1, 0, 0), 90))
    assembly.export(str(TARGET / "instances.step"), exportType="STEP")
    box = assembly.toCompound().BoundingBox()
    return {
        "file": "instances.step", "units": "mm", "componentCount": 3,
        "boundsMm": [box.xmin, box.ymin, box.zmin, box.xmax, box.ymax, box.zmax],
        "required": "Retain each distinct occurrence and nested rigid transform; do not deduplicate different placements.",
    }


if __name__ == "__main__":
    cases = [contact_case(), instances_case()]
    (TARGET / "expected.json").write_text(json.dumps(cases, indent=2), encoding="utf-8")
    print(json.dumps(cases, indent=2))
