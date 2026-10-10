"""Public equipment workflow operations; UI, MCP and external clients share these."""
from __future__ import annotations

import copy
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from service import storage as db
from service import modeling as model
from service import skill_versions as skills

router = APIRouter(prefix="/api")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_default=True)


class Revision(Strict):
    revision: int = Field(ge=0)


class AuditContext(Strict):
    sessionId: str | None = None
    skillFingerprint: str | None = None
    selectionRef: str | None = None
    feedback: str | None = Field(default=None, max_length=20000)


class Evidence(Strict):
    documentId: str
    quote: str = Field(min_length=1, max_length=4000)
    field: str = "recipe"
    reference: str | None = None


class Part(Strict):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,60}$")
    name: str = Field(default="主体", max_length=200)
    kind: Literal["source", "box", "cylinder"]
    centerMm: list[float] = Field(default_factory=lambda: [0, 0, 0], min_length=3, max_length=3)
    sizeMm: list[float] | None = Field(default=None, min_length=3, max_length=3)
    radiusMm: float | None = Field(default=None, gt=0, le=100000)
    heightMm: float | None = Field(default=None, gt=0, le=100000)
    axis: list[float] = Field(default_factory=lambda: [0, 0, 1], min_length=3, max_length=3)

    @model_validator(mode="after")
    def dimensions(self):
        if self.kind == "box" and (not self.sizeMm or any(v <= 0 or v > 100000 for v in self.sizeMm)):
            raise ValueError("盒体必须提供三个正尺寸 sizeMm")
        if self.kind == "cylinder" and (self.radiusMm is None or self.heightMm is None or sum(v*v for v in self.axis) < 1e-12):
            raise ValueError("圆柱必须提供 radiusMm、heightMm 和非零 axis")
        return self


class Thermal(Strict):
    thicknessMm: float | None = Field(default=None, gt=0)
    material: str | None = Field(default=None, max_length=500)
    massKg: float | None = Field(default=None, ge=0)
    specificHeatJPerKgK: float | None = Field(default=None, ge=0)
    conductivityWPerMK: float | None = Field(default=None, ge=0)
    powerW: float | None = Field(default=None, ge=0)


class Region(Strict):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,60}$")
    name: str = Field(default="安装区域", max_length=200)
    partId: str
    selector: Literal["xmin", "xmax", "ymin", "ymax", "zmin", "zmax", "lateral", "all"]


class Recipe(Strict):
    schemaVersion: Literal[1] = 1
    representation: Literal["source", "solid", "surface_shell"]
    parts: list[Part] = Field(min_length=1, max_length=100)
    thermal: Thermal = Field(default_factory=Thermal)
    regions: list[Region] = Field(default_factory=list, max_length=100)
    dimensionBasis: str = Field(min_length=1, max_length=8000)
    notes: str = Field(default="", max_length=16000)
    sources: list[Evidence] = Field(default_factory=list)
    legacyCandidateFile: str | None = None

    @model_validator(mode="after")
    def identities(self):
        ids = {part.id for part in self.parts}
        if len(ids) != len(self.parts) or len({r.id for r in self.regions}) != len(self.regions):
            raise ValueError("方案组成/区域 ID 不可重复")
        if any(region.partId not in ids for region in self.regions):
            raise ValueError("区域必须引用当前方案中的组成")
        if self.representation == "source" and (len(self.parts) != 1 or self.parts[0].kind != "source"):
            raise ValueError("source 表示必须为单一源几何组成")
        return self


class Change(Strict):
    componentId: str
    recipe: Recipe
    reason: str = Field(min_length=1, max_length=8000)


class Rebuild(Revision):
    changes: list[Change] = Field(min_length=1, max_length=2000)
    context: AuditContext | None = None


class CopyRecipe(Revision):
    name: str = Field(min_length=1, max_length=200)
    context: AuditContext | None = None


class LoadCopy(Revision):
    context: AuditContext | None = None


class ContactSide(Strict):
    componentId: str
    regionId: str | None = None


class Contact(Strict):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    a: ContactSide
    b: ContactSide
    status: Literal["candidate", "confirmed", "needs_review", "excluded"] = "candidate"
    origin: Literal["manual", "document", "geometry"] = "manual"
    areaMm2: float | None = Field(default=None, ge=0)
    conductanceWPerK: float | None = Field(default=None, ge=0)
    evidence: str = Field(min_length=1, max_length=8000)
    sources: list[Evidence] = Field(default_factory=list)


class ContactUpdate(Revision):
    contacts: list[Contact] = Field(min_length=1, max_length=2000)
    context: AuditContext | None = None


class Identity(Strict):
    componentId: str
    displayName: str = Field(min_length=1, max_length=60)
    engineeringGroup: Literal["结构", "单机", "附件", "待分类"] = "单机"
    nameStatus: Literal["identified", "candidate", "unidentified"] = "candidate"
    basis: str = Field(min_length=1, max_length=8000)
    sources: list[Evidence] = Field(default_factory=list)


class Identities(Revision):
    components: list[Identity] = Field(min_length=1, max_length=2000)
    context: AuditContext | None = None


class NewSkill(Strict):
    label: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=500000)
    resources: dict[str, str] = Field(default_factory=dict)


class BindSkill(Revision):
    sessionId: str = Field(min_length=1, max_length=200)
    skillId: str
    componentIds: list[str] = Field(default_factory=list, max_length=2000)


class Feedback(Revision):
    componentIds: list[str] = Field(default_factory=list, max_length=2000)
    reason: str = Field(min_length=1, max_length=20000)
    context: AuditContext | None = None


def ready(project_id, revision):
    from service.app import ready_project
    return model.ensure_workbench(ready_project(project_id, revision))


def component(project, component_id):
    value = next((c for c in project["components"] if c["id"] == component_id), None)
    if value is None:
        raise ValueError("组件不存在")
    return value


def evidence(project_id, sources):
    from service.app import validate_sources
    validate_sources(project_id, sources)


def audit(request):
    return request.context.model_dump(exclude_none=True) if request.context else None


def validate_changes(project, request):
    if len({c.componentId for c in request.changes}) != len(request.changes):
        raise ValueError("同一操作不可重复重建组件")
    for change in request.changes:
        c = component(project, change.componentId)
        evidence(project["id"], change.recipe.sources)
        legacy = change.recipe.legacyCandidateFile
        if legacy and legacy != c.get("recipe", {}).get("legacyCandidateFile"):
            raise ValueError("不能指定外部候选文件替代当前来源")
    if audit(request):
        model.record_change(copy.deepcopy(project), "validate", [], "校验上下文", audit(request))


@router.get("/skills")
def list_skills():
    return {"skills": skills.list_skills(), "defaultSkillId": skills.default_skill()["id"]}


@router.get("/skills/{skill_id}")
def read_skill(skill_id: str):
    return skills.get_skill(skill_id)


@router.post("/skills")
def import_skill(request: NewSkill):
    with db.LOCK:
        return skills.add_skill(request.label, request.content, request.resources)


@router.post("/projects/{project_id}/workflow-bindings")
def bind_workflow(project_id: str, request: BindSkill):
    with db.LOCK:
        project = model.ensure_workbench(db.load_project(project_id))
        db.check_revision(project, request.revision)
        for cid in request.componentIds:
            component(project, cid)
        skill = skills.get_skill(request.skillId)
        # A session-wide pin cannot be changed even when another project binds it.
        pin_path = db.ROOT / "workflow-sessions" / f"{db.safe_id(request.sessionId)}.json"
        if pin_path.exists():
            pinned = db.read_json(pin_path)
            if pinned["skillId"] != skill["id"] or pinned["skillFingerprint"] != skill["fingerprint"]:
                raise ValueError("该会话已固定其他 Skill；更换版本请使用新会话")
        binding = {"sessionId": request.sessionId, "projectId": project_id,
                   "skillId": skill["id"], "skillFingerprint": skill["fingerprint"],
                   "componentIds": request.componentIds, "boundAt": db.now(), "loadedAt": None}
        previous = project["workflowBindings"].get(request.sessionId)
        if previous:
            binding.update(boundAt=previous["boundAt"], loadedAt=previous.get("loadedAt"))
        project["workflowBindings"][request.sessionId] = binding
        db.atomic_json(pin_path, {**binding, "content": skill["content"], "resources": skill["resources"]})
        db.save_project(project)  # Binding doesn't change geometry revision.
        return binding


@router.post("/projects/{project_id}/workflow-bindings/{session_id}/loaded")
def loaded_workflow(project_id: str, session_id: str):
    with db.LOCK:
        project = model.ensure_workbench(db.load_project(project_id))
        binding = project["workflowBindings"].get(session_id)
        if not binding:
            raise ValueError("会话尚未绑定该工程")
        binding["loadedAt"] = db.now()
        db.save_project(project)
        return binding


@router.get("/projects/{project_id}/context")
def project_context(project_id: str):
    project = model.ensure_workbench(db.load_project(project_id))
    return {"projectId": project_id, "name": project["name"], "revision": project["revision"],
            "source": project.get("source"), "sourceStepUrl": db.artifact_url(project_id, "source.step"),
            "documents": [{**d, "readUrl": f"/api/projects/{project_id}/documents/{d['id']}",
                           "fileUrl": f"/api/projects/{project_id}/documents/{d['id']}/file"} for d in project["documents"]],
            "components": [{k: c.get(k) for k in ("id", "displayName", "nameStatus", "identityEvidence", "sourceName", "engineeringGroup", "recipeFingerprint", "recipe", "installationRegions", "localBoundsMm", "pose")} for c in project["components"]],
            "thermalContacts": project["thermalContacts"], "workflowBindings": project["workflowBindings"],
            "checks": project["checks"], "artifacts": project["artifacts"]}


@router.get("/projects/{project_id}/documents/{document_id}/file")
def document_file(project_id: str, document_id: str):
    project = db.load_project(project_id)
    doc = next((d for d in project["documents"] if d["id"] == document_id), None)
    if not doc:
        raise FileNotFoundError()
    path = db.project_dir(project_id) / "documents" / f"{db.safe_id(document_id)}{Path(doc['name']).suffix.lower()}"
    return FileResponse(path, filename=doc["name"])


@router.get("/projects/{project_id}/recipes")
def read_recipes(project_id: str):
    project = model.ensure_workbench(db.load_project(project_id))
    return {"revision": project["revision"], "components": [
        {k: c.get(k) for k in ("id", "displayName", "nameStatus", "identityEvidence", "engineeringGroup", "sourceName", "localBoundsMm", "pose", "recipe", "recipeFingerprint", "outputGeometry", "installationRegions", "recipeCopies")} for c in project["components"]]}


@router.post("/projects/{project_id}/recipes/rebuild")
def rebuild_recipes(project_id: str, request: Rebuild):
    from service.app import submit
    project = ready(project_id, request.revision)
    validate_changes(project, request)
    return submit(project, "recipes", {"changes": [c.model_dump() for c in request.changes], "context": audit(request)})


@router.post("/projects/{project_id}/components/{component_id}/recipe-copies")
def save_copy(project_id: str, component_id: str, request: CopyRecipe):
    with db.LOCK:
        project = ready(project_id, request.revision)
        c = component(project, component_id)
        copy_id = uuid.uuid4().hex
        saved = {"id": copy_id, "name": request.name, "at": db.now(), "componentId": component_id,
                 "recipe": copy.deepcopy(c["recipe"]), "fingerprint": c["recipeFingerprint"],
                 "sourceHash": c["sourceHash"], "savedRevision": project["revision"], "engineeringAccepted": False}
        model.record_change(project, "save_recipe_copy", [component_id], request.name, audit(request), copyId=copy_id)
        db.atomic_json(db.project_dir(project_id) / "recipe-copies" / f"{copy_id}.json", saved)
        c["recipeCopies"].append({k: saved[k] for k in ("id", "name", "at", "fingerprint", "engineeringAccepted")})
        db.invalidate_exports(project)
        db.save_project(project, increment=True)
        return {"copy": saved, "revision": project["revision"]}


@router.post("/projects/{project_id}/components/{component_id}/recipe-copies/{copy_id}/load")
def load_copy(project_id: str, component_id: str, copy_id: str, request: LoadCopy):
    saved = db.read_json(db.project_dir(project_id) / "recipe-copies" / f"{db.safe_id(copy_id)}.json")
    project = ready(project_id, request.revision)
    c = component(project, component_id)
    if saved["componentId"] != component_id or saved["sourceHash"] != c["sourceHash"]:
        raise ValueError("方案副本不属于该单机来源")
    return rebuild_recipes(project_id, Rebuild(revision=request.revision, context=request.context,
        changes=[Change(componentId=component_id, recipe=Recipe.model_validate(saved["recipe"]), reason=f"载入方案副本：{saved['name']}")]))


@router.get("/projects/{project_id}/thermal-contacts")
def read_contacts(project_id: str):
    project = model.ensure_workbench(db.load_project(project_id))
    return {"revision": project["revision"], "contacts": project["thermalContacts"],
            "discovery": project.get("contactDiscovery", {"status": "not_checked"}),
            "complete": project.get("contactDiscovery", {}).get("status") == "completed"}


@router.post("/projects/{project_id}/thermal-contacts")
def update_contacts(project_id: str, request: ContactUpdate):
    with db.LOCK:
        project = ready(project_id, request.revision)
        by_id = {c["id"]: c for c in project["components"]}
        if len({c.id for c in request.contacts}) != len(request.contacts):
            raise ValueError("接触 ID 不可重复")
        for contact in request.contacts:
            if contact.a.componentId == contact.b.componentId:
                raise ValueError("接触两端必须为不同组件")
            evidence(project_id, contact.sources)
            if contact.origin == "document" and not contact.sources:
                raise ValueError("资料接触定义须包含原文来源")
            if contact.origin == "geometry" and contact.status == "confirmed":
                raise ValueError("几何证据只能产生候选，不能认证热连接")
            for side in (contact.a, contact.b):
                c = component(project, side.componentId)
                regions = c.get("installationRegions", [])
                if side.regionId and not any(r["id"] == side.regionId and r.get("mappingStatus") == "mapped" for r in regions):
                    raise ValueError("接触区域不存在或尚未成功重建")
                if contact.status == "confirmed" and not side.regionId:
                    raise ValueError("确认接触须明确双方安装区域")
            current = next((c for c in project["thermalContacts"] if c["id"] == contact.id), None)
            value = contact.model_dump()
            value.update(mappingStatus="mapped" if contact.a.regionId and contact.b.regionId else "needs_review",
                         recipeFingerprints={side.componentId: by_id[side.componentId]["recipeFingerprint"] for side in (contact.a, contact.b)},
                         unknownFields=[key for key in ("areaMm2", "conductanceWPerK") if value[key] is None], updatedAt=db.now())
            if current:
                current.update(value)
            else:
                project["thermalContacts"].append(value)
        model.record_change(project, "update_contacts", list({side.componentId for c in request.contacts for side in (c.a, c.b)}),
                            "; ".join(c.evidence for c in request.contacts), audit(request), contacts=[c.model_dump() for c in request.contacts])
        project["checks"]["thermalStatus"] = "needs_review"
        db.invalidate_exports(project)
        return db.save_project(project, increment=True)


@router.post("/projects/{project_id}/identities")
def update_identities(project_id: str, request: Identities):
    with db.LOCK:
        project = ready(project_id, request.revision)
        for identity in request.components:
            c = component(project, identity.componentId)
            if not any("\u4e00" <= char <= "\u9fff" for char in identity.displayName):
                raise ValueError("工程名称须包含可读中文；源代号保持在详情")
            evidence(project_id, identity.sources)
            c.update(displayName=identity.displayName, engineeringGroup=identity.engineeringGroup,
                     nameStatus=identity.nameStatus, identityEvidence=identity.model_dump())
        model.record_change(project, "identify_equipment", [c.componentId for c in request.components],
                            "; ".join(c.basis for c in request.components), audit(request))
        db.invalidate_exports(project)
        return db.save_project(project, increment=True)


@router.get("/projects/{project_id}/evidence")
def read_evidence(project_id: str):
    project = model.ensure_workbench(db.load_project(project_id))
    return {"apiVersion": 2, "softwareVersion": "0.3.0", "projectId": project_id, "revision": project["revision"],
            "activeJobId": project.get("activeJobId"), "workflowBindings": project["workflowBindings"],
            "components": [{"id": c["id"], "displayName": c["displayName"], "nameStatus": c.get("nameStatus", "unidentified"),
                            "identityEvidence": c.get("identityEvidence"), "recipeFingerprint": c["recipeFingerprint"], "recipe": c["recipe"],
                            "measurements": c.get("outputGeometry"), "pose": c["pose"], "originalPose": c["originalPose"],
                            "unknownThermalFields": [k for k, v in c["recipe"]["thermal"].items() if v is None],
                            "installationRegions": c.get("installationRegions", [])} for c in project["components"]],
            "checks": project["checks"], "thermalContacts": project["thermalContacts"],
            "contactDiscovery": project.get("contactDiscovery", {"status": "not_checked"}),
            "feedbackRecords": project["feedbackRecords"], "artifacts": project["artifacts"],
            "sessionRecords": session_records(project_id),
            "lastExport": project.get("lastExport"), "scoring": "external"}


@router.get("/projects/{project_id}/feedback")
def read_feedback(project_id: str):
    project = model.ensure_workbench(db.load_project(project_id))
    return {"records": project["feedbackRecords"], "autoSkillUpdate": False}


class SessionRecord(Strict):
    sessionId: str
    seq: int = Field(ge=0)
    type: str = Field(max_length=100)
    summary: str = Field(max_length=16000)
    componentIds: list[str] = Field(default_factory=list)
    skillFingerprint: str


def session_records(project_id):
    root = db.project_dir(project_id) / "session-records"
    return sorted((db.read_json(path) for path in root.glob("*.json")), key=lambda r: (r["sessionId"], r["seq"]))


@router.post("/projects/{project_id}/session-records")
def record_session(project_id: str, request: SessionRecord):
    with db.LOCK:
        project = model.ensure_workbench(db.load_project(project_id))
        binding = project["workflowBindings"].get(request.sessionId)
        if not binding or binding["skillFingerprint"] != request.skillFingerprint:
            raise ValueError("会话记录指纹与绑定不一致")
        key = model.fingerprint([request.sessionId, request.seq, request.type])
        value = {**request.model_dump(), "projectId": project_id, "at": db.now(), "revision": project["revision"], "autoSkillUpdate": False}
        db.atomic_json(db.project_dir(project_id) / "session-records" / f"{key}.json", value)
        return {"recorded": True, "id": key}


@router.get("/projects/{project_id}/session-records")
def read_session_records(project_id: str):
    db.load_project(project_id)
    return {"records": session_records(project_id)}


@router.post("/projects/{project_id}/feedback")
def add_feedback(project_id: str, request: Feedback):
    with db.LOCK:
        project = ready(project_id, request.revision)
        for cid in request.componentIds:
            component(project, cid)
        model.record_change(project, "engineer_feedback", request.componentIds, request.reason, audit(request))
        return db.save_project(project, increment=True)
