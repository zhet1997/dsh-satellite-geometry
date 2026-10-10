import { useEffect, useState } from 'react';
import { Copy, FileCode2, Plus, RefreshCw, Save, X } from 'lucide-react';
import type { CadClient } from './api';
import type { CadComponent, Project, Recipe, RecipePart, SkillVersion, ThermalContact } from './types';

export function displayName(c: CadComponent) {
  const name = c.displayName || (/[\u4e00-\u9fff]/.test(c.name) ? c.name : `待识别单机 ${c.id.slice(1)}`);
  return c.nameStatus === 'candidate' ? `${name}（待核实）` : name;
}

function fromBounds(c: CadComponent): Recipe {
  const b = c.localBoundsMm ?? [0, 0, 0, ...(c.dimensionsMm ?? [10, 10, 10])];
  return { schemaVersion: 1, representation: 'solid', parts: [{ id: 'body', name: '主体', kind: 'box',
    centerMm: [0, 1, 2].map(i => (b[i] + b[i+3]) / 2), sizeMm: [0, 1, 2].map(i => b[i+3]-b[i]) }],
    thermal: {}, regions: [], dimensionBasis: '源 STEP 实测局部包围尺寸', notes: '' };
}

export function RecipeInspector({ component, project, active, client, sessionId, onRebuild, onRefresh, onError, onChat }: {
  component: CadComponent; project: Project; active: boolean; client: CadClient;
  sessionId?: string;
  onRebuild: (recipe: Recipe, reason: string) => void; onRefresh: () => Promise<unknown>;
  onError: (message: string) => void; onChat: () => void;
}) {
  const [draft, setDraft] = useState<Recipe>(component.recipe ?? fromBounds(component));
  const [reason, setReason] = useState('');
  const [copyName, setCopyName] = useState('');
  const [saving, setSaving] = useState(false);
  const [jsonMode, setJsonMode] = useState(false);
  const [json, setJson] = useState('');
  useEffect(() => { setDraft(component.recipe ?? fromBounds(component)); setReason(''); setCopyName(''); setJsonMode(false); }, [component.id, project.revision]);
  useEffect(() => { if (!jsonMode) setJson(JSON.stringify(draft, null, 2)); }, [draft, jsonMode]);
  const toggleJson = () => {
    try { if (jsonMode) setDraft(JSON.parse(json) as Recipe); setJsonMode(!jsonMode); }
    catch (e) { onError(e instanceof Error ? e.message : '方案 JSON 不正确'); }
  };
  const setPart = (i: number, value: Partial<RecipePart>) => setDraft(d => ({ ...d, parts: d.parts.map((p, index) => i === index ? { ...p, ...value } : p) }));
  const makeTemplate = (kind: 'box' | 'cylinder_base' | 'shell' | 'source') => {
    const d = fromBounds(component), main = d.parts[0], size = main.sizeMm!;
    if (kind === 'source') { d.representation = 'source'; d.parts = [{ id: 'body', name: '源几何', kind: 'source', centerMm: [0, 0, 0] }]; }
    if (kind === 'shell') d.representation = 'surface_shell';
    if (kind === 'cylinder_base') {
      const h = size[2] * .15;
      d.parts = [{ ...main, id: 'base', name: '矩形底座', centerMm: [main.centerMm[0], main.centerMm[1], main.centerMm[2] - size[2]/2 + h/2], sizeMm: [size[0], size[1], h] },
        { id: 'body', name: '圆柱主体', kind: 'cylinder', centerMm: [main.centerMm[0], main.centerMm[1], main.centerMm[2]+h/2], radiusMm: Math.min(size[0],size[1])/2, heightMm: size[2]-h, axis: [0,0,1] }];
    }
    d.regions = [{ id: 'mount', name: '底部安装面', partId: d.parts[0].id, selector: 'zmin' }];
    d.thermal = { ...component.recipe?.thermal };
    setDraft(d); setJsonMode(false);
  };
  const saveCopy = async () => {
    if (!copyName.trim()) return;
    setSaving(true);
    try { await client.saveRecipeCopy(project.id, project.revision, component.id, copyName.trim(), sessionId); await onRefresh(); }
    catch (e) { onError(e instanceof Error ? e.message : '副本未保存'); }
    finally { setSaving(false); }
  };
  const submit = () => {
    try { onRebuild(jsonMode ? JSON.parse(json) as Recipe : draft, reason.trim() || '工程师在工作台修改单机建模方案'); }
    catch (e) { onError(e instanceof Error ? e.message : '方案格式不正确'); }
  };
  return <section className="recipe-inspector">
    <div className="section-title"><h2>{displayName(component)}</h2><span>{component.id}</span></div>
    <div className="inspector-subline">{component.sourceName || component.name}</div>
    {component.identityEvidence && <details><summary>名称依据 · {component.nameStatus==='identified'?'已识别':component.nameStatus==='candidate'?'待核实':'待识别'}</summary><p>{component.identityEvidence.basis}</p></details>}
    <fieldset className="recipe-fields" disabled={active || jsonMode}>
    <div className="recipe-presets"><button disabled={active} onClick={() => makeTemplate('box')}>盒体</button><button disabled={active} onClick={() => makeTemplate('cylinder_base')}>圆柱＋底座</button><button disabled={active} onClick={() => makeTemplate('shell')}>面壳</button><button disabled={active} onClick={() => makeTemplate('source')}>源几何</button></div>
    <label className="form-field">表示<select value={draft.representation} onChange={e => setDraft(d => ({ ...d, representation: e.target.value as Recipe['representation'] }))}><option value="solid">实体</option><option value="surface_shell">面壳</option><option value="source">源几何</option></select></label>
    <div className="section-title recipe-title"><h3>几何组成</h3><button className="icon-button" title="添加组成" disabled={active || draft.representation === 'source'} onClick={() => setDraft(d => ({ ...d, parts: [...d.parts, { id: `part_${Date.now()}`, name: '组成', kind: 'box', centerMm: [0,0,0], sizeMm: [10,10,10] }] }))}><Plus size={14}/></button></div>
    {draft.parts.map((p,i) => <div key={p.id} className="recipe-part"><div className="recipe-part-heading"><input aria-label={`组成 ${i+1} 名称`} value={p.name} onChange={e => setPart(i, {name:e.target.value})}/><span>{p.kind === 'box' ? '盒体' : p.kind === 'cylinder' ? '圆柱' : '原几何'}</span>{draft.parts.length>1 && <button aria-label="删除组成" onClick={() => setDraft(d => ({...d,parts:d.parts.filter((_,n)=>n!==i),regions:d.regions.filter(r=>r.partId!==p.id)}))}><X size={12}/></button>}</div>
      {p.kind !== 'source' && <><VectorInput label="中心 / mm" values={p.centerMm} onChange={v=>setPart(i,{centerMm:v})}/>{p.kind==='box' ? <VectorInput label="尺寸 / mm" values={p.sizeMm??[10,10,10]} onChange={v=>setPart(i,{sizeMm:v})}/> : <><div className="metadata-numbers"><label>半径 / mm<input type="number" min={.001} value={p.radiusMm??1} onChange={e=>setPart(i,{radiusMm:Number(e.target.value)})}/></label><label>高度 / mm<input type="number" min={.001} value={p.heightMm??1} onChange={e=>setPart(i,{heightMm:Number(e.target.value)})}/></label></div><VectorInput label="轴向" values={p.axis??[0,0,1]} onChange={v=>setPart(i,{axis:v})}/></>}</>}
    </div>)}
    <details className="recipe-thermal" open={draft.representation==='surface_shell'}><summary>热属性与壳厚</summary><label className="form-field">材料<input value={draft.thermal.material??''} placeholder="未知" onChange={e=>setDraft(d=>({...d,thermal:{...d.thermal,material:e.target.value||null}}))}/></label><div className="metadata-numbers">{([{key:'thicknessMm',label:'壳厚 / mm'},{key:'massKg',label:'质量 / kg'},{key:'specificHeatJPerKgK',label:'比热 / J·kg⁻¹·K⁻¹'},{key:'conductivityWPerMK',label:'导热 / W·m⁻¹·K⁻¹'},{key:'powerW',label:'功耗 / W'}] as const).map(f=><label key={f.key}>{f.label}<input type="number" min={0} value={draft.thermal[f.key]??''} placeholder="未知" onChange={e=>setDraft(d=>({...d,thermal:{...d.thermal,[f.key]:e.target.value===''?null:Number(e.target.value)}}))}/></label>)}</div></details>
    <details className="recipe-regions"><summary>安装区域 · {draft.regions.length}</summary>{draft.regions.map((r,i)=><div className="region-row" key={r.id}><input value={r.name} aria-label="区域名称" onChange={e=>setDraft(d=>({...d,regions:d.regions.map((x,n)=>n===i?{...x,name:e.target.value}:x)}))}/><select aria-label="区域组成" value={r.partId} onChange={e=>setDraft(d=>({...d,regions:d.regions.map((x,n)=>n===i?{...x,partId:e.target.value}:x)}))}>{draft.parts.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select><select aria-label="安装面" value={r.selector} onChange={e=>setDraft(d=>({...d,regions:d.regions.map((x,n)=>n===i?{...x,selector:e.target.value as typeof r.selector}:x)}))}>{['xmin','xmax','ymin','ymax','zmin','zmax','lateral','all'].map(v=><option key={v} value={v}>{({zmin:'底面',zmax:'顶面',lateral:'圆柱侧面',all:'全部面'} as Record<string,string>)[v]??v}</option>)}</select><button aria-label="删除区域" onClick={()=>setDraft(d=>({...d,regions:d.regions.filter((_,n)=>n!==i)}))}><X size={12}/></button></div>)}<button className="button subtle full" onClick={()=>setDraft(d=>({...d,regions:[...d.regions,{id:`region_${Date.now()}`,name:'安装区域',partId:d.parts[0].id,selector:'zmin'}]}))}><Plus size={13}/>添加区域</button></details>
    <label className="form-field">尺寸依据<input value={draft.dimensionBasis} onChange={e=>setDraft(d=>({...d,dimensionBasis:e.target.value}))}/></label>
    <label className="form-field">修改意见<textarea rows={2} value={reason} onChange={e=>setReason(e.target.value)} placeholder="记录本次工程判断"/></label>
    </fieldset>
    <details><summary>方案 JSON</summary><button className="button subtle" disabled={active} onClick={toggleJson}>{jsonMode?'返回表单':'编辑 JSON'}</button><textarea className="recipe-json" aria-label="方案 JSON" readOnly={!jsonMode} rows={10} value={json} onChange={e=>setJson(e.target.value)}/></details>
    <button className="button primary full" disabled={active||saving} onClick={submit}><RefreshCw size={14}/>应用并重建</button>
    <button className="button subtle full" onClick={onChat}>带入 DSH 聊天</button>
    <div className="recipe-copies"><h3>方案副本</h3><div className="copy-save"><input value={copyName} onChange={e=>setCopyName(e.target.value)} placeholder="副本名称" aria-label="方案副本名称"/><button className="icon-button" title="保存当前已应用方案为副本" disabled={active||saving||!copyName.trim()} onClick={()=>void saveCopy()}><Copy size={15}/></button></div>{component.recipeCopies?.map(c=><div key={c.id} className="copy-row"><span>{c.name}</span><button disabled={active||saving} onClick={()=>void client.loadRecipeCopy(project.id,project.revision,component.id,c.id,sessionId).then(async result=>{await onRefresh(); window.dispatchEvent(new CustomEvent('satcad-job',{detail:result}));}).catch(e=>onError(String(e)))}>载入</button></div>)}</div>
    <details><summary>原始组成 · {component.sourceNodeIds?.length??1}</summary><div className="source-geometry-list">{(component.sourceNodeIds??[component.id]).slice(0,200).map(id=><div key={id}>{project.tree.find(n=>n.id===id)?.name??id}<span>{id}</span></div>)}{(component.sourceNodeIds?.length??0)>200&&<span>完整映射保存在源装配树与导出清单中</span>}</div></details>
    {component.outputGeometry && <dl className="component-metrics"><div><dt>输出面 / 实体</dt><dd>{component.outputGeometry.faceCount} / {component.outputGeometry.solidCount}</dd></div><div><dt>表示检查</dt><dd>{component.outputGeometry.passed?'有效':'待复核'}</dd></div></dl>}
  </section>;
}

function VectorInput({label,values,onChange}:{label:string;values:number[];onChange:(v:number[])=>void}) {
  return <label className="vector-field"><span>{label}</span><div>{values.map((v,i)=><input key={i} aria-label={`${label} ${['X','Y','Z'][i]}`} type="number" step="any" value={v} onChange={e=>onChange(values.map((x,n)=>n===i?Number(e.target.value):x))}/>)}</div></label>;
}

export function SkillPanel({client,project,sessionId,onClose,onSelectVersion,onError}:{client:CadClient;project:Project|null;sessionId?:string;onClose:()=>void;onSelectVersion:(skillId:string)=>void;onError:(s:string)=>void}) {
  const [versions,setVersions]=useState<SkillVersion[]>([]),[selected,setSelected]=useState(''),[value,setValue]=useState<SkillVersion|null>(null),[resource,setResource]=useState(''),[importing,setImporting]=useState(false),[label,setLabel]=useState(''),[content,setContent]=useState('');
  const [resources,setResources]=useState<Record<string,string>>({});
  useEffect(()=>{void client.skills().then(r=>{setVersions(r.skills);setSelected((sessionId&&project?.workflowBindings?.[sessionId]?.skillId)||r.defaultSkillId);}).catch(e=>onError(String(e)));},[client,project?.id,sessionId]);
  useEffect(()=>{if(selected) void client.skill(selected).then(v=>{setValue(v);setResource('');}).catch(e=>onError(String(e)));},[client,selected]);
  const pinned = sessionId ? project?.workflowBindings?.[sessionId] : undefined;
  const importVersion=async()=>{try{const v=await client.importSkill(label,content,resources);setVersions(vs=>[v,...vs.filter(x=>x.id!==v.id)]);setSelected(v.id);setImporting(false);}catch(e){onError(String(e));}};
  return <div className="modal-backdrop"><section className="modal skill-modal" role="dialog" aria-modal="true" aria-label="Skill 版本"><header><h2>建模 Skill</h2><button className="icon-button" aria-label="关闭" onClick={onClose}><X size={18}/></button></header><select aria-label="Skill 版本" value={selected} onChange={e=>setSelected(e.target.value)}>{versions.map(v=><option key={v.id} value={v.id}>{v.label} · {v.fingerprint.slice(0,8)}</option>)}</select>{value&&<><div className="skill-fingerprint">SHA-256 {value.fingerprint}</div><div className="skill-resource-tabs"><button className={!resource?'active':''} onClick={()=>setResource('')}>SKILL.md</button>{Object.keys(value.resources??{}).map(name=><button key={name} onClick={()=>setResource(name)}>{name}</button>)}</div><pre className="skill-content">{resource?value.resources?.[resource]:value.content}</pre></>}
    {pinned&&<div className="skill-pin">当前会话：{pinned.skillFingerprint.slice(0,12)} · {pinned.loadedAt?'已读取':'待 Agent 读取'}</div>}
    {importing&&<div><label className="form-field">候选版本名称<input value={label} onChange={e=>setLabel(e.target.value)}/></label><label className="form-field">正文<textarea rows={8} value={content} onChange={e=>setContent(e.target.value)}/></label><label className="button subtle">导入 Markdown / JSON<input type="file" accept=".md,.json" onChange={e=>{const f=e.target.files?.[0];if(f)void f.text().then(t=>{if(f.name.endsWith('.json')){const x=JSON.parse(t);if(typeof x.content!=='string'||!x.content.trim())throw new Error('Skill JSON 缺少正文 content');setContent(x.content);setResources(x.resources??{});setLabel(x.label??f.name);}else{setContent(t);setResources({});setLabel(f.name);}}).catch(err=>onError(String(err)));}}/></label><button className="button primary" disabled={!label.trim()||!content.trim()} onClick={()=>void importVersion()}><Save size={14}/>保存候选版本</button></div>}
    <div className="modal-actions"><button className="button subtle" onClick={()=>{setImporting(!importing);setContent(value?.content??'');setLabel('候选版本');setResources(value?.resources??{});}}><FileCode2 size={14}/>导入 / 另存候选</button><button className="button primary" disabled={!project||!sessionId||!selected||(!!pinned&&pinned.skillId!==selected)} onClick={()=>{onSelectVersion(selected);onClose();}}>绑定当前会话</button></div>{pinned&&pinned.skillId!==selected&&<p className="skill-switch-note">在 DSH 新建会话后绑定此版本；当前会话保留已加载的规则。</p>}</section></div>;
}

export function ContactDiagram({project,selected,onSelect}:{project:Project;selected:string[];onSelect:(contact:ThermalContact)=>void}) {
  const contacts=(project.thermalContacts??[]).filter(c=>!selected.length||selected.includes(c.a.componentId)||selected.includes(c.b.componentId));
  const name=(id:string)=>{const c=project.components.find(x=>x.id===id);return c?displayName(c):id;};
  return <div className="contact-diagram"><div className="section-title"><h3>热接触关系</h3><span>{project.contactDiscovery?.status==='completed'?'几何识别完成':project.contactDiscovery?.status==='partial'?'部分识别':'待识别'}</span></div>{contacts.length?contacts.map(c=><button key={c.id} className={`contact-edge ${c.status}`} onClick={()=>onSelect(c)}><span>{name(c.a.componentId)}<small>{c.a.regionId??'安装区域待定义'}</small></span><span className="contact-edge-line"><i/>{c.areaMm2!==null?`${Number(c.areaMm2.toFixed(2))} mm²`:'面积未知'}<small>{({candidate:'候选',confirmed:'已确认',needs_review:'待复核',excluded:'已排除'})[c.status]}</small></span><span>{name(c.b.componentId)}<small>{c.b.regionId??'安装区域待定义'}</small></span></button>):<p className="contact-empty">{project.contactDiscovery?.status==='completed'?'该选区没有接触候选':'接触关系尚未确定'}</p>}</div>;
}
