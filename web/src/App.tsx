import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowDownToLine, ArrowLeftRight, ArrowUpRight, Box, CheckCircle2,
  ChevronDown, ChevronRight, CircleAlert, Eye, EyeOff, FileText, Focus,
  FolderOpen, Layers3, LoaderCircle, Maximize, MessageSquare, Minus,
  Plus, RefreshCw, Satellite, Search, Settings2, ShieldCheck,
  Sparkles, Upload, X,
} from 'lucide-react';
import { ApiError, createClient } from './api';
import { Viewer, type ViewerHandle, type CameraState } from './Viewer';
import { RecipeInspector, SkillPanel, ContactDiagram, displayName } from './WorkbenchPanels';
import { exportPresentation } from './checkPresentation';
import type { CheckIssue, HostContext, Job, Project, ProjectDocument, ProjectSummary, Purpose, Strategy, ThermalContact, RegionFace } from './types';

const PURPOSES: Array<{ id: Purpose; name: string; description: string; strategy: Exclude<Strategy, 'original'> }> = [
  { id: 'thermal', name: '热分析', description: '保留热接触与敏感组件', strategy: 'conservative' },
  { id: 'assembly', name: '装配检查', description: '多层包络，复核实体干涉', strategy: 'multibox' },
  { id: 'envelope', name: '空间包络', description: '减少细节，提取组件外轮廓', strategy: 'box' },
  { id: 'detail', name: '局部精化', description: '多层包络，保留更多外形细节', strategy: 'multibox' },
];
const JOB_LABELS: Record<string, string> = { import: '导入模型', simplify: '简化几何', check: '检查几何', export: '导出模型', restore: '保留原实体' };
const initialParams = new URLSearchParams(window.location.search);
function parentOrigin() {
  try { return document.referrer ? new URL(document.referrer).origin : window.location.origin; }
  catch { return window.location.origin; }
}
function emitHost(type: string, payload: Record<string, unknown> = {}) {
  if (window.parent !== window) window.parent.postMessage({ type: `satellite-geometry:${type}`, ...payload }, parentOrigin());
}
function errorText(error: unknown) {
  return error instanceof ApiError && error.status === 409
    ? '项目已被另一项操作更新，已重新读取。请检查最新结果后再操作。'
    : error instanceof Error ? error.message : '操作未完成，请重试';
}
function finite(value: number | undefined, digits = 1) {
  return typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString('zh-CN', { maximumFractionDigits: digits }) : '—';
}
function normalizeProject(raw: Project): Project {
  return { ...raw, components: raw.components ?? [], tree: raw.tree ?? [], artifacts: raw.artifacts ?? {}, checks: raw.checks ?? {} };
}

export default function App() {
  const [apiBase, setApiBase] = useState(initialParams.get('apiBase') || (window.location.pathname.startsWith('/satellite-geometry/') ? '/api/cad' : '/api'));
  const client = useMemo(() => createClient(apiBase), [apiBase]);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [projectId, setProjectId] = useState(initialParams.get('projectId') || '');
  const [project, setProject] = useState<Project | null>(null);
  const [connected, setConnected] = useState(false);
  const [initializing, setInitializing] = useState(true);
  const [selected, setSelected] = useState<string[]>([]);
  const [hidden, setHidden] = useState<string[]>([]);
  const [query, setQuery] = useState('');
  const purpose: Purpose = 'thermal';
  const effectivePreserveContacts = true;
  const [tolerance, setTolerance] = useState(0.1);
  const [comparison, setComparison] = useState<'original' | 'simplified' | 'compare'>('compare');
  const [wireframe, setWireframe] = useState(false);
  const [tab, setTab] = useState<'geometry' | 'checks' | 'files'>('geometry');
  const [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [chatTransferPending, setChatTransferPending] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [newName, setNewName] = useState('');
  const [stepFile, setStepFile] = useState<File | null>(null);
  const [documents, setDocuments] = useState<File[]>([]);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [showSkill, setShowSkill] = useState(false);
  const [sessionId, setSessionId] = useState<string>();
  const [isolate, setIsolate] = useState(false);
  const [neighbours, setNeighbours] = useState(false);
  const [cameraLocked, setCameraLocked] = useState(true);
  const [contextMenu, setContextMenu] = useState<{id:string;x:number;y:number}|null>(null);
  const [contactFaces, setContactFaces] = useState<RegionFace[]>([]);
  const [editingContact, setEditingContact] = useState<ThermalContact|null>(null);
  const [documentPreview, setDocumentPreview] = useState<ProjectDocument | null>(null);
  const [semanticEdit, setSemanticEdit] = useState<'rename' | 'group' | null>(null);
  const [semanticName, setSemanticName] = useState('');
  const [semanticReason, setSemanticReason] = useState('');
  const originalViewer = useRef<ViewerHandle>(null);
  const simplifiedViewer = useRef<ViewerHandle>(null);
  const projectRef = useRef(project); projectRef.current = project;
  const selectedProjectIdRef = useRef(projectId); selectedProjectIdRef.current = projectId;
  const pollingGeneration = useRef(0);
  const mounted = useRef(true);
  const active = busy || job?.status === 'running' || job?.status === 'queued';
  const selectedComponents = useMemo(() => project?.components.filter((component) => selected.includes(component.id)) ?? [], [project, selected]);
  const inspected = selectedComponents.length === 1 ? selectedComponents[0] : null;
  const visibleIds = useMemo(() => {
    const ids = new Set(selected);
    if(neighbours) for(const c of project?.thermalContacts??[]) if(selected.includes(c.a.componentId)||selected.includes(c.b.componentId)){ids.add(c.a.componentId);ids.add(c.b.componentId);}
    return ids;
  }, [project, selected, neighbours]);
  const viewHidden = useMemo(() => [...new Set([...hidden,...(isolate?(project?.components??[]).filter(c=>!visibleIds.has(c.id)).map(c=>c.id):[])])], [project, hidden, isolate, visibleIds]);
  const syncCamera = (side:'original'|'simplified',value:CameraState) => { if(cameraLocked) (side==='original'?simplifiedViewer:originalViewer).current?.setCamera(value); };
  const menu = (id:string,x:number,y:number) => { setContextMenu({id,x,y}); setSelected([id]); setIsolate(true); };
  const showContact = (c:ThermalContact) => {setSelected([c.a.componentId,c.b.componentId]);setIsolate(true);setContactFaces([...(c.patches??[]),...(project?.components??[]).flatMap(x=>(x.installationRegions??[]).filter(r=>[c.a.regionId,c.b.regionId].includes(r.id)&&[c.a.componentId,c.b.componentId].includes(x.id)).flatMap(r=>r.faces))]);setTab('geometry');setEditingContact({...c});};

  const refresh = useCallback(async (id = projectRef.current?.id) => {
    if (!id) return null;
    const next = normalizeProject(await client.get(id));
    if (mounted.current && id === selectedProjectIdRef.current) { setProject(next); setConnected(true); }
    return next;
  }, [client]);
  const refreshProjects = useCallback(async () => {
    const values = await client.list();
    if (mounted.current) { setProjects(values); setConnected(true); }
    return values;
  }, [client]);

  useEffect(() => { mounted.current = true; return () => { mounted.current = false; pollingGeneration.current++; }; }, []);
  useEffect(() => {
    let cancelled = false; setInitializing(true);
    void refreshProjects().then((values) => {
      if (!cancelled && !projectId && values.length) setProjectId(values[0].id);
    }).catch((reason) => { if (!cancelled) { setConnected(false); setError(errorText(reason)); } })
      .finally(() => { if (!cancelled) setInitializing(false); });
    return () => { cancelled = true; };
    // Host context may choose a project separately from connection setup.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshProjects]);
  useEffect(() => {
    let cancelled = false; pollingGeneration.current++; setJob(null); setSelected([]); setHidden([]); setQuery('');
    if (!projectId) { setProject(null); return; }
    setProject(null); setInitializing(true);
    void client.get(projectId).then((value) => {
      if (cancelled) return;
      setProject(normalizeProject(value)); setConnected(true); setError('');
    }).catch((reason) => { if (!cancelled) setError(errorText(reason)); })
      .finally(() => { if (!cancelled) setInitializing(false); });
    return () => { cancelled = true; };
  }, [client, projectId]);
  useEffect(() => {
    const poll=window.setInterval(()=>{const p=projectRef.current;if(p&&!busy) void client.get(p.id).then(next=>{if(next.id===selectedProjectIdRef.current&&next.updatedAt!==projectRef.current?.updatedAt) setProject(normalizeProject(next));}).catch(()=>undefined);},2500);
    return ()=>window.clearInterval(poll);
  },[client,busy]);
  useEffect(()=>{const receive=(e:Event)=>{const result=(e as CustomEvent).detail;if(projectRef.current&&result?.jobId)void followJob(result.jobId,projectRef.current.id);};window.addEventListener('satcad-job',receive);return()=>window.removeEventListener('satcad-job',receive);});
  useEffect(() => {
    if (!notice || chatTransferPending) return;
    const timeout = window.setTimeout(() => setNotice(''), 5000); return () => window.clearTimeout(timeout);
  }, [notice, chatTransferPending]);
  useEffect(() => {
    if (!chatTransferPending) return;
    const timeout = window.setTimeout(() => {
      setChatTransferPending(false); setNotice('');
      setError('尚未收到 DSH 回执。请检查左侧聊天是否就绪，再重新带入选择。');
    }, 30_000);
    return () => window.clearTimeout(timeout);
  }, [chatTransferPending]);
  useEffect(() => {
    emitHost('selection', { projectId: project?.id, revision: project?.revision,
      selection: selectedComponents.map((component) => ({ nodeId: component.id, name: component.name })), purpose, preserveContacts: effectivePreserveContacts });
  }, [project?.id, project?.revision, selectedComponents, purpose, effectivePreserveContacts, sessionId]);
  useEffect(() => {
    const receive = (event: MessageEvent) => {
      if (event.source !== window.parent || event.origin !== parentOrigin()) return;
      const data = event.data as HostContext & { type?: string; ok?: boolean; message?: string; sessionId?:string };
      if (data?.type === 'satellite-geometry:selection-result') {
        setChatTransferPending(false);
        if (data.ok === true) {
          setError(''); setNotice(typeof data.message === 'string' ? data.message : '已将项目和选择带入 DSH 输入框');
        } else {
          setNotice(''); setError(typeof data.message === 'string' ? data.message : '未能带入 DSH，请检查左侧聊天后重试。');
        }
        return;
      }
      if (data?.type !== 'satellite-geometry:context') return;
      if (data.apiBase && typeof data.apiBase === 'string') setApiBase(data.apiBase);
      if (data.sessionId) setSessionId(data.sessionId);
      if (data.projectId && typeof data.projectId === 'string') {
        if (data.projectId !== projectRef.current?.id) setProjectId(data.projectId);
        else if (typeof data.revision === 'number' && data.revision !== projectRef.current?.revision) void refresh().catch(() => undefined);
      }
    };
    window.addEventListener('message', receive); emitHost('ready');
    return () => window.removeEventListener('message', receive);
  }, [refresh]);

  const followJob = useCallback(async (id: string, forProject: string) => {
    const generation = ++pollingGeneration.current;
    setJob({ jobId: id, projectId: forProject, kind: '', status: 'queued', progress: 0, message: '任务已提交，等待处理' });
    let failures = 0;
    while (mounted.current && generation === pollingGeneration.current) {
      try {
        const current = await client.job(id);
        if (generation !== pollingGeneration.current) return;
        setJob(current); failures = 0;
        if (current.status === 'completed') {
          await refresh(forProject); await refreshProjects();
          setNotice(`${JOB_LABELS[current.kind] ?? '操作'}已完成`);
          emitHost('project-updated', { projectId: forProject }); return true;
        }
        if (current.status === 'failed') { setError(current.error || current.message || '任务未完成'); await refresh(forProject); return false; }
        if (current.status === 'cancelled') { await refresh(forProject); setNotice('任务已取消，已完成的项目修订保持可用'); return false; }
      } catch (reason) {
        failures++;
        if (failures >= 4) { setError(`任务状态读取中断：${errorText(reason)}。刷新项目后可恢复进度。`); return false; }
      }
      await new Promise((resolve) => window.setTimeout(resolve, 900));
    }
  }, [client, refresh, refreshProjects]);
  useEffect(() => {
    if (project?.activeJobId && job?.jobId!==project.activeJobId && !busy) void followJob(project.activeJobId, project.id);
  }, [project?.id, project?.activeJobId, job, busy, followJob]);

  const execute = async (operation: () => Promise<{ jobId: string }>, kind: string) => {
    if (!project || active) return; setError(''); setBusy(true);
    try {
      const result = await operation();
      setJob({ jobId: result.jobId, projectId: project.id, kind, status: 'queued', progress: 0, message: '任务已提交' });
      void followJob(result.jobId, project.id);
    } catch (reason) {
      setError(errorText(reason));
      if (reason instanceof ApiError && reason.status === 409) await refresh().catch(() => undefined);
    } finally { setBusy(false); }
  };
  const createProject = async () => {
    if (!newName.trim() || busy) return; setBusy(true); setError('');
    try {
      const next = await client.create(newName.trim());
      setProjectId(next.id); await refreshProjects(); setShowCreate(false); setNewName(''); setShowImport(true);
    } catch (reason) { setError(errorText(reason)); } finally { setBusy(false); }
  };
  const importFiles = async () => {
    if (!project || (!stepFile && !documents.length) || active) return;
    if (stepFile && !/\.(step|stp)$/i.test(stepFile.name)) { setError('请选择 .step 或 .stp 几何文件'); return; }
    setBusy(true); setError('');
    try {
      for (const document of documents) await client.uploadDocument(project.id, document);
      if (stepFile) {
        setUploadProgress(0);
        const result = await client.uploadStep(project.id, stepFile, setUploadProgress);
        setShowImport(false); void followJob(result.jobId, project.id);
      } else { await refresh(); setShowImport(false); setNotice('配套资料已添加'); }
      setStepFile(null); setDocuments([]);
    } catch (reason) { setError(errorText(reason)); }
    finally { setBusy(false); setUploadProgress(null); }
  };
  const simplify = (local = false) => {
    if (!project) return;
    const choice = PURPOSES.find((value) => value.id === purpose)!;
    void execute(() => client.simplify(project.id, project.revision, {
      strategy: choice.strategy, purpose,
      componentIds: local ? selected : undefined, preserveContacts: effectivePreserveContacts, contactToleranceMm: tolerance,
    }), 'simplify');
  };
  const restore = async () => {
    if (!project || !selected.length || active) return;
    setBusy(true); setError('');
    try {
      let current = project;
      for (const id of selected) {
        const result = await client.restore(current.id, id, current.revision);
        const completed = await followJob(result.jobId, current.id);
        if (!completed) return;
        const updated = await refresh(current.id); if (!updated) break; current = updated;
      }
      setNotice(`已保留 ${selected.length} 个组件的原始几何与位姿`);
    } catch (reason) { setError(errorText(reason)); }
    finally { setBusy(false); }
  };
  const select = useCallback((id: string | null, additive = false) => {
    if (!id) return;
    setIsolate(true); setContactFaces([]);
    setSelected((values) => additive ? values.includes(id) ? values.filter((value) => value !== id) : [...values, id] : [id]);
  }, []);
  const applySemantics = async (groupId?: string) => {
    if (!project || active) return;
    if (!groupId && (!semanticEdit || !semanticName.trim() || !semanticReason.trim())) return;
    setBusy(true); setError('');
    try {
      await client.semantics(project.id, project.revision, groupId
        ? { action: 'ungroup', groupId, reason: '用户在工作台撤销语义分组，恢复原父级' }
        : { action: semanticEdit!, componentIds: selected, name: semanticName.trim(), reason: semanticReason.trim() });
      await refresh(); setSemanticEdit(null); setSemanticName(''); setSemanticReason('');
      setNotice(groupId ? '已还原分组前的装配层级' : '装配名称与分组已更新，实体和位姿未改变');
    } catch (reason) { setError(errorText(reason)); if (reason instanceof ApiError && reason.status === 409) await refresh().catch(() => undefined); }
    finally { setBusy(false); }
  };
  const askSelection = (override?:string[]) => {
    const chosen=override?project?.components.filter(c=>override.includes(c.id))??[]:selectedComponents; setContextMenu(null);
    if (chatTransferPending) return;
    if (window.parent === window) {
      setNotice('请在 DSH 插件工作台中打开，便可将所选组件带入原生聊天。'); return;
    }
    setError(''); setChatTransferPending(true); setNotice('正在将选择带入 DSH…');
    emitHost('ask-selection', { projectId: project?.id, revision: project?.revision,
      selection: chosen.map((component) => ({ nodeId: component.id, name: displayName(component) })), purpose, preserveContacts: effectivePreserveContacts,
      prompt: '请读取当前会话固定的建模 Skill、当前单机方案和安装接触证据。按我的要求修改当前方案，保持装配位姿，重建后复查接触；未知热属性保留未知。' });
  };
  const hideSelection = () => setHidden((values) => Array.from(new Set([...values, ...selected])));
  const allViewers = (action: (viewer: ViewerHandle) => void) => [originalViewer, simplifiedViewer].forEach((ref) => { if (ref.current) action(ref.current); });
  const hasGeometry = Boolean(project?.components.length);
  const originalUrl = client.artifactUrl(project?.artifacts.originalGlb);
  const simplifiedUrl = client.artifactUrl(project?.artifacts.simplifiedGlb || project?.artifacts.originalGlb);
  const preservedCount = project?.components.filter((component) => component.preserved).length ?? 0;
  const simplifiedCount = project?.components.filter((component) => component.strategy !== 'original' && component.recipe?.representation !== 'source').length ?? 0;
  const issueCount = (project?.checks.sourceCollisions?.length ?? 0)
    + (project?.checks.falsePositivePairs?.length ?? 0)
    + (project?.checks.errors?.length ?? 0);

  return <div className="app-shell">
    <header className="topbar">
      <div className="brand"><div className="brand-mark"><Satellite size={20} /></div><div><strong>卫星几何工作台</strong><span>SATELLITE GEOMETRY</span></div></div>
      <div className="project-switcher"><FolderOpen size={15} /><select aria-label="当前项目" value={projectId} onChange={(event) => setProjectId(event.target.value)} disabled={busy}>
        <option value="">选择几何项目</option>{projects.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
      </select><ChevronDown size={12} /><button className="icon-button" title="新建项目" aria-label="新建项目" onClick={() => setShowCreate(true)}><Plus size={17} /></button></div>
      <div className="topbar-right"><span className="mode-chip">热分析</span><button className="button subtle" onClick={()=>setShowSkill(true)}>Skill</button><span className={`connection ${connected ? 'online' : ''}`}><i />{connected ? '计算服务已连接' : '等待计算服务'}</span><button className="icon-button" aria-label="连接设置" title="连接设置" onClick={() => setShowSettings(true)}><Settings2 size={16} /></button></div>
    </header>

    <div className="workspace">
      <aside className="assembly-sidebar">
        <div className="sidebar-heading"><div><span className="eyebrow">PROJECT ASSEMBLY</span><h2>工程目录</h2></div><span className="count-badge">{project?.components.length ?? 0}</span></div>
        <button className="button import-button" disabled={!project || active} onClick={() => setShowImport(true)}><Upload size={15} />导入 STEP / 配套资料</button>
        <label className="tree-search"><Search size={14} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索组件或编号" aria-label="搜索组件" />{query && <button className="icon-button" aria-label="清空搜索" onClick={() => setQuery('')}><X size={12} /></button>}</label>
        <div className="tree-actions"><span>{selected.length ? `已选 ${selected.length} 项` : '点击定位 · Ctrl 多选'}</span><button onClick={() => setSelected(project?.components.map((component) => component.id) ?? [])}>全选</button><button onClick={() => {setSelected([]);setIsolate(false);}}>清空</button></div>
        <div className="tree-scroll">
          {initializing ? <div className="sidebar-empty"><LoaderCircle className="spin" size={22} /><span>正在读取项目</span></div> : !hasGeometry ? <div className="sidebar-empty"><Layers3 size={30} strokeWidth={1} /><strong>尚未导入装配</strong><span>STEP 中的零件与实例关系<br />将在此保留并呈现</span></div> : <AssemblyTree project={project!} query={query} selected={selected} hidden={hidden} collapsed={collapsed} onSelect={select} onContextMenu={menu} onToggle={(id) => setCollapsed((value) => { const next = new Set(value); if (next.has(id)) next.delete(id); else next.add(id); return next; })} onVisibility={(id) => setHidden((values) => values.includes(id) ? values.filter((value) => value !== id) : [...values, id])} />}
        </div>
        <div className="sidebar-footer"><ShieldCheck size={16}/><span>源 STEP 与原位姿保留</span></div>
      </aside>

      <main className="main-workspace">
        <div className="project-heading"><div><span className="eyebrow">GEOMETRY WORKSPACE</span><h1>{project?.name || '从一份 STEP 开始'}</h1><p>{hasGeometry ? `${project!.components.length} 个组件 · ${simplifiedCount} 个已简化 · ${preservedCount} 个保留原实体` : '在原始装配中理解、简化和校验卫星几何。'}</p></div><div className="heading-actions"><button className="button primary" disabled={!hasGeometry||active} onClick={()=>{if(window.parent===window||!sessionId){setNotice('请先在 DSH 工作台中创建或选择对话会话');return;}emitHost('run-workflow',{projectId:project?.id,revision:project?.revision,selection:[],prompt:'读取本会话固定的 Skill 和工程配套资料，整理所有单机中文名称和两层工程分类，按热分析用途建立合理简化方案并自主重建，默认保持原位姿，整理安装接触候选，不猜测物理参数。记录每项选择依据，检查后报告未知项。'});setNotice('已请求 DSH 开始建模，请查看左侧会话');}}><Sparkles size={14}/>一键建模</button>{project && <span className="revision">修订 {project.revision}</span>}<button className="button subtle" disabled={active || !project} onClick={() => { void refresh().then(() => setJob(null)).catch((reason) => setError(errorText(reason))); }} aria-label="刷新项目"><RefreshCw size={14} /></button></div></div>
        {error && <div className="banner error" role="alert"><CircleAlert size={16} /><span>{error}</span><button className="icon-button" aria-label="关闭错误提示" onClick={() => setError('')}><X size={14} /></button></div>}
        {notice && <div className={`banner ${chatTransferPending ? 'pending' : 'success'}`} role="status">{chatTransferPending ? <LoaderCircle className="spin" size={16} /> : <CheckCircle2 size={16} />}<span>{notice}</span><button className="icon-button" aria-label="关闭提示" onClick={() => setNotice('')}><X size={14} /></button></div>}
        <div className="workspace-tabs"><button className={tab === 'geometry' ? 'active' : ''} onClick={() => setTab('geometry')}><Box size={15} />几何视图</button><button className={tab === 'checks' ? 'active' : ''} onClick={() => setTab('checks')}><ShieldCheck size={15} />检查与问题{issueCount > 0 && <span className="tab-badge">{issueCount}</span>}</button><button className={tab === 'files' ? 'active' : ''} onClick={() => setTab('files')}><FileText size={15} />资料与导出</button></div>

        {tab === 'geometry' ? <div className="geometry-content">
          <div className="viewport-toolbar"><div className="segmented"><button className={comparison === 'original' ? 'active' : ''} onClick={() => setComparison('original')}>原始</button><button className={comparison === 'compare' ? 'active' : ''} onClick={() => setComparison('compare')}><ArrowLeftRight size={13} />对比</button><button className={comparison === 'simplified' ? 'active' : ''} onClick={() => setComparison('simplified')}>简化</button></div><div className="viewport-tools"><button className={cameraLocked?'is-on':''} onClick={()=>setCameraLocked(v=>!v)} title="锁定左右视角" aria-label="锁定左右视角">{cameraLocked?'同步视角':'独立视角'}</button><button onClick={()=>{setIsolate(false);setContactFaces([]);allViewers(v=>v.fit());}}>整星</button><button className={neighbours?'is-on':''} disabled={!selected.length} onClick={()=>{setNeighbours(v=>!v);setIsolate(true);}}>相邻安装件</button><button title="适应全部" aria-label="适应全部" onClick={() => allViewers((viewer) => viewer.fit())}><Maximize size={15} /></button><button title="聚焦所选" aria-label="聚焦所选" disabled={!selected.length} onClick={() => allViewers((viewer) => viewer.focus(selected))}><Focus size={15} /></button><button title="等轴视图" onClick={() => allViewers((viewer) => viewer.view('iso'))}>ISO</button><button title="俯视" onClick={() => allViewers((viewer) => viewer.view('top'))}>TOP</button><button className={wireframe ? 'is-on' : ''} title="线框" aria-label="线框显示" onClick={() => setWireframe((value) => !value)}><Box size={15} /></button></div></div>
          <div className={`viewports ${comparison === 'compare' ? 'comparison' : ''}`}>
            {comparison !== 'simplified' && <Viewer ref={originalViewer} url={originalUrl} title="原始几何" subtitle="SOURCE" selected={selected} hidden={viewHidden} wireframe={wireframe} onSelect={select} onContextMenu={menu} regions={contactFaces} onCameraChange={value=>syncCamera('original',value)} />}
            {comparison !== 'original' && <Viewer ref={simplifiedViewer} url={simplifiedUrl} title="简化结果" subtitle="ENVELOPE" selected={selected} hidden={viewHidden} wireframe={wireframe} onSelect={select} onContextMenu={menu} regions={contactFaces} onCameraChange={value=>syncCamera('simplified',value)} />}
            {!project && !initializing && <div className="welcome-card"><span className="welcome-icon"><Satellite size={27} /></span><h2>让复杂几何，变得清晰</h2><p>保留装配关系，为热分析和工程检查<br />建立可追溯的简化包络模型。</p><button className="button primary" onClick={() => setShowCreate(true)}><Plus size={16} />新建几何项目</button><small>支持 STEP · 原型与实例 · 人机协同</small></div>}
          </div>
          <div className="viewport-footer"><span><i className="green-dot" />简化保持装配位姿<span className="footer-divider">/</span>单位 mm</span><span>{hidden.length ? <button onClick={() => setHidden([])}><Eye size={12} />恢复 {hidden.length} 个隐藏组件</button> : '拖动旋转 · 滚轮缩放 · 点选组件'}</span></div>
        </div> : tab === 'checks' ? <ChecksPanel project={project} active={active} onRun={() => project && void execute(() => client.check(project.id, project.revision), 'check')} onSelect={(ids) => { setSelected(ids);setIsolate(true); setTab('geometry'); }} onContact={showContact} /> : <FilesPanel project={project} active={active} artifactUrl={client.artifactUrl} onUpload={() => setShowImport(true)} onDocument={(document) => { if (project) void client.document(project.id, document.id).then(setDocumentPreview).catch((reason) => setError(errorText(reason))); }} onExport={() => project && void execute(() => client.export(project.id, project.revision), 'export')} />}

        {job && <div className={`job-panel ${job.status === 'failed' ? 'failed' : ''}`} role="status"><div className="job-icon">{job.status === 'completed' ? <CheckCircle2 size={18} /> : job.status === 'failed' || job.status === 'cancelled' ? <CircleAlert size={18} /> : <LoaderCircle className="spin" size={18} />}</div><div className="job-copy"><div><strong>{JOB_LABELS[job.kind] ?? '几何处理'}</strong><span>{job.status === 'completed' ? '完成' : job.status === 'cancelled' ? '已取消' : `${Math.round(job.progress ?? 0)}%`}</span></div><p>{job.message || '正在计算，请稍候'}</p><div className="progress-track"><i style={{ width: `${Math.max(2, Math.min(100, job.progress ?? 0))}%` }} /></div></div>{['queued', 'running'].includes(job.status) ? <button className="button subtle" onClick={() => void client.cancelJob(job.jobId || job.id!).then(() => setNotice('已申请取消，将在当前几何步骤结束后停止')).catch((reason) => setError(errorText(reason)))}>取消</button> : <button className="icon-button" aria-label="收起任务进度" onClick={() => setJob(null)}><X size={14} /></button>}</div>}
      </main>

      <aside className="inspector-sidebar">
        {inspected && project ? <RecipeInspector component={inspected} project={project} active={Boolean(active)} client={client} sessionId={sessionId&&project.workflowBindings?.[sessionId]?sessionId:undefined} onRefresh={refresh} onError={setError} onChat={()=>askSelection()} onRebuild={(recipe,reason)=>void execute(()=>client.rebuildRecipe(project.id,project.revision,inspected.id,recipe,reason,sessionId&&project.workflowBindings?.[sessionId]?sessionId:undefined),'recipes')}/> : <section className="selection-section"><h2>单机详情</h2><div className="inspector-empty"><Focus size={25}/><p>{selected.length>1?`已选择 ${selected.length} 个组件`:'从目录或三维视图选择单机'}</p></div>{selected.length>0&&<button className="button subtle full" onClick={()=>askSelection()}>带入 DSH 聊天</button>}</section>}
        {selected.length>0&&<details className="inspector-tools"><summary>其他操作</summary><button className="button subtle full" disabled={active} onClick={()=>simplify(true)}>保守简化所选</button><button className="button subtle full" disabled={active} onClick={()=>void restore()}>恢复源几何与位姿</button><button className="button subtle full" onClick={hideSelection}>隐藏所选</button><button className="button subtle full" disabled={active} onClick={()=>{setSemanticEdit(selected.length===1?'rename':'group');setSemanticName(inspected?displayName(inspected):'');setSemanticReason('');}}>修改名称 / 分组</button></details>}
        {project&&<ContactDiagram project={project} selected={selected} onSelect={showContact}/>}
      </aside>
    </div>

    {showSkill&&<SkillPanel client={client} project={project} sessionId={sessionId} onClose={()=>setShowSkill(false)} onError={setError} onSelectVersion={id=>{emitHost('bind-skill',{projectId:project?.id,revision:project?.revision,skillId:id,selection:selectedComponents.map(c=>({nodeId:c.id,name:displayName(c)}))});setNotice('已请求绑定建模版本');}}/>}
    {contextMenu&&<div className="context-menu" role="menu" style={{left:Math.min(contextMenu.x,window.innerWidth-180),top:Math.min(contextMenu.y,window.innerHeight-100)}}><button role="menuitem" onClick={()=>askSelection([contextMenu.id])}><MessageSquare size={14}/>加入 DSH 会话</button><button role="menuitem" onClick={()=>{select(contextMenu.id);setContextMenu(null);}}>检查单机</button><button role="menuitem" onClick={()=>setContextMenu(null)}>关闭</button></div>}
    {editingContact&&project&&<Modal title="安装与热接触" subtitle={`${editingContact.a.componentId} ↔ ${editingContact.b.componentId}`} onClose={()=>setEditingContact(null)}><div className="contact-editor">{(['a','b'] as const).map(side=><label className="form-field" key={side}>{side==='a'?'组件 A 安装区域':'组件 B 安装区域'}<select value={editingContact[side].regionId??''} onChange={e=>setEditingContact(c=>c?{...c,[side]:{...c[side],regionId:e.target.value||null}}:c)}><option value="">待定义</option>{project.components.find(c=>c.id===editingContact[side].componentId)?.installationRegions?.map(r=><option key={r.id} value={r.id}>{r.name}</option>)}</select></label>)}<label className="form-field">状态<select value={editingContact.status} onChange={e=>setEditingContact(c=>c?{...c,status:e.target.value as ThermalContact['status'],origin:'manual'}:c)}><option value="candidate">候选</option><option value="confirmed">工程师确认</option><option value="needs_review">待复核</option><option value="excluded">已排除</option></select></label><label className="form-field">判断依据<textarea rows={3} value={editingContact.evidence} onChange={e=>setEditingContact(c=>c?{...c,evidence:e.target.value,origin:'manual'}:c)}/></label><label className="form-field">接触面积 / mm²<input type="number" min={0} value={editingContact.areaMm2??''} placeholder="未知" onChange={e=>setEditingContact(c=>c?{...c,areaMm2:e.target.value===''?null:Number(e.target.value),origin:'manual'}:c)}/></label><label className="form-field">热导通 / W·K⁻¹<input type="number" min={0} value={editingContact.conductanceWPerK??''} placeholder="未知" onChange={e=>setEditingContact(c=>c?{...c,conductanceWPerK:e.target.value===''?null:Number(e.target.value),origin:'manual'}:c)}/></label></div><div className="modal-actions"><button className="button subtle" onClick={()=>setEditingContact(null)}>查看三维区域</button><button className="button primary" disabled={active} onClick={()=>void client.updateContacts(project.id,project.revision,[editingContact]).then(async()=>{await refresh();setEditingContact(null);}).catch(e=>setError(errorText(e)))}>保存接触定义</button></div></Modal>}
    {showCreate && <Modal title="新建几何项目" subtitle="为一份卫星装配建立独立、可追溯的简化项目。" onClose={() => !busy && setShowCreate(false)}><form onSubmit={(event) => { event.preventDefault(); void createProject(); }}><label className="form-field">项目名称<input autoFocus value={newName} onChange={(event) => setNewName(event.target.value)} maxLength={100} placeholder="例如：遥感卫星 · 热分析包络" /></label><div className="modal-actions"><button type="button" className="button subtle" onClick={() => setShowCreate(false)} disabled={busy}>取消</button><button className="button primary" disabled={!newName.trim() || busy}>{busy ? <LoaderCircle className="spin" size={15} /> : <Plus size={15} />}创建并导入</button></div></form></Modal>}
    {showImport && <Modal title={hasGeometry ? '添加或更新项目输入' : '导入卫星几何'} subtitle="STEP 提供几何与装配关系，配套资料用于补充工程语义。" onClose={() => !busy && setShowImport(false)}><label className="file-drop"><Upload size={25} /><strong>{stepFile?.name ?? '选择 STEP / STP 文件'}</strong><span>{stepFile ? `${finite(stepFile.size / 1024 / 1024, 2)} MB` : '保留原始坐标、装配层级及重复实例'}</span><input type="file" accept=".step,.stp" disabled={busy} onChange={(event) => setStepFile(event.target.files?.[0] ?? null)} /></label>{hasGeometry && <p className="small-note">重新导入 STEP 将建立新的几何修订，请在导入完成后重新检查简化结果。</p>}<label className="document-drop"><FileText size={20} /><div><strong>配套资料（可选）</strong><span>需求说明、组件清单、材料或热设计要求</span></div><input type="file" multiple accept=".pdf,.docx,.xlsx,.csv,.txt,.md,.json" disabled={busy} onChange={(event) => setDocuments(Array.from(event.target.files ?? []))} /><Plus size={17} /></label>{documents.length > 0 && <div className="upload-file-list">{documents.map((file, index) => <div key={`${file.name}-${index}`}><FileText size={13} /><span>{file.name}</span><button className="icon-button" onClick={() => setDocuments((values) => values.filter((_, i) => i !== index))} aria-label={`移除 ${file.name}`}><X size={12} /></button></div>)}</div>}{uploadProgress !== null && <div className="upload-progress"><span>上传几何文件 {Math.round(uploadProgress)}%</span><div className="progress-track"><i style={{ width: `${uploadProgress}%` }} /></div></div>}<div className="modal-actions"><button className="button subtle" onClick={() => setShowImport(false)} disabled={busy}>取消</button><button className="button primary" disabled={active || (!stepFile && !documents.length)} onClick={() => void importFiles()}>{busy ? <LoaderCircle className="spin" size={15} /> : <Upload size={15} />}{stepFile ? '导入并解析装配' : '添加资料'}</button></div></Modal>}
    {showSettings && <Modal title="计算服务连接" subtitle="在 DSH 中由插件统一连接；独立使用时可以指定服务地址。" onClose={() => setShowSettings(false)}><form onSubmit={(event) => { event.preventDefault(); setError(''); setShowSettings(false); void refreshProjects().catch((reason) => setError(errorText(reason))); }}><label className="form-field">接口地址<input value={apiBase} onChange={(event) => setApiBase(event.target.value)} placeholder="/api/cad" /></label><label className="inline-field">接触容差 / mm<input type="number" min={0} max={10} step={0.01} value={tolerance} onChange={e=>setTolerance(Number(e.target.value))}/></label><p className="small-note">本机 DSH 默认使用 /api/cad。独立开发可使用计算服务的完整 /api 地址。</p><div className="modal-actions"><button className="button primary">连接服务</button></div></form></Modal>}
    {documentPreview && <Modal title={documentPreview.name} subtitle={documentPreview.extractionStatus === 'extracted' ? '已提取文字，可供 DSH 理解资料和追溯来源。' : '未提取到可用文字，扫描文档可能需要 OCR。'} onClose={() => setDocumentPreview(null)}>{documentPreview.warnings?.map((warning, index) => <p className="small-note" key={index}>{warning}</p>)}<pre className="document-preview">{documentPreview.text || '暂无可读文字。原始资料已保留。'}</pre><div className="modal-actions"><button className="button primary" onClick={() => setDocumentPreview(null)}>完成</button></div></Modal>}
    {semanticEdit && <Modal title={semanticEdit === 'rename' ? '修改组件名称' : '整理装配分组'} subtitle="仅调整工作装配树中的名称与分组，保留原始实体映射和位姿。" onClose={() => !busy && setSemanticEdit(null)}><label className="form-field">{semanticEdit === 'rename' ? '组件名称' : '分组名称'}<input autoFocus value={semanticName} onChange={(event) => setSemanticName(event.target.value)} maxLength={200} /></label><label className="form-field semantic-reason">整理依据<textarea value={semanticReason} onChange={(event) => setSemanticReason(event.target.value)} rows={3} placeholder="例如：根据组件清单，将同一分系统的安装部件归为一组" /></label><div className="modal-actions"><button className="button subtle" disabled={busy} onClick={() => setSemanticEdit(null)}>取消</button><button className="button primary" disabled={busy || !semanticName.trim() || !semanticReason.trim()} onClick={() => void applySemantics()}>保存装配关系</button></div></Modal>}
    {error && (showCreate || showImport || showSettings || semanticEdit) && <div className="modal-error" role="alert"><CircleAlert size={16} /><span>{error}</span><button className="icon-button" onClick={() => setError('')} aria-label="关闭错误"><X size={13} /></button></div>}
  </div>;
}

function Modal({ title, subtitle, onClose, children }: { title: string; subtitle: string; onClose: () => void; children: React.ReactNode }) {
  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}><section className="modal" role="dialog" aria-modal="true" aria-label={title}><header><div><h2>{title}</h2><p>{subtitle}</p></div><button className="icon-button" onClick={onClose} aria-label="关闭对话框"><X size={18} /></button></header>{children}</section></div>;
}

function AssemblyTree({project,query,selected,hidden,collapsed,onSelect,onToggle,onVisibility,onContextMenu}:{project:Project;query:string;selected:string[];hidden:string[];collapsed:Set<string>;onSelect:(id:string|null,additive?:boolean)=>void;onToggle:(id:string)=>void;onVisibility:(id:string)=>void;onContextMenu:(id:string,x:number,y:number)=>void}) {
  const search=query.toLowerCase().trim();
  const groups=new Map<string,typeof project.components>();
  for(const c of project.components){if(search&&!`${displayName(c)} ${c.sourceName??c.name} ${c.id}`.toLowerCase().includes(search))continue;const group=c.engineeringGroup??'待分类';groups.set(group,[...(groups.get(group)??[]),c]);}
  return <div role="tree" aria-label="工程组件">{[...groups].map(([name,items])=><div key={name}><button className="tree-group" aria-expanded={!collapsed.has(name)} onClick={()=>onToggle(name)}>{collapsed.has(name)?<ChevronRight size={13}/>:<ChevronDown size={13}/>}<Layers3 size={14}/><span>{name}</span><small>{items.length}</small></button>{!collapsed.has(name)&&items.map(c=><div key={c.id} role="treeitem" className={`tree-node ${selected.includes(c.id)?'selected':''} ${hidden.includes(c.id)?'hidden':''}`} onContextMenu={e=>{e.preventDefault();onContextMenu(c.id,e.clientX,e.clientY);}}><Minus size={8}/><button className="tree-label" onClick={e=>onSelect(c.id,e.ctrlKey||e.metaKey||e.shiftKey)} title={`${displayName(c)} · ${c.sourceName??c.name} · ${c.id}`}><Box size={14}/><span>{displayName(c)}</span></button><button className="tree-eye" aria-label="切换组件可见性" onClick={()=>onVisibility(c.id)}>{hidden.includes(c.id)?<EyeOff size={12}/>:<Eye size={12}/>}</button></div>)}</div>)}</div>;
}

function issueIds(issue: CheckIssue): string[] {
  if (typeof issue === 'string') return [];
  const values = issue.componentIds ?? issue.components ?? issue.pair;
  if (Array.isArray(values)) return values.filter((value): value is string => typeof value === 'string');
  return [issue.a, issue.b, issue.componentA, issue.componentB].filter((value): value is string => typeof value === 'string');
}
function issueDescription(issue: CheckIssue) {
  if (typeof issue === 'string') return issue;
  return String(issue.message ?? issue.description ?? issue.reason ?? issue.error ?? (issueIds(issue).join(' ↔ ') || '需要查看详细检查报告'));
}
function ChecksPanel({project,active,onRun,onSelect,onContact}:{project:Project|null;active:boolean;onRun:()=>void;onSelect:(ids:string[])=>void;onContact:(c:ThermalContact)=>void}) {
  const checks=project?.checks;
  const groups=[{title:'原始真实干涉',items:checks?.sourceCollisions??[]},{title:'简化新增重叠',items:checks?.falsePositivePairs??[]},{title:'未完成检查',items:checks?.errors??[]}];
  return <div className="content-page checks-page"><div className="content-page-heading"><h2>干涉与安装接触</h2><button className="button primary" disabled={!project?.components.length||active} onClick={onRun}><ShieldCheck size={15}/>检查几何与贴面</button></div><div className="check-status-strip"><span>源几何：{checks?.sourceComplete?'检查完成':'未确定'}</span><span>简化几何：{checks?.envelopeComplete?'检查完成':'待检查 / 未确定'}</span></div>{groups.map(g=><section className="check-group" key={g.title}><header><h3>{g.title} · {g.items.length}</h3></header>{g.items.length?<div className="issues-list">{g.items.map((issue,i)=><button key={i} disabled={!issueIds(issue).length} onClick={()=>onSelect(issueIds(issue))}><CircleAlert size={14}/><span>{issueDescription(issue)}</span></button>)}</div>:<p className="no-issues">{checks?.sourceComplete?'暂无记录':'未确定'}</p>}</section>)}{project&&<ContactDiagram project={project} selected={[]} onSelect={onContact}/>}<details className="check-scope"><summary>检查范围与未知项</summary>{checks?.warnings?.map((w,i)=><p key={i}>{issueDescription(w)}</p>)}</details></div>;
}

function FilesPanel({ project, active, artifactUrl, onUpload, onExport, onDocument }: { project: Project | null; active: boolean; artifactUrl: (path?: string) => string | undefined; onUpload: () => void; onExport: () => void; onDocument: (document: ProjectDocument) => void }) {
  const exported = exportPresentation(project?.lastExport, Boolean(project?.artifacts.step));
  const artifacts = [
    { key: 'step', name: '简化模型 · STEP', detail: exported.state === 'review' ? '仅供复核用途；请先确认上方检查说明' : '几何实体；适用性以检查与复核结果为准', format: 'STEP' },
    { key: 'recipes', name: '单机方案与热属性', detail: '面壳厚度、材料、已知参数及稳定标识', format: 'JSON' },
    { key: 'contacts', name: '热接触关系清单', detail: '接触组件对、完整性和确认事项', format: 'JSON' },
    { key: 'bundle', name: '项目导出包', detail: 'STEP、GLB、组件属性与接触清单', format: 'ZIP' },
  ];
  return <div className="content-page files-page">
    <div className="content-page-heading"><div><h2>项目资料与产物</h2><p>输入资料、简化结果和检查报告属于同一项目修订。</p></div><button className="button primary" disabled={!project?.components.length || active} onClick={onExport}><ArrowDownToLine size={15} />生成导出包</button></div>
    <section className={`export-status ${exported.state}`} aria-label="STEP 导出检查状态" role="status">
      {exported.state === 'passed' ? <ShieldCheck size={22} /> : exported.state === 'review' || exported.state === 'unknown' ? <CircleAlert size={22} /> : <FileText size={22} />}
      <div><strong>{exported.title}</strong><p>{exported.detail}</p>
        {project?.lastExport?.invalidSourceComponentIds?.length ? <p>源模型中有 {project.lastExport.invalidSourceComponentIds.length} 个组件未通过拓扑检查。</p> : null}
        {project?.lastExport?.warnings?.length ? <details><summary>查看导出检查说明</summary>{project.lastExport.warnings.map((warning, index) => <p key={index}>{warning}</p>)}</details> : null}
      </div>
    </section>
    <div className="artifact-grid">{artifacts.map((artifact) => { const url = artifactUrl(project?.artifacts[artifact.key]); return <div className={`artifact-card ${url ? 'available' : ''}`} key={artifact.key}><span className="file-format">{artifact.format}</span><h3>{artifact.name}</h3><p>{artifact.detail}</p>{url ? <a href={url} target="_blank" rel="noreferrer" download><ArrowDownToLine size={14} />下载产物</a> : <span className="pending-file">尚未生成</span>}</div>; })}</div>
    <section className="documents-section"><div className="section-title"><h2>配套资料</h2><button className="button subtle" disabled={!project || active} onClick={onUpload}><Plus size={14} />添加资料</button></div><p className="small-note">在左侧聊天中说明项目名称，或先从几何视图选择组件并带入聊天，再请 DSH 阅读配套资料。</p>{project?.documents?.length ? project.documents.map((document, index) => <button className="document-row" key={index} onClick={() => onDocument(document)}><FileText size={18} /><span>{document.name}</span><small>{document.extractionStatus === 'extracted' ? '文字已提取' : document.extractionStatus === 'needs_ocr' ? '需要 OCR' : '查看资料'}</small><ArrowUpRight size={13} /></button>) : <div className="empty-documents"><FileText size={25} strokeWidth={1.2} /><p>可添加组件清单、需求说明和材料资料，<br />也可以只使用 STEP 完成几何简化。</p></div>}</section>
  </div>;
}
