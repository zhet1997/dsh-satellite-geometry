import type { Checks, ExportRecord } from './types';

export type AcceptanceStatus = 'passed' | 'needs_review' | 'unknown' | 'failed';

/** A successful job or a source-only pass cannot establish completed acceptance. */
export function acceptanceStatus(checks: Checks | undefined, kind: 'assembly' | 'thermal'): AcceptanceStatus {
  const reported = kind === 'assembly' ? checks?.assemblyStatus : checks?.thermalStatus;
  if (reported === 'failed') return 'failed';
  if (!checks?.sourceComplete || !checks.envelopeComplete || checks.errors?.length || checks.uncertainComponentIds?.length) return 'unknown';
  if (!reported || reported === 'unknown') return 'unknown';
  if (kind === 'assembly' && ((checks.sourceCollisions?.length ?? 0) > 0 || (checks.falsePositivePairs?.length ?? 0) > 0)) return 'needs_review';
  return reported;
}

export type ExportPresentation = { state: 'pending' | 'passed' | 'review' | 'unknown'; title: string; detail: string };

/** Generated files are downloadable even when existing source defects require repair. */
export function exportPresentation(record: ExportRecord | undefined, hasStep: boolean): ExportPresentation {
  if (!hasStep) return { state: 'pending', title: '当前修订尚未导出', detail: '生成导出包后，将显示 STEP 的可读取性与拓扑检查结果。' };
  if (record?.stepReadable === true && record.stepReadbackValid === false) {
    return {
      state: 'review', title: 'STEP 可读取，但拓扑检查未通过',
      detail: record.sourceTopologyValid === false
        ? '源模型本身已有拓扑缺陷，导出保留了源几何。此文件仅供复核与修复，不适合作为已验收的下游 CAD / CAE 输入。'
        : '导出文件仍存在拓扑问题。此文件仅供复核与修复，不适合作为已验收的下游 CAD / CAE 输入。',
    };
  }
  if (record?.stepReadable === true && record.stepReadbackValid === true && record.sourceTopologyValid === false) {
    return {
      state: 'review', title: 'STEP 拓扑检查通过，源模型缺陷仍需复核',
      detail: '导出的 STEP 可读取且回读拓扑有效，但源模型本身已有拓扑缺陷。请复核源缺陷对简化结果的影响；此结果不代表工程验收通过。',
    };
  }
  if (record?.stepReadable === true && record.stepReadbackValid === true && record.sourceTopologyValid === true && (!record.status || record.status === 'valid')) {
    return { state: 'passed', title: 'STEP 可读取，拓扑检查通过', detail: '已重新读取导出的 STEP 并验证拓扑有效性。仍需结合装配与热接触检查，确认具体工程用途。' };
  }
  return { state: 'unknown', title: '导出文件尚未完成有效性确认', detail: '当前缺少完整的 STEP 可读取性、源拓扑或回读拓扑记录。请重新导出并查看检查结果，暂不作为已验收的下游输入。' };
}
