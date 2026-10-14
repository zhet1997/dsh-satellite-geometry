"""Independent HTTP boundary shared by the DSH tools and geometry workbench."""
from __future__ import annotations

import copy
import asyncio
import hmac
import hashlib
import logging
import os
import shutil
import signal
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from service import storage as db
from service.documents import document_summary, extract_document, recovery_methods, SUPPORTED_SUFFIXES

EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="satellite-cad")


@asynccontextmanager
async def lifespan(app):
    db.ROOT.mkdir(parents=True, exist_ok=True)
    for path in (db.ROOT / "jobs").glob("*.json"):
        try:
            job = db.read_json(path)
            if job["status"] in {"queued", "running"}:
                db.update_job(job["id"], status="failed", message="服务重启，未完成任务已中断；可重新提交", error="interrupted")
                project = db.load_project(job["projectId"])
                if project.get("activeJobId") == job["id"]:
                    project.pop("activeJobId", None)
                    db.save_project(project)
        except (ValueError, OSError, KeyError):
            continue
    try:
        yield
    finally:
        # Graceful shutdown must not wait an hour for a busy native CAD call.
        # Ask every owned job to stop, then let the supervisor reap its process.
        with db.LOCK:
            for path in (db.ROOT / "jobs").glob("*.json"):
                try:
                    job = db.read_json(path)
                    project = db.load_project(job["projectId"])
                    if job["status"] in {"queued", "running"} and project.get("activeJobId") == job["id"]:
                        db.update_job(job["id"], cancelRequested=True, message="服务关闭，正在停止几何任务")
                except (ValueError, OSError, KeyError):
                    continue
        await asyncio.to_thread(lambda: EXECUTOR.submit(lambda: None).result())


app = FastAPI(title="Satellite Geometry Service", version="0.3.1", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("SATCAD_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8787,http://127.0.0.1:8787,http://localhost:3080,http://127.0.0.1:3080").split(","),
                   allow_methods=["GET", "POST"], allow_headers=["Content-Type", "Authorization"])


@app.middleware("http")
async def token_auth(request: Request, call_next):
    token = os.environ.get("SATCAD_TOKEN", "")
    if token and request.url.path.startswith("/api/") and request.url.path != "/api/health":
        provided = request.headers.get("authorization", "")
        if not hmac.compare_digest(provided, f"Bearer {token}"):
            return JSONResponse({"detail": "需要服务访问令牌"}, status_code=401)
    return await call_next(request)


@app.exception_handler(ValueError)
async def invalid_request(_: Request, exc: ValueError):
    return JSONResponse({"detail": str(exc)}, status_code=409 if "版本已变化" in str(exc) else 400)


@app.exception_handler(FileNotFoundError)
async def missing_resource(_: Request, exc: FileNotFoundError):
    return JSONResponse({"detail": "项目或资源不存在"}, status_code=404)


@app.exception_handler(Exception)
async def internal_error(_: Request, exc: Exception):
    logging.getLogger(__name__).error("Unhandled service error", exc_info=exc)
    return JSONResponse({"detail": "服务未能完成这项操作，详细原因已记录到运行日志"}, status_code=500)


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class NewProject(ApiModel):
    name: str = Field(default="卫星几何项目", max_length=200)


class Revision(ApiModel):
    revision: int = Field(ge=0)


class DocumentRecovery(Revision):
    method: Literal["retry", "xlsx_xml", "docx_xml", "mark_unreadable"]
    reason: str = Field(default="", max_length=4000)
    sessionId: str | None = None


class DocumentRecoveryRequest(ApiModel):
    sessionId: str
    requestId: str
    documentIds: list[str] = Field(min_length=1, max_length=100)
    action: Literal["claim", "submitted", "dispatch_failed"] = "claim"
    message: str = Field(default="", max_length=1000)


class Simplification(Revision):
    componentIds: list[str] | None = None
    strategy: Literal["conservative", "box", "multibox"] = "conservative"
    preserveContacts: bool = True
    contactToleranceMm: float = Field(default=0.1, ge=0, le=10)
    purpose: Literal["thermal", "assembly", "envelope"] = "thermal"


class Restore(Revision):
    restoreGeometry: bool = True
    restorePose: bool = True


class EquipmentEnvelopeRebuild(Revision):
    planId: str
    authorization: Literal["user_requested_equivalent_envelopes"]
    thermalContacts: Literal["separately_defined"]
    reason: str = Field(min_length=1, max_length=4000)


class SourceReference(ApiModel):
    documentId: str
    quote: str = Field(min_length=1, max_length=4000)
    field: str = "notes"
    reference: str | None = None


class MotionConstraints(ApiModel):
    allowedTranslationAxes: list[Literal["X", "Y", "Z"]] = Field(default_factory=list)
    maxTranslationMm: float = Field(default=0, ge=0, le=100000)
    maxRotationDeg: float = Field(default=0, ge=0, le=180)
    preserveContacts: bool = True
    reason: str = Field(min_length=1, max_length=4000)
    sources: list[SourceReference] = Field(default_factory=list)


MetadataField = Literal["massKg", "powerW", "fixed", "thermalCritical", "material", "notes", "motionConstraints"]
METADATA_FIELDS = {"massKg", "powerW", "fixed", "thermalCritical", "material", "notes", "motionConstraints"}


class ComponentMetadata(ApiModel):
    id: str
    origin: Literal["document", "manual"] = "manual"
    changedFields: list[MetadataField] | None = None
    massKg: float | None = Field(default=None, ge=0)
    powerW: float | None = Field(default=None, ge=0)
    fixed: bool | None = None
    thermalCritical: bool | None = None
    material: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=8000)
    motionConstraints: MotionConstraints | None = None
    sources: list[SourceReference] = Field(default_factory=list)


class Metadata(Revision):
    components: list[ComponentMetadata] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=20000)


class PlanOperation(ApiModel):
    componentId: str
    action: Literal["preserve", "box", "multibox"]
    reason: str = Field(min_length=1, max_length=4000)
    sources: list[SourceReference] = Field(default_factory=list)


class Plan(Revision):
    summary: str = Field(min_length=1, max_length=16000)
    operations: list[PlanOperation] = Field(min_length=1, max_length=10000)


class PoseChange(Revision):
    rotation: list[list[float]]
    translationMm: list[float]
    reason: str = Field(min_length=1, max_length=4000)
    authorization: Literal["user_requested", "verified_source_collision"]


class SemanticOperation(ApiModel):
    action: Literal["rename", "group", "ungroup"]
    componentIds: list[str] = Field(default_factory=list)
    groupId: str | None = None
    name: str | None = Field(default=None, max_length=200)
    reason: str = Field(min_length=1, max_length=4000)


class Semantics(Revision):
    operations: list[SemanticOperation] = Field(min_length=1, max_length=1000)


def get_project(project_id):
    from service.modeling import ensure_workbench
    return ensure_workbench(db.load_project(project_id))


def ready_project(project_id, revision=None):
    project = get_project(project_id)
    if revision is not None:
        db.check_revision(project, revision)
    if project.get("activeJobId"):
        raise HTTPException(409, "当前项目已有任务在进行，请等待完成或取消")
    return project


def require_geometry(project):
    if not project["components"]:
        raise ValueError("请先导入 STEP 装配")


def run_job(job):
    """Supervise one serial subprocess while keeping OCP outside the HTTP GIL."""
    process = None
    project_id = job["projectId"]
    try:
        if db.get_job(job["id"]).get("cancelRequested"):
            db.update_job(job["id"], status="cancelled", message="排队任务已取消")
            return
        environment = dict(os.environ, SATCAD_DATA_ROOT=str(db.ROOT))
        environment["PYTHONUNBUFFERED"] = "1"
        environment["SATCAD_SUPERVISOR_PID"] = str(os.getpid())
        # Forked pair workers inherit read-only BRep; avoid background numerical
        # thread pools in their dedicated parent CAD worker.
        for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
            environment[name] = "1"
        log_path = db.ROOT / "jobs" / f"{job['id']}.log"
        started = time.monotonic()
        maximum = float(os.environ.get("SATCAD_JOB_TIMEOUT_SECONDS", "3600"))
        with log_path.open("wb") as log:
            process = subprocess.Popen([sys.executable, "-m", "service.worker", job["id"]],
                                       cwd=Path(__file__).resolve().parents[1], env=environment,
                                       stdout=log, stderr=subprocess.STDOUT, start_new_session=os.name != "nt")
            db.update_job(job["id"], workerPid=process.pid)
            while process.poll() is None:
                state = db.get_job(job["id"])
                cancelled = state.get("cancelRequested")
                timed_out = time.monotonic() - started > maximum
                if cancelled or timed_out:
                    try:
                        if os.name == "nt":
                            process.terminate()
                        else:
                            os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        if os.name == "nt":
                            process.kill()
                        else:
                            os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=5)
                    with db.LOCK:
                        state = db.get_job(job["id"])
                        if state["status"] not in {"completed", "failed"}:
                            db.update_job(job["id"], status="cancelled" if cancelled else "failed",
                                          message="几何任务已取消，已结束子进程" if cancelled else "几何任务超时，已结束子进程",
                                          error=None if cancelled else "job timeout")
                    break
                time.sleep(.2)
        state = db.get_job(job["id"])
        if state["status"] in {"queued", "running"}:
            db.update_job(job["id"], status="failed", message="几何子进程意外退出；原版本保持可用", error=f"worker exit code {process.returncode}")
    except Exception as exc:
        import logging
        logging.exception("Geometry job failed")
        db.update_job(job["id"], status="failed", message="任务失败；原始模型和已完成版本保持可用", error=f"{type(exc).__name__}: {exc}")
    finally:
        with db.LOCK:
            current = get_project(project_id)
            if current.get("activeJobId") == job["id"]:
                current.pop("activeJobId", None)
                db.save_project(current)


def submit(project, kind, payload=None, increment=True):
    with db.LOCK:
        current = ready_project(project["id"], project["revision"])
        job = db.new_job(project["id"], kind)
        job = db.update_job(job["id"], payload=payload or {}, projectSnapshot=project, incrementRevision=increment)
        current["activeJobId"] = job["id"]
        db.save_project(current)
        EXECUTOR.submit(run_job, job)
    return {"jobId": job["id"], "projectId": project["id"], "status": "queued"}


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "satellite-geometry", "version": "0.3.1"}


@app.get("/api/capabilities")
def capabilities():
    return {"apiVersion": 2, "recipes": ["source", "solid", "surface_shell"], "recipeParts": ["box", "cylinder", "source"],
            "recipeCopies": True, "skillVersions": "immutable_session_bound", "evidenceScoring": "external",
            "sourceFormats": ["step", "stp"], "documentFormats": ["docx", "xlsx", "pdf", "txt", "md", "csv", "json"],
            "strategies": ["conservative", "box", "multibox"], "preserveOriginalPoseByDefault": True,
            "equivalentEquipmentEnvelopes": {"available": True, "requiresExplicitUserChoice": True, "thermalContacts": "separately_defined", "movesComponents": False},
            "checks": ["original_step_solid_intersection", "candidate_envelope_intersection", "contact_proximity", "topology_readback"],
            "notYetChecked": ["cables", "bolt_mating", "whole_shell_containment", "thermal_conductance"],
            "layout": "explicit_source-verified_pose_candidates", "exports": ["step", "glb", "properties.json", "contacts.json", "zip"],
            "coordinateSystem": {"source": "Z-up mm", "glb": "Y-up m"}}


@app.get("/api/projects")
def projects():
    return {"projects": db.list_projects()}


@app.post("/api/projects")
def create_project(request: NewProject):
    with db.LOCK:
        return db.new_project(request.name)


@app.get("/api/projects/{project_id}")
def read_project(project_id: str):
    return get_project(project_id)


@app.get("/api/projects/{project_id}/artifacts/{relative:path}")
def read_artifact(project_id: str, relative: str):
    path = db.artifact_path(project_id, relative)
    if not path.is_file():
        raise FileNotFoundError()
    return FileResponse(path)


@app.post("/api/projects/{project_id}/import")
def import_model(project_id: str, file: UploadFile = File(...)):
    project = ready_project(project_id)
    if project["components"]:
        raise ValueError("原始装配不可覆盖；请创建新项目导入另一 STEP")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".step", ".stp"}:
        raise ValueError("仅支持 STEP/STP 文件")
    root = db.project_dir(project_id)
    source = root / "source" / "original.step"
    source.parent.mkdir(parents=True, exist_ok=True)
    temporary = source.with_name(f".upload-{uuid.uuid4().hex}.step")
    maximum = int(os.environ.get("SATCAD_MAX_UPLOAD_BYTES", str(4 * 1024**3)))
    size = 0
    try:
        with temporary.open("wb") as handle:
            for chunk in iter(lambda: file.file.read(1024 * 1024), b""):
                size += len(chunk)
                if size > maximum:
                    raise ValueError("STEP 文件超过当前上传大小限制")
                handle.write(chunk)
        if size == 0:
            raise ValueError("STEP 文件为空")
        # Concurrent uploads must not overwrite a source already being imported.
        # Each upload streams privately, then reserves the project atomically.
        with db.LOCK:
            current = ready_project(project_id, project["revision"])
            if current["components"]:
                raise ValueError("原始装配不可覆盖；请创建新项目导入另一 STEP")
            os.replace(temporary, source)
            artifact = root / "artifacts" / "source.step"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, artifact)
            return submit(current, "import", {"originalName": Path(file.filename or "original.step").name})
    finally:
        temporary.unlink(missing_ok=True)
        file.file.close()


@app.post("/api/projects/{project_id}/simplify")
def simplify_model(project_id: str, request: Simplification):
    project = ready_project(project_id, request.revision)
    require_geometry(project)
    if request.purpose == "thermal" and not request.preserveContacts:
        raise ValueError("热分析用途必须保留已识别关键接触几何")
    return submit(project, "simplify", {"request": request.model_dump()})


@app.post("/api/projects/{project_id}/check")
def check_model(project_id: str, request: Revision):
    project = ready_project(project_id, request.revision)
    require_geometry(project)
    return submit(project, "check", increment=False)


@app.post("/api/projects/{project_id}/export")
def export_model(project_id: str, request: Revision):
    project = ready_project(project_id, request.revision)
    require_geometry(project)
    return submit(project, "export", increment=False)


@app.post("/api/projects/{project_id}/components/{component_id}/restore")
def restore_component(project_id: str, component_id: str, request: Restore):
    project = ready_project(project_id, request.revision)
    if component_id not in {c["id"] for c in project["components"]}:
        raise ValueError("组件不存在")
    return submit(project, "restore", {"componentId": component_id, "request": request.model_dump()})


@app.get("/api/jobs/{job_id}")
def read_job(job_id: str):
    return {key: value for key, value in db.get_job(job_id).items() if key not in {"projectSnapshot", "payload"}}


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    with db.LOCK:
        job = db.get_job(job_id)
        if job["status"] in {"queued", "running"}:
            db.update_job(job_id, cancelRequested=True, message="正在停止独立几何进程")
        return read_job(job_id)


@app.post("/api/projects/{project_id}/documents")
def upload_document(project_id: str, file: UploadFile = File(...)):
    with db.LOCK:
        project = ready_project(project_id)
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise ValueError("不支持的资料格式")
        document_id = uuid.uuid4().hex
        folder = db.project_dir(project_id) / "documents"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{document_id}{suffix}"
        try:
            content = file.file.read(50 * 1024 * 1024 + 1)
            if len(content) > 50 * 1024 * 1024:
                raise ValueError("资料文件不能超过50MB")
            checksum = hashlib.sha256(content).hexdigest()
            previous = next((doc for doc in project["documents"] if doc.get("sha256") == checksum), None)
            if previous:
                document = db.read_json(folder / f"{db.safe_id(previous['id'])}.parsed.json")
                return {"document": document, "revision": project["revision"], "duplicate": True}
            path.write_bytes(content)
            document = extract_document(path, Path(file.filename or "document").name, document_id)
        finally:
            file.file.close()
        db.atomic_json(folder / f"{document_id}.parsed.json", document)
        project["documents"].append(document_summary(document))
        db.invalidate_exports(project)
        db.save_project(project, increment=True)
        return {"document": document, "revision": project["revision"]}


@app.get("/api/projects/{project_id}/documents/{document_id}")
def read_document(project_id: str, document_id: str):
    get_project(project_id)
    document = db.read_json(db.project_dir(project_id) / "documents" / f"{db.safe_id(document_id)}.parsed.json")
    return {**document, "fileUrl": f"/api/projects/{project_id}/documents/{document_id}/file"}


def save_document(project: dict, document: dict, *, increment: bool = False):
    folder = db.project_dir(project["id"]) / "documents"
    db.atomic_json(folder / f"{db.safe_id(document['id'])}.parsed.json", document)
    project["documents"] = [document_summary(document) if doc["id"] == document["id"] else doc for doc in project["documents"]]
    if increment:
        db.invalidate_exports(project)
    db.save_project(project, increment=increment)


@app.post("/api/projects/{project_id}/documents/recovery-request")
def request_document_recovery(project_id: str, request: DocumentRecoveryRequest):
    """Durable, at-most-once automatic dispatch, including across page reloads."""
    with db.LOCK:
        project = ready_project(project_id)
        db.safe_id(request.sessionId)
        db.safe_id(request.requestId)
        if request.sessionId not in project.get("workflowBindings", {}):
            raise ValueError("恢复资料前需将当前 DSH 会话绑定到此工程")
        documents = []
        if any(not any(doc["id"] == document_id for doc in project["documents"]) for document_id in request.documentIds):
            raise FileNotFoundError()
        originals = [read_document(project_id, document_id) for document_id in dict.fromkeys(request.documentIds)]
        for document in originals:
            document.pop("fileUrl", None)
            recovery = document.setdefault("recovery", {"automaticAttempts": 0, "toolAttempts": 0})
            if request.action == "claim":
                if document["extractionStatus"] not in {"needs_recovery", "needs_ocr"} or recovery.get("automaticAttempts", 0):
                    continue
                recovery.update(status="claimed", automaticAttempts=1, requestId=request.requestId,
                                sessionId=request.sessionId, requestedAt=db.now())
            elif recovery.get("requestId") != request.requestId or recovery.get("sessionId") != request.sessionId:
                continue
            elif recovery.get("status") == "claimed":
                recovery.update(status="queued" if request.action == "submitted" else "needs_review", message=request.message)
            save_document(project, document)
            documents.append(document_summary(document))
        return {"documents": documents, "revision": project["revision"], "requestId": request.requestId}


@app.post("/api/projects/{project_id}/documents/{document_id}/recover")
def recover_document(project_id: str, document_id: str, request: DocumentRecovery):
    with db.LOCK:
        project = ready_project(project_id, request.revision)
        if not any(doc["id"] == document_id for doc in project["documents"]):
            raise FileNotFoundError()
        previous = read_document(project_id, document_id)
        previous.pop("fileUrl", None)
        if previous["extractionStatus"] == "extracted":
            return {"document": previous, "revision": project["revision"]}
        suffix = Path(previous["name"]).suffix.lower()
        if request.method not in recovery_methods(suffix):
            raise ValueError("此资料不支持指定的恢复方式")
        recovery = previous.get("recovery", {"automaticAttempts": 0, "toolAttempts": 0}).copy()
        if request.sessionId:
            db.safe_id(request.sessionId)
            if recovery.get("sessionId") != request.sessionId:
                raise ValueError("资料恢复请求与当前会话不一致")
            if recovery.get("toolAttempts", 0) >= 2 and request.method != "mark_unreadable":
                raise ValueError("自动恢复已尝试两次；请标记无法读取并说明缺失项")
        if request.method == "mark_unreadable":
            if not request.reason.strip():
                raise ValueError("标记无法读取时须说明原因")
            document = previous
            document.update(extractionStatus="unreadable", text="", sections=[])
            document["warnings"] = ["原始资料已保存，内容暂未能读取；相关工程参数保持未知", request.reason]
        else:
            source = db.project_dir(project_id) / "documents" / f"{db.safe_id(document_id)}{suffix}"
            document = extract_document(source, previous["name"], document_id, method=request.method)
            if document["sha256"] != previous["sha256"]:
                raise ValueError("原始资料校验不一致，未提交恢复内容")
            old_attempts = previous.get("diagnostics", {}).get("attempts", [])
            document["diagnostics"]["attempts"] = (old_attempts + document["diagnostics"]["attempts"])[-20:]
            recovery["toolAttempts"] = recovery.get("toolAttempts", 0) + 1
        recovery.update(status="resolved" if document["extractionStatus"] == "extracted" else "needs_review",
                        method=request.method, reason=request.reason, updatedAt=db.now())
        document["recovery"] = recovery
        save_document(project, document, increment=True)
        return {"document": document, "revision": project["revision"]}


def validate_sources(project_id, references):
    for reference in references:
        document = read_document(project_id, reference.documentId)
        if reference.quote not in document["text"]:
            raise ValueError(f"引用文字不在资料 {document['name']} 的提取文本中")


@app.post("/api/projects/{project_id}/metadata")
def update_metadata(project_id: str, request: Metadata):
    with db.LOCK:
        project = ready_project(project_id, request.revision)
        by_id = {c["id"]: c for c in project["components"]}
        if len({item.id for item in request.components}) != len(request.components):
            raise ValueError("同一次资料提交不能重复列出组件")
        updates = []
        for item in request.components:
            if item.id not in by_id:
                raise ValueError(f"组件不存在：{item.id}")
            validate_sources(project_id, item.sources)
            if item.motionConstraints:
                validate_sources(project_id, item.motionConstraints.sources)
            supplied = item.model_fields_set & METADATA_FIELDS
            changed = set(item.changedFields) if item.changedFields is not None else supplied
            if changed != supplied:
                raise ValueError("changedFields 必须与本次实际提交的属性字段完全一致；其他属性请省略")
            values = item.model_dump(include=changed)
            references = [ref.model_dump(exclude_none=True) for ref in item.sources]
            if item.motionConstraints:
                for ref in item.motionConstraints.sources:
                    entry = ref.model_dump(exclude_none=True)
                    if not entry["field"].startswith("motionConstraints."):
                        entry["field"] = "motionConstraints." + entry["field"]
                    references.append(entry)
            for reference in references:
                if reference["field"].split(".")[0] not in changed:
                    raise ValueError(f"引用字段 {reference['field']} 没有在本次属性提交中")
            if item.origin == "document":
                required = {key for key, value in values.items() if value is not None and key != "motionConstraints"}
                if item.motionConstraints:
                    required |= {"motionConstraints." + field for field in item.motionConstraints.model_fields_set if field != "sources"}
                covered = {reference["field"] for reference in references}
                missing = required - covered
                if missing:
                    raise ValueError("资料来源未覆盖已填写字段：" + ", ".join(sorted(missing)))
            elif references:
                raise ValueError("人工修改请省略 sources；引用资料请使用 origin=document")
            updates.append((item, changed, values, references))
        for item, changed, values, references in updates:
            metadata = by_id[item.id]["metadata"]
            # Replace evidence only for the fields actually edited. A manual
            # edit must never inherit a document quote for the previous value.
            old_references = [reference for reference in metadata.get("sources", []) if reference.get("field", "notes").split(".")[0] not in changed]
            provenance = metadata.setdefault("provenance", {})
            for key in list(provenance):
                if key.split(".")[0] in changed:
                    provenance.pop(key)
            for key, value in values.items():
                matching = [reference for reference in references if reference["field"] == key or reference["field"].startswith(key + ".")]
                provenance[key] = {"origin": item.origin, "state": "unknown" if value is None else "known", "at": db.now(), "sources": matching}
                if value is None:
                    metadata.pop(key, None)
                else:
                    metadata[key] = value
                if key == "motionConstraints" and value is not None:
                    metadata[key]["sources"] = matching
                    for field in item.motionConstraints.model_fields_set - {"sources"}:
                        field_key = "motionConstraints." + field
                        provenance[field_key] = {"origin": item.origin, "state": "known", "at": db.now(), "sources": [reference for reference in references if reference["field"] == field_key]}
            metadata["sources"] = old_references + references
            from service.modeling import ensure_workbench, fingerprint
            ensure_workbench(project)
            c = by_id[item.id]
            for key in ("material", "massKg", "powerW"):
                if key in changed:
                    c["recipe"]["thermal"][key] = metadata.get(key)
            c["recipeFingerprint"] = fingerprint(c["recipe"])
            for region in c.get("installationRegions", []):
                region["recipeFingerprint"] = c["recipeFingerprint"]
        if request.notes is not None:
            project["notes"] = request.notes
        project["checks"]["thermalStatus"] = "unknown"
        db.invalidate_exports(project)
        return db.save_project(project, increment=True)


@app.post("/api/projects/{project_id}/plans")
def create_plan(project_id: str, request: Plan):
    with db.LOCK:
        project = ready_project(project_id, request.revision)
        ids = {c["id"] for c in project["components"]}
        if len({op.componentId for op in request.operations}) != len(request.operations):
            raise ValueError("同一方案不能重复定义同一组件")
        for operation in request.operations:
            if operation.componentId not in ids:
                raise ValueError(f"组件不存在：{operation.componentId}")
            validate_sources(project_id, operation.sources)
        plan = {"id": uuid.uuid4().hex, **request.model_dump(), "createdAt": db.now(), "status": "proposed"}
        db.atomic_json(db.project_dir(project_id) / "plans" / f"{plan['id']}.json", plan)
        project["plans"].append({key: plan[key] for key in ("id", "summary", "revision", "status", "createdAt")})
        db.save_project(project)
        return {"planId": plan["id"], "revision": project["revision"], "plan": plan}


@app.post("/api/projects/{project_id}/plans/{plan_id}/apply")
def apply_plan(project_id: str, plan_id: str, request: Simplification):
    project = ready_project(project_id, request.revision)
    plan = db.read_json(db.project_dir(project_id) / "plans" / f"{db.safe_id(plan_id)}.json")
    db.check_revision(project, plan["revision"])
    request = request.model_copy(update={"componentIds": [op["componentId"] for op in plan["operations"]]})
    if request.purpose == "thermal" and not request.preserveContacts:
        raise ValueError("热分析用途必须保留已识别关键接触几何")
    return submit(project, "apply_plan", {"request": request.model_dump(), "plan": plan})


@app.post("/api/projects/{project_id}/equipment-envelopes")
def rebuild_equipment_model(project_id: str, request: EquipmentEnvelopeRebuild):
    project = ready_project(project_id, request.revision)
    require_geometry(project)
    plan = db.read_json(db.project_dir(project_id) / "plans" / f"{db.safe_id(request.planId)}.json")
    db.check_revision(project, plan["revision"])
    operations = plan["operations"]
    if {op["componentId"] for op in operations} != {c["id"] for c in project["components"]}:
        raise ValueError("等效包络方案必须覆盖全部组件")
    if any(op["action"] not in {"preserve", "box"} for op in operations):
        raise ValueError("等效包络方案仅支持 preserve/box")
    return submit(project, "equipment_envelopes", {"request": request.model_dump(), "plan": plan})


@app.post("/api/projects/{project_id}/components/{component_id}/pose")
def update_pose(project_id: str, component_id: str, request: PoseChange):
    import numpy as np
    project = ready_project(project_id, request.revision)
    component = next((c for c in project["components"] if c["id"] == component_id), None)
    if component is None:
        raise ValueError("组件不存在")
    if component.get("metadata", {}).get("fixed"):
        raise ValueError("该组件已锁定原位姿")
    constraints = component.get("metadata", {}).get("motionConstraints")
    if not constraints:
        raise ValueError("缺少明确移动约束；请先记录允许平移轴、最大位移/转角及依据，再提交候选位姿")
    rotation = np.asarray(request.rotation, dtype=float)
    translation = np.asarray(request.translationMm, dtype=float)
    if rotation.shape != (3, 3) or translation.shape != (3,) or not np.isfinite(rotation).all() or not np.isfinite(translation).all() or not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-7) or not np.isclose(np.linalg.det(rotation), 1., atol=1e-7):
        raise ValueError("位姿必须是有限平移和右手正交旋转矩阵")
    delta = translation - np.asarray(component["originalPose"]["translationMm"])
    for index, axis in enumerate(("X", "Y", "Z")):
        if axis not in constraints.get("allowedTranslationAxes", []) and abs(delta[index]) > 1e-6:
            raise ValueError(f"约束未允许沿世界 {axis} 轴移动")
    if float(np.linalg.norm(delta)) > constraints.get("maxTranslationMm", 0) + 1e-6:
        raise ValueError("候选超过相对原始位姿的最大平移范围")
    source_rotation = np.asarray(component["originalPose"]["rotation"])
    angle = float(np.degrees(np.arccos(np.clip((np.trace(rotation @ source_rotation.T) - 1) / 2, -1, 1))))
    if angle > constraints.get("maxRotationDeg", 0) + 1e-6:
        raise ValueError("候选超过相对原始位姿的最大旋转角")
    if request.authorization == "verified_source_collision" and not any(component_id in pair["componentIds"] for pair in project["checks"]["sourceCollisions"]):
        raise ValueError("没有该组件的已核实真实干涉；包络重叠不足以授权自动移动")
    return submit(project, "pose", {
        "componentId": component_id, "request": request.model_dump(),
        "translationDeltaMm": delta.tolist(), "rotationDeltaDeg": angle,
    })


@app.post("/api/projects/{project_id}/semantics")
def update_semantics(project_id: str, request: Semantics):
    """Edit the working assembly tree without changing source occurrences or poses."""
    with db.LOCK:
        project = copy.deepcopy(ready_project(project_id, request.revision))
        by_id = {component["id"]: component for component in project["components"]}
        tree = {node["id"]: node for node in project["tree"]}
        source_parents = {node["id"]: node["parentId"] for node in project.get("sourceTree", project["tree"])}
        for operation in request.operations:
            if not set(operation.componentIds).issubset(by_id):
                raise ValueError("语义操作包含不存在的组件")
            if len(operation.componentIds) != len(set(operation.componentIds)):
                raise ValueError("语义操作不能重复列出同一组件")
            if operation.action == "rename":
                if len(operation.componentIds) != 1 or not operation.name:
                    raise ValueError("重命名需一个组件及新名称")
                component = by_id[operation.componentIds[0]]
                component.setdefault("originalName", component["name"])
                component.setdefault("sourceName", component["name"])
                component["name"] = operation.name
                if any("\u4e00" <= char <= "\u9fff" for char in operation.name):
                    component.update(displayName=operation.name, nameStatus="identified")
                tree[component["id"]]["name"] = operation.name
            elif operation.action == "group":
                if len(operation.componentIds) < 2 or not operation.name:
                    raise ValueError("分组至少需要两个组件及组名")
                group_id = "G" + uuid.uuid4().hex[:12]
                group = {"id": group_id, "name": operation.name, "parentId": None,
                         "children": operation.componentIds, "isLeaf": False, "semanticGroup": True,
                         "reason": operation.reason, "previousParents": {}}
                for component_id in operation.componentIds:
                    node = tree[component_id]
                    group["previousParents"][component_id] = node["parentId"]
                    if node["parentId"] in tree:
                        tree[node["parentId"]]["children"] = [x for x in tree[node["parentId"]]["children"] if x != component_id]
                    node["parentId"] = group_id
                    by_id[component_id]["semanticGroupId"] = group_id
                tree[group_id] = group
                project["tree"].append(group)
            else:
                group = tree.get(operation.groupId)
                if not group or not group.get("semanticGroup"):
                    raise ValueError("只能拆除工作树中的语义分组；原始STEP映射保持完整")
                for component_id in group["children"]:
                    parent_id = group["previousParents"].get(component_id)
                    if parent_id is not None and parent_id not in tree:
                        parent_id = source_parents.get(component_id)
                    if parent_id is not None and parent_id not in tree:
                        parent_id = None
                    tree[component_id]["parentId"] = parent_id
                    if parent_id in tree:
                        if component_id not in tree[parent_id]["children"]:
                            tree[parent_id]["children"].append(component_id)
                    if parent_id in tree and tree[parent_id].get("semanticGroup"):
                        by_id[component_id]["semanticGroupId"] = parent_id
                    else:
                        by_id[component_id].pop("semanticGroupId", None)
                project["tree"] = [node for node in project["tree"] if node["id"] != operation.groupId]
                tree.pop(operation.groupId)
        project["rootIds"] = [node["id"] for node in project["tree"] if node["parentId"] is None]
        project.setdefault("semanticHistory", []).append({"at": db.now(), **request.model_dump()})
        db.invalidate_exports(project)
        return db.save_project(project, increment=True)


from service.workbench import router as workbench_router
app.include_router(workbench_router)

# API routes precede the optional self-contained web workbench.
web_dist = Path(__file__).resolve().parents[1] / "web" / "dist"
if web_dist.is_dir():
    app.mount("/", StaticFiles(directory=web_dist, html=True), name="workbench")
