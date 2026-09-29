"""STEP occurrence metadata and semantic component-boundary rules."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


SELECTION_STRATEGY = "semantic-top-down-prototypes-v3"
TRANSLATION_PRECISION = 4
ROTATION_PRECISION = 9

_X2_LITERAL = re.compile(r"_X2_([0-9A-F]+)_X0_", re.IGNORECASE)
_X2_STEP = re.compile(r"\\X2\\([0-9A-F]+)\\X0\\", re.IGNORECASE)
_OCCURRENCE = re.compile(
    r"#(?P<entity>\d+)\s*=\s*NEXT_ASSEMBLY_USAGE_OCCURRENCE\s*\("
    r"\s*'(?P<occurrence>(?:''|[^'])*)'\s*,"
    r"\s*'(?P<relationship>(?:''|[^'])*)'\s*,"
    r"\s*'(?P<description>(?:''|[^'])*)'\s*,"
    r"\s*#(?P<parent>\d+)\s*,\s*#(?P<child>\d+)\s*,\s*\$\s*\)\s*;",
    re.DOTALL,
)
_GENERIC_NAME = re.compile(
    r"^(?:next\s+assembly\s+relationship|=>\[[^]]+\])$", re.IGNORECASE
)
_DATED_ASSEMBLY = re.compile(r"^\d{6,}(?:[-_].*)?(?:asm|装配体)", re.IGNORECASE)
_TECHNICAL_FILE = re.compile(r"(?:^|[_-])(?:asm|step|stp)(?:$|[_-])", re.IGNORECASE)


def _decode_utf16_hex(value: str) -> str:
    try:
        return bytes.fromhex(value).decode("utf-16-be")
    except (UnicodeDecodeError, ValueError):
        return value


def decode_step_name(value: str | None) -> str:
    """Decode common STEP/XCAF UTF-16 escape forms without altering plain text."""
    result = str(value or "").replace("''", "'").strip()
    result = _X2_LITERAL.sub(lambda match: _decode_utf16_hex(match.group(1)), result)
    result = _X2_STEP.sub(lambda match: _decode_utf16_hex(match.group(1)), result)
    return result.strip()


def is_generic_name(value: str | None) -> bool:
    return not value or bool(_GENERIC_NAME.fullmatch(decode_step_name(value)))


def is_structural_container_name(value: str | None) -> bool:
    """Return whether a node lacks a decoded name and must still be traversed."""
    name = decode_step_name(value)
    if is_generic_name(name) or _DATED_ASSEMBLY.search(name):
        return True
    if _TECHNICAL_FILE.search(name) and not re.search(r"[\u3400-\u9fff]", name):
        return True
    return False


def is_meaningful_name(value: str | None) -> bool:
    name = decode_step_name(value)
    if is_generic_name(name):
        return False
    return bool(re.search(r"[\u3400-\u9fff]", name) or re.search(r"[A-Za-z]{2,}", name))


@dataclass(frozen=True)
class StepOccurrence:
    entity_id: str
    occurrence_id: str
    relationship_name: str
    description: str
    parent_definition_id: str
    child_definition_id: str


@dataclass(frozen=True)
class ResolvedNodeName:
    name: str
    source: str
    status: str


def coordinate_key(coordinate: dict | None) -> tuple[float, ...]:
    """Return a tolerance-normalized rigid-pose key for occurrence auditing."""
    coordinate = coordinate or {}
    origin = coordinate.get("originMm") or (0.0, 0.0, 0.0)
    axes = [
        coordinate.get(name) or fallback
        for name, fallback in (
            ("xAxis", (1.0, 0.0, 0.0)),
            ("yAxis", (0.0, 1.0, 0.0)),
            ("zAxis", (0.0, 0.0, 1.0)),
        )
    ]
    return (
        *(round(float(value), TRANSLATION_PRECISION) for value in origin),
        *(
            round(float(value), ROTATION_PRECISION)
            for axis in axes
            for value in axis
        ),
    )


def occurrence_identity(node: dict) -> tuple[str, tuple[float, ...]] | None:
    """Identify one physical occurrence without collapsing positioned instances."""
    definition_id = node.get("stepDefinitionId")
    if not definition_id:
        return None
    return str(definition_id), coordinate_key(node.get("coordinateSystem"))


def deduplicate_exact_occurrences(nodes: list[dict]) -> tuple[list[dict], dict]:
    """Keep the first definition+pose occurrence and report exact overlaps."""
    retained: list[dict] = []
    representatives: dict[tuple[str, tuple[float, ...]], dict] = {}
    duplicate_of: dict[str, str] = {}
    groups: dict[str, list[str]] = {}
    for node in nodes:
        identity = occurrence_identity(node)
        if identity is None or identity not in representatives:
            retained.append(node)
            if identity is not None:
                representatives[identity] = node
            continue
        representative = representatives[identity]
        duplicate_of[node["id"]] = representative["id"]
        groups.setdefault(representative["id"], []).append(node["id"])
    for representative_id, duplicate_ids in groups.items():
        representative = next(node for node in retained if node["id"] == representative_id)
        representative["duplicateOccurrenceIds"] = duplicate_ids
    return retained, {
        "exactDuplicateCount": len(duplicate_of),
        "duplicateOf": duplicate_of,
        "groups": groups,
        "translationToleranceMm": 10 ** -TRANSLATION_PRECISION,
        "rotationTolerance": 10 ** -ROTATION_PRECISION,
    }


class StepOccurrenceTree:
    def __init__(self, occurrences: list[StepOccurrence]):
        self.occurrences = occurrences
        self._children: dict[str, list[StepOccurrence]] = {}
        child_definitions: set[str] = set()
        for occurrence in occurrences:
            self._children.setdefault(occurrence.parent_definition_id, []).append(
                occurrence
            )
            child_definitions.add(occurrence.child_definition_id)
        self.root_definition_ids = [
            definition_id
            for definition_id in self._children
            if definition_id not in child_definitions
        ]

    def children(self, definition_id: str | None) -> list[StepOccurrence]:
        return list(self._children.get(definition_id or "", ()))

    def match_root_definitions(self, child_counts: list[int]) -> list[str | None]:
        remaining = list(self.root_definition_ids)
        result: list[str | None] = []
        for count in child_counts:
            matching = [item for item in remaining if len(self.children(item)) == count]
            selected = matching[0] if matching else (remaining[0] if remaining else None)
            result.append(selected)
            if selected in remaining:
                remaining.remove(selected)
        return result


def parse_step_occurrences(path: Path) -> StepOccurrenceTree:
    """Read NEXT_ASSEMBLY_USAGE_OCCURRENCE statements without loading the file."""
    occurrences: list[StepOccurrence] = []
    statement = ""
    collecting = False
    with path.open("r", encoding="utf-8", errors="replace") as source:
        for line in source:
            if not collecting:
                if "NEXT_ASSEMBLY_USAGE_OCCURRENCE" not in line:
                    continue
                statement = line
                collecting = ";" not in line
            else:
                statement += line
                collecting = ";" not in line
            if collecting:
                continue
            match = _OCCURRENCE.search(statement)
            if match:
                occurrences.append(StepOccurrence(
                    entity_id=match.group("entity"),
                    occurrence_id=match.group("occurrence").replace("''", "'"),
                    relationship_name=decode_step_name(match.group("relationship")),
                    description=decode_step_name(match.group("description")),
                    parent_definition_id=match.group("parent"),
                    child_definition_id=match.group("child"),
                ))
            statement = ""
    return StepOccurrenceTree(occurrences)


def resolve_node_name(
    *,
    occurrence: StepOccurrence | None,
    label_name: str,
    target_name: str,
    fallback: str,
) -> ResolvedNodeName:
    candidates = (
        (occurrence.description if occurrence else "", "step_occurrence_description"),
        (label_name, "xcaf_occurrence_label"),
        (target_name, "xcaf_product_label"),
    )
    for raw_name, source in candidates:
        name = decode_step_name(raw_name)
        if is_meaningful_name(name):
            return ResolvedNodeName(name=name, source=source, status="resolved")
    decoded_fallback = decode_step_name(label_name or target_name)
    if decoded_fallback and not is_generic_name(decoded_fallback):
        return ResolvedNodeName(
            name=decoded_fallback, source="technical_label", status="technical"
        )
    return ResolvedNodeName(
        name=f"未命名组件_{fallback}", source="generated_fallback", status="unresolved"
    )
