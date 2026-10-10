"""Immutable workflow packages shared by the UI, DSH binding and external callers."""
from __future__ import annotations

from pathlib import Path, PurePosixPath
from service import storage as db
from service.modeling import fingerprint


DEFAULT_PATH = Path(__file__).parent / "resources" / "thermal-modeling" / "SKILL.md"


def add_skill(label, content, resources=None):
    resources = resources or {}
    if not content.strip() or len(content) > 500_000:
        raise ValueError("Skill 正文须为非空且小于 500KB")
    for name, text in resources.items():
        candidate = PurePosixPath(name)
        if candidate.is_absolute() or ".." in candidate.parts or "\\" in name or ":" in name or not isinstance(text, str):
            raise ValueError("Skill 资源必须为安全相对路径及文本内容")
    if sum(len(text) for text in resources.values()) > 2_000_000:
        raise ValueError("Skill 资源超过 2MB")
    sha = fingerprint({"content": content, "resources": resources})
    skill = {"id": f"skill-{sha[:24]}", "label": label, "fingerprint": sha,
             "content": content, "resources": resources, "createdAt": db.now(), "immutable": True}
    target = db.ROOT / "skills" / f"{skill['id']}.json"
    if target.exists():
        return db.read_json(target)
    db.atomic_json(target, skill)
    return skill


def default_skill():
    return add_skill("热设计工作流 0.3", DEFAULT_PATH.read_text(encoding="utf-8"))


def get_skill(skill_id):
    db.safe_id(skill_id)
    skill = db.read_json(db.ROOT / "skills" / f"{skill_id}.json")
    if fingerprint({"content": skill["content"], "resources": skill["resources"]}) != skill["fingerprint"]:
        raise ValueError("Skill 内容指纹不一致")
    return skill


def list_skills():
    with db.LOCK:
        default_skill()
        return [{k: item[k] for k in ("id", "label", "fingerprint", "createdAt", "immutable")}
                for item in sorted((db.read_json(path) for path in (db.ROOT / "skills").glob("*.json")),
                                   key=lambda value: value["createdAt"], reverse=True)]
