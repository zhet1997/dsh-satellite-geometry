"""Generate a delivery report only from completed, consistent saved evidence."""
from __future__ import annotations
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = [
    ('原项目卫星装配', 'satellite-assembly-container'),
    ('原项目 CATCH', 'catch-container'),
    ('有效行星减速箱组件', 'gearbox-container'),
    ('Dawn 推进器源缺陷回归', 'thruster-container'),
]
EXPORT_LABELS = {
    'valid': '源与输出拓扑通过；工程适用性另行确认',
    'source_and_output_invalid_review_required': '源与输出拓扑无效；仅供复核与修复',
    'source_defects_review_required': '输出拓扑通过；源模型缺陷仍需复核',
}


def read(relative):
    return json.loads((ROOT / relative).read_text(encoding='utf-8-sig'))


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def passed_test_count(log):
    matches = list(re.finditer(r'^Ran (\d+) tests? in [^\r\n]+', log, re.MULTILINE))
    require(bool(matches), 'Backend test count is missing')
    final = matches[-1]
    require(log[final.end():].strip() == 'OK', 'Final backend tests did not finish with OK')
    count = int(final.group(1))
    require(count > 0, 'Backend test suite is empty')
    return count


def effective_check_status(checks, kind):
    reported = checks.get(f'{kind}Status', 'unknown')
    if reported == 'failed':
        return 'failed'
    if (checks.get('sourceComplete') is not True or checks.get('envelopeComplete') is not True
            or checks.get('errors') or checks.get('uncertainComponentIds')
            or any(checks.get('unknownPairCounts', {}).values())):
        return 'unknown'
    if reported not in {'passed', 'needs_review'}:
        return 'unknown'
    if kind == 'assembly' and (checks.get('sourceCollisions') or checks.get('falsePositivePairs')):
        return 'needs_review'
    return reported


def summarize_case(name, folder):
    location = f'validation/artifacts/{folder}'
    item = read(f'{location}/http-validation.json')
    require(item.get('status') == 'passed', f'Workflow evidence is incomplete: {name}')
    initial = read(f'{location}/initial-export-attempt.json')
    properties = read(f'{location}/properties.json')
    require(properties.get('projectId') == item.get('projectId'), f'Project evidence differs: {name}')
    require(properties.get('revision') == item.get('revision'), f'Revision evidence differs: {name}')
    checks, components, exported = properties['checks'], properties['components'], properties['export']
    require(checks == item['checks'] and exported == item.get('export'), f'HTTP and artifact evidence differ: {name}')
    require(all(type(exported.get(k)) is bool for k in ('stepReadable', 'stepReadbackValid', 'sourceTopologyValid')),
            f'Topology evidence is missing: {name}')
    require(exported['stepReadable'] is True, f'STEP is not readable: {name}')
    require(exported.get('instanceStructureVerified') is True, f'Instance structure is unverified: {name}')
    require(exported.get('acceptanceIsSeparate') is True, f'Missing engineering acceptance boundary: {name}')
    require(exported.get('stepOccurrenceCount') == len(components) == item['import']['componentCount'],
            f'Component/instance count differs: {name}')
    require(type(exported.get('stepPrototypeCount')) is int and 0 < exported['stepPrototypeCount'] <= len(components),
            f'Invalid prototype count: {name}')
    invalid_ids = exported.get('invalidSourceComponentIds')
    require(isinstance(invalid_ids, list), f'Missing source-defect list: {name}')
    require(all(cid in {c['id'] for c in components} for cid in invalid_ids), f'Unknown defect component: {name}')
    require(exported['sourceTopologyValid'] == (not invalid_ids), f'Contradictory source topology evidence: {name}')
    require(exported['stepReadbackValid'] or not exported['sourceTopologyValid'],
            f'New invalid output from valid source was published: {name}')
    expected = ('valid' if exported['sourceTopologyValid'] and exported['stepReadbackValid']
                else 'source_and_output_invalid_review_required' if not exported['stepReadbackValid']
                else 'source_defects_review_required')
    require(exported.get('status') == expected, f'Export status contradicts topology evidence: {name}')
    require(expected == 'valid' or bool(exported.get('warnings')), f'Missing review warning: {name}')
    step = item['artifacts']['step']
    step_path = ROOT / location / 'simplified.step'
    require(step_path.stat().st_size == step['bytes'] > 0, f'Downloaded STEP size differs: {name}')
    require(step['sha256'] == exported['stepSha256'], f'STEP digest evidence differs: {name}')
    poses_retained = bool(components) and all('pose' in c and 'originalPose' in c and c['pose'] == c['originalPose'] for c in components)
    require(poses_retained and 'all original component poses retained' in item['assertions'], f'Original poses not retained: {name}')
    preserved = sum(c['strategy'] == 'original' for c in components)
    simplified = len(components) - preserved
    require((simplified, preserved) == (item['simplifiedCount'], item['preservedCount']), f'Simplification counts differ: {name}')
    refinement = properties.get('envelopeRefinement') or {}
    case = {
        'name': name, 'folder': folder, 'projectId': item['projectId'], 'revision': item['revision'],
        'workflow': item['status'], 'workflowScope': 'saved simplification plus final HTTP export/download validation',
        'reusedCompletedSimplification': item.get('reusedCompletedSimplification', False),
        'componentCount': len(components), 'simplifiedCount': simplified, 'preservedCount': preserved,
        'finalExportElapsedSecondsIncludingQueue': item['elapsedSeconds'],
        'initialAttempt': {'path': f'{location}/initial-export-attempt.json', 'status': initial.get('status'),
                           'elapsedSecondsIncludingQueue': initial.get('elapsedSeconds'),
                           'jobs': [{k: j.get(k) for k in ('kind', 'status', 'createdAt', 'updatedAt', 'error')} for j in initial.get('jobs', [])]},
        'assemblyStatus': effective_check_status(checks, 'assembly'), 'thermalStatus': effective_check_status(checks, 'thermal'),
        'reportedAssemblyStatus': checks.get('assemblyStatus', 'unknown'), 'reportedThermalStatus': checks.get('thermalStatus', 'unknown'),
        'sourceComplete': checks.get('sourceComplete') is True, 'envelopeComplete': checks.get('envelopeComplete') is True,
        'sourceCollisionPairs': len(checks.get('sourceCollisions', [])), 'envelopeFalsePositivePairs': len(checks.get('falsePositivePairs', [])),
        'contactPairs': len(checks.get('contacts', [])), 'uncertainComponents': len(checks.get('uncertainComponentIds', [])),
        'unknownPairCounts': checks.get('unknownPairCounts', {}), 'sourcePairCacheHits': checks.get('sourcePairCacheHits'),
        'initialEnvelopeFalsePositivePairs': len(refinement.get('initialFalsePositivePairs', [])), 'refinementChanges': refinement.get('changes', []),
        'stepReadable': exported['stepReadable'], 'stepReadbackValid': exported['stepReadbackValid'],
        'sourceTopologyValid': exported['sourceTopologyValid'], 'invalidSourceComponentIds': invalid_ids,
        'exportStatus': exported['status'], 'exportWarnings': exported.get('warnings', []),
        'stepOccurrenceCount': exported['stepOccurrenceCount'], 'stepPrototypeCount': exported['stepPrototypeCount'],
        'stepBytes': step['bytes'], 'stepSha256': step['sha256'], 'instanceStructureVerified': exported['instanceStructureVerified'],
        'allPosesRetained': poses_retained, 'poseEvidenceScope': 'saved component pose fields equal originalPose fields',
        'finalExportPerInstanceWorldGeometryVerified': None,
        'engineeringAcceptance': 'not_certified', 'artifactFolder': location,
    }
    if folder in {'gearbox-container', 'thruster-container'}:
        require(len(components) == 1, f'Single-component regression changed: {name}')
        case['componentGeometry'] = {k: components[0].get(k) for k in ('faceCount', 'solidCount', 'dimensionsMm', 'strategy', 'sourceValid', 'sourceTopologyValid')}
    if folder == 'satellite-assembly-container':
        placement_path = 'validation/assembly-final-placement-check.json'
        placement = read(placement_path)
        require(placement.get('stepSha256') == step['sha256'], 'Placement check does not match final assembly STEP')
        require(type(placement.get('worldGeometryPlacementVerified')) is bool, 'Placement check is incomplete')
        require(placement.get('leafCount') == placement.get('geometryComparedCount') == len(components),
                'Placement check does not cover every exported assembly component')
        case['finalExportPerInstanceWorldGeometryVerified'] = placement['worldGeometryPlacementVerified']
        case['finalExportPlacement'] = {'path': placement_path, **{k: placement.get(k) for k in (
            'stepSha256', 'leafCount', 'geometryComparedCount', 'maxWorldMatrixAbsoluteDelta',
            'maxCadRoundedMatrixAbsoluteDelta', 'maxWorldGeometricBoundsAbsoluteDeltaMm',
            'allComparedFaceCountsMatch', 'worldGeometryPlacementVerified', 'allLocalShapeRootLocationsIdentity',
            'actualMergedGeometricBoundsMm', 'boundsMethodExplanation')}}
    if folder in {'satellite-assembly-container', 'catch-container'}:
        inspection_path = ('validation/assembly-final-inspection.json' if folder == 'satellite-assembly-container'
                           else 'validation/catch-final-inspection.json')
        independent = read(inspection_path)
        require(independent.get('inspectionPassed') is True and independent.get('sha256') == step['sha256'],
                f'Final independent inspection does not match downloaded STEP: {name}')
        require(independent['summary']['leafOccurrenceCount'] == len(components), f'Independent leaf count differs: {name}')
        case['finalIndependentInspection'] = {
            'path': inspection_path, 'sha256': independent['sha256'], 'leafOccurrenceCount': independent['summary']['leafOccurrenceCount'],
            'cadConservativeBoundsMm': independent['summary']['bounds'], 'snapshot': independent['snapshot'],
            'engineeringAccepted': independent['engineeringAccepted'],
        }
    if folder == 'gearbox-container':
        # Read face records from the final small STEP without rerunning a CAD job.
        step_text = step_path.read_text(encoding='ascii', errors='replace')
        case['componentGeometry']['exportedFaceEntityCount'] = len(re.findall(r'\bADVANCED_FACE\s*\(', step_text))
        case['componentGeometry']['exportedSolidEntityCount'] = len(re.findall(r'\bMANIFOLD_SOLID_BREP\s*\(', step_text))
        inspection = read('validation/gearbox-inspection.json')
        token = inspection['tokens'][0]
        require(inspection.get('ok') is True and token['stepHash'] == initial['artifacts']['step']['sha256'],
                'Independent gearbox inspection does not match the initial checked export')
        case['componentGeometry']['initialIndependentInspection'] = {
            'path': 'validation/gearbox-inspection.json', 'stepSha256': token['stepHash'],
            'faceCount': token['summary']['faceCount'], 'dimensionsMm': token['entryFacts']['size'],
        }
        final_inspection = read('validation/gearbox-final-inspection.json')
        final_token = final_inspection['tokens'][0]
        require(final_inspection.get('ok') is True and final_token['stepHash'] == step['sha256'],
                'Final gearbox inspection does not match the downloaded STEP')
        require(final_token['summary']['faceCount'] == case['componentGeometry']['exportedFaceEntityCount'],
                'Final gearbox face records differ from independent inspection')
        case['componentGeometry']['finalIndependentInspection'] = {
            'path': 'validation/gearbox-final-inspection.json', 'stepSha256': final_token['stepHash'],
            'faceCount': final_token['summary']['faceCount'], 'dimensionsMm': final_token['entryFacts']['size'],
            'leafOccurrenceCount': final_token['summary']['leafOccurrenceCount'],
            'shapeCount': final_token['summary']['shapeCount'],
        }
    return case


def main():
    cases = [summarize_case(name, folder) for name, folder in CASES]
    native = read('validation/native-integration-summary.json')
    package = read('validation/package-install-summary.json')
    persistence = read('validation/container-persistence-production.json')
    require(persistence.get('restartPersistencePassed') is True, 'Production restart has not passed')
    require(persistence.get('workbenchHttpReady') is True and persistence.get('dshProxyReady') is True, 'Post-restart HTTP evidence is missing')
    require(persistence.get('projectsBefore') == persistence.get('projectsAfter'), 'Restart snapshots differ')
    launcher_note = ('已停止独立 DSH 实例与正式 Compose 服务，再通过 Windows PowerShell 5.1 的桌面启动脚本成功启动；路径处理修正也已在停止状态复验。'
                     if persistence.get('launcherPathHandlingFixedAndRevalidated') is True else '')
    for case in cases:
        saved = persistence.get('projectsAfter', {}).get(case['projectId'], {})
        require(saved.get('revision') == case['revision'] and saved.get('stepSha256') == case['stepSha256'],
                f"Production restart does not cover final export: {case['name']}")
    backend_count = passed_test_count((ROOT / 'validation/backend-final-tests.log').read_text(encoding='utf-8-sig'))
    plugin_count = package.get('testsPassed')
    require(type(plugin_count) is int and plugin_count > 0, 'Plugin test count is missing')
    for key in ('productionDependenciesInstalled', 'hostEntrypointImports', 'finalPrebuiltClientAndViewerPresent',
                'isolatedProfileInstallerPasses', 'isolatedProfileLinkResolves', 'packed194ComponentSnapshotAndPaginationPass',
                'packedFilteredReadPreservesInvalidExportEvidence'):
        require(package.get(key) is True, f'Package validation is incomplete: {key}')
    package_path = ROOT / 'dist/lbk-dsh-satellite-geometry-0.1.0.tgz'
    require(package_path.stat().st_size == package['bytes'] and hashlib.sha256(package_path.read_bytes()).hexdigest() == package['sha256'],
            'Final package differs from installation evidence')
    require(native.get('assertions') and all(v is True for v in native['assertions'].values()), 'Native model validation is incomplete')
    ui = read('validation/ui-smoke.json')
    require(ui.get('assertions') and all(v is True for v in ui['assertions'].values()), 'Browser validation is incomplete')
    for key in ('invalidSourceExportWarningVisible', 'validExportTopologyStatusVisible',
                'workbenchConnectedAfterColdRestart', 'final194ComponentCandidateGlbVisible'):
        require(ui['assertions'].get(key) is True, f'Final export status browser check is missing: {key}')
    for key in ('finalScreenshot', 'exportWarningScreenshot', 'fullAssemblyCandidateScreenshot'):
        require(ui.get(key) and (ROOT / ui[key]).is_file(), f'Browser screenshot is missing: {key}')
    primary_snapshot = ui.get('fullAssemblyPrimaryStepSnapshot', {})
    if primary_snapshot.get('status') == 'failed':
        snapshot_note = (f"194 组件整星的独立 STEP 截图尝试 {primary_snapshot.get('attempts')} 次未完成，"
                         f"错误为 `{primary_snapshot.get('error')}`。已保留工作台中最终候选 GLB 的真实截图，"
                         "但它不能替代独立 STEP 截图；本报告不把该项视觉验收列为通过。")
    elif primary_snapshot.get('status') == 'passed':
        snapshot_note = '194 组件整星的独立 STEP 截图已完成，证据记录于 ui-smoke.json。'
    else:
        snapshot_note = '194 组件整星的独立 STEP 截图尚无完成证据，本报告不把该项视觉验收列为通过。'
    contact = read('validation/artifacts/container-contact/http-validation.json')
    require(contact.get('status') == 'passed' and 'four-foot contact area is 36 mm²' in contact.get('assertions', []), 'Contact regression is incomplete')
    generated = datetime.now(timezone.utc).isoformat()
    summary = {
        'generatedAt': generated, 'cases': cases, 'backendTestsPassed': backend_count, 'pluginTestsPassed': plugin_count,
        'claims': {'workflowCompletedIsNotTopologyValidity': True, 'topologyValidityIsNotEngineeringAcceptance': True,
                   'unknownIsNotPassed': True, 'engineeringAcceptance': 'not_certified'},
        'nativeModel': {'componentsMatched': native['componentsWithSourcedAttributes'], 'fieldsWritten': native['sourcedFieldCount'],
                        'unmatchedRemainUnknown': native['unmatchedComponentsRemainUnknown'], 'assertions': native['assertions'],
                        'dimensionMatchingIsIdentityCertification': False},
        'package': package, 'productionPersistence': persistence, 'ui': ui,
    }
    rows = '\n'.join(
        f"| {c['name']} | {c['componentCount']} | {c['simplifiedCount']} / {c['preservedCount']} | "
        f"{c['assemblyStatus']} / {c['thermalStatus']} | {c['sourceCollisionPairs']} | "
        f"{c['initialEnvelopeFalsePositivePairs']} → {c['envelopeFalsePositivePairs']} |" for c in cases)
    topology_rows = '\n'.join(
        f"| {c['name']} | {'是' if c['stepReadable'] else '否'} | "
        f"{'通过' if c['sourceTopologyValid'] else '未通过'}（{len(c['invalidSourceComponentIds'])}） | "
        f"{'通过' if c['stepReadbackValid'] else '未通过'} | {c['stepOccurrenceCount']} / {c['stepPrototypeCount']} | "
        f"{c['stepBytes']:,} | {EXPORT_LABELS[c['exportStatus']]} |" for c in cases)
    details = '\n\n'.join(
        f"- **{c['name']}**：接触候选 {c['contactPairs']} 对，未确定组件 {c['uncertainComponents']} 个。"
        f"未确定配对分类：`{json.dumps(c['unknownPairCounts'], ensure_ascii=False)}`。成功源配对复用 {c['sourcePairCacheHits']} 次。"
        f"最终导出验证耗时 {c['finalExportElapsedSecondsIncludingQueue']:.1f} 秒，含排队，不含之前的导入和简化。"
        f"产物：[案例目录]({c['artifactFolder']})；早期记录：[initial-export-attempt.json]({c['initialAttempt']['path']})。" for c in cases)
    satellite, catch, gearbox, thruster = cases
    placement = satellite['finalExportPlacement']
    placement_note = (
        f"194 组件整星最终 STEP 已另作逐实例核对，证据哈希与最终下载文件一致："
        f"完成 {placement['geometryComparedCount']} 个组件的世界变换与世界 BRep 范围比较，"
        f"最大世界变换矩阵元素差 {placement['maxWorldMatrixAbsoluteDelta']:.6g}，"
        f"最大世界几何边界差 {placement['maxWorldGeometricBoundsAbsoluteDeltaMm']:.6g} mm，"
        f"面数逐项{'一致' if placement['allComparedFaceCountsMatch'] else '存在差异'}。"
        f"该项位置核对结论为**{'通过' if placement['worldGeometryPlacementVerified'] else '未通过'}**。"
        "比较了原样保留组件与已保存简化候选，范围限于上述位置、范围及面数事实，不能替代拓扑或工程验收。"
        f"可视检查工具旋转原型局部包围盒后的保守最大 Z 为 "
        f"{satellite['finalIndependentInspection']['cadConservativeBoundsMm']['max'][2]:.6f} mm，"
        f"紧致世界 BRep 最大 Z 为 {placement['actualMergedGeometricBoundsMm'][5]:.6f} mm；"
        "两种范围算法不同，不能用外框差异认定零件漂移。"
        "详细证据见 [assembly-final-placement-check.json](validation/assembly-final-placement-check.json)。")
    geometry = gearbox['componentGeometry']
    sizes = ' × '.join(f'{v:g}' for v in geometry['dimensionsMm'])
    inspection = geometry['finalIndependentInspection']
    require(geometry['dimensionsMm'] == inspection['dimensionsMm'], 'Gearbox inspection dimensions differ')
    report = f'''# 第一版开发与验收记录

记录日期：{ui.get('date', generated[:10])}。运行环境：Windows、WSL Ubuntu、Linux Docker，DSH 0.1.1-rc.2，CadQuery 2.8.0。原服务器项目只读，独立代码位于本仓库。

## 验收结论的范围

四个案例的应用流程、最终 HTTP 导出和下载验证完成。**流程完成不等于 STEP 拓扑有效；拓扑有效也不等于工程验收合格。** 下表逐项保留真实判定；`unknown` 表示检查未确定，不能按通过处理。有源拓扑缺陷的文件只作为复核资料，源与输出均无效时仅供复核与修复，不适合作为已验收的下游 CAD / CAE 输入。

## 实际交付

桌面快捷方式：`D:\\Desktop\\卫星几何工作台.lnk`。工作台：<http://127.0.0.1:3081/satellite-geometry/>。独立 Docker 服务：`127.0.0.1:8787`，持久卷：`dsh-satellite-geometry_project-data`。使用 DSH 已配置模型，插件包含界面、{package['stdioMcpToolCount']} 个 MCP 工具和操作 Skill。

## 原项目真实案例

两份整星 STEP 与配套资料来自用户指定的 5090 服务器。减速箱和 Dawn 推进器是其中的真实源原型。来源和 SHA256 见 [cases/README.md](cases/README.md)。正式容器复用了已经保存的导入与简化状态；本次最终验证执行导出、下载、文件哈希比对、STEP 回读和命名实例检查。早期结果保存在各案例的 `initial-export-attempt.json`，没有把早期失败记录覆盖为通过。

| 案例 | 组件数 | 简化 / 保留 | 装配 / 热状态 | 原始真实干涉 | 包络假干涉：初始 → 最终 |
|---|---:|---:|---|---:|---:|
{rows}

两份整星按热分析用途保留接触原形：卫星装配仅简化 **{satellite['simplifiedCount']} / {satellite['componentCount']}** 个组件，CATCH 简化 **{catch['simplifiedCount']} / {catch['componentCount']}** 个。这是有限简化率，不能表述为完成了大幅减面。卫星装配发现的 {satellite['initialEnvelopeFalsePositivePairs']} 对包络新增假干涉经细化或回退后剩余 {satellite['envelopeFalsePositivePairs']} 对，原始 {satellite['sourceCollisionPairs']} 对真实干涉保留并报告。四个案例全部组件在项目记录中的当前位姿字段与原始位姿字段逐一相同，没有提交移动零件来消除干涉的操作；这项记录级核对与导出文件中的世界几何核对分开报告。

{placement_note}

| 案例 | STEP 可读 | 源拓扑（缺陷组件数） | 导出回读拓扑 | 实例 / 原型数 | STEP 字节数 | 用途说明 |
|---|---|---|---|---:|---:|---|
{topology_rows}

完整的 `stepReadable`、`stepReadbackValid`、`sourceTopologyValid`、`invalidSourceComponentIds`、`status`、实例数、原型数与哈希保存在每个案例的 `properties.json`，机器摘要保留相同事实。源缺陷和输出缺陷并未认证为一一对应；不能仅凭“源本来无效”推断导出没有任何新增缺陷。有效输入若导出后新出现无效拓扑，回归测试要求作业失败并禁止发布产物。

两份整星最终 STEP 的独立 CAD 检查均与最终文件哈希绑定，并确认 194 与 33 个叶实例，记录见 [assembly-final-inspection.json](validation/assembly-final-inspection.json) 和 [catch-final-inspection.json](validation/catch-final-inspection.json)。检查器的 shapeCount 指标不等于实体数；本报告不将其当作实体统计。

{details}

有效减速箱源实体有 **{geometry['faceCount']} 面**，最终下载 STEP 含 **{geometry['exportedSolidEntityCount']} 个实体、{geometry['exportedFaceEntityCount']} 个面**，包络尺寸 **{sizes} mm**。最终产物的独立几何检查确认 {inspection['faceCount']} 面及相同尺寸，记录见 [gearbox-final-inspection.json](validation/gearbox-final-inspection.json)，并已核对检查文件的 STEP 哈希与最终下载产物一致。初次产物的独立检查另存于 [gearbox-inspection.json](validation/gearbox-inspection.json)。单组件几何检查不能代替整星装配或热接触验收。

Dawn 推进器源原型包含 {thruster['componentGeometry']['solidCount']} 个实体、{thruster['componentGeometry']['faceCount']} 个面，但源拓扑无效；它被保留为缺陷输入回归，没有把“存在实体”或“所有面属于实体”当作“拓扑有效”。有实体与游离曲面混合的原型也会保持未确定，例如 CATCH 中已有 2 实体、430 面而 6 面不属于实体的记录。复杂相交默认每对 10 秒、每轮 300 秒预算，超时或覆盖不完整的组件保留原形、列为未知，可提高预算后重新检查。

## LLM 资料提取与对话联动

实际使用 DSH 原生模型读取真实 DOCX/XLSX，为 **{native['componentsWithSourcedAttributes']} 个组件写入 {native['sourcedFieldCount']} 个质量/功耗字段**。数值与 Excel 原列逐项一致，引用精确存在于原文；**{native['unmatchedComponentsRemainUnknown']} 个无法唯一匹配的组件保留未知**。材料、固定性与运动约束缺失时不编造。尺寸匹配是记录了误差和出处的推断，不能替代器件身份认证。机器证据见 [native-integration-summary.json](validation/native-integration-summary.json)。

浏览器实测原生聊天与三维并排、实体渲染、树和三维点选联动、固定引用草稿、194 组件全选的真实回执及 DSH 代理 ZIP 下载。新增导出页分别显示有效拓扑与源缺陷警告；成功下载不会被显示为工程验收通过。用户改变选区不会改变已发送引用；引用绑定会话、项目修订和服务地址。详细浏览器断言与截图记录见 [ui-smoke.json](validation/ui-smoke.json)。

最终真实截图：[完整装配的候选 GLB]({ui.get('fullAssemblyCandidateScreenshot', 'validation/ui-smoke.json')})、[工作台]({ui.get('finalScreenshot', 'validation/ui-smoke.json')})、[源缺陷导出提示]({ui.get('exportWarningScreenshot', 'validation/ui-smoke.json')})。

{snapshot_note}

## 回归、打包和持久化

- 后端 **{backend_count} 项**测试通过，数量动态取自 [backend-final-tests.log](validation/backend-final-tests.log)：实例与变换、36 mm² 脚接触、源干涉与包络误报、自动细化与失败回原、受约束移动、字段出处、分组导出、取消、超时与预算、缓存和子进程回收，以及有效输入新出现无效输出时禁止发布。
- 插件 **{plugin_count} 项**测试通过，数量取自 [package-install-summary.json](validation/package-install-summary.json)。最终安装包在干净目录实际安装，Host、预构建界面、独立 profile、{package['stdioMcpToolCount']} 个 MCP 工具、194 组件分页与源缺陷证据读取均验证成功。
- 小型接触案例完成容器 HTTP 导入、简化、导出与回读，脚接触仍为 **36 mm²**。原始验证记录独立保留，没有将其拓扑结果套用到四个真实案例。
- 正式容器冷重启后，{len(persistence['projectsAfter'])} 个项目的版本、组件数、资料数与已有导出 STEP 哈希逐项不变，包含上述四个案例的最终产物。工作台与 DSH 文件代理已重新检查可用。{launcher_note}证据见 [container-persistence-production.json](validation/container-persistence-production.json)。

最终插件包：`dist/lbk-dsh-satellite-geometry-0.1.0.tgz`，{package['bytes']:,} 字节，SHA256：`{package['sha256']}`。报告生成前重新核对了包字节数和哈希与安装证据一致。

## 仍需明确的限制

首版以保守包络、多盒与有限分层细化为主；接触密集、开放曲面、源拓扑缺陷或计算未确定的组件可能完整保留，不能承诺大幅简化率。已有受约束位姿候选验证，尚无通用全局布局优化器。导出不自动修复源拓扑。接触表是几何候选，不是热导通认证；电缆、孔位配合、安装顺序、完整壳体包含性、网格和求解不在验收范围。扫描 PDF 需先 OCR。Docker 实测为当前 Linux x86-64 环境，其他架构需另行构建验证。

完整机器摘要见 [validation/final-summary.json](validation/final-summary.json)。原始模型、完整对话及开发运行数据仅留在本机，不进入插件发布包。
'''
    # Do not publish either report until all evidence gates above have passed.
    (ROOT / 'validation/final-summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (ROOT / 'VALIDATION.md').write_text(report, encoding='utf-8')
    print(json.dumps({'report': str(ROOT / 'VALIDATION.md'), 'caseCount': len(cases), 'backendTestsPassed': backend_count,
                      'pluginTestsPassed': plugin_count, 'exportStatuses': {c['folder']: c['exportStatus'] for c in cases}}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
