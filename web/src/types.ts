export type Strategy = 'original' | 'conservative' | 'box' | 'multibox';
export type Purpose = 'thermal' | 'assembly' | 'envelope' | 'detail';
export type Vec3 = [number, number, number];
export type ComponentMetadata = {
  massKg?: number; powerW?: number; fixed?: boolean; thermalCritical?: boolean;
  material?: string; notes?: string;
};
export type CadComponent = {
  id: string; name: string; parentId?: string | null;
  sourceNodeIds?: string[]; prototypeId?: string;
  boundsMm?: number[]; dimensionsMm?: number[]; centerMm?: number[];
  pose?: { rotation: number[][]; translationMm: number[] };
  strategy: Strategy; preserved: boolean; preservationReason?: string;
  volumeMm3?: number; simplifiedVolumeMm3?: number; faceCount?: number;
  metadata: ComponentMetadata;
};
export type TreeNode = {
  id: string; name: string; parentId: string | null; children: string[];
  isLeaf: boolean; componentId?: string;
  semanticGroup?: boolean;
};
export type CheckIssue = string | {
  id?: string; message?: string; description?: string; reason?: string;
  componentIds?: string[]; components?: string[]; pair?: string[];
  a?: string; b?: string; componentA?: string; componentB?: string;
  [key: string]: unknown;
};
export type Checks = {
  sourceCollisions?: CheckIssue[]; envelopeCollisions?: CheckIssue[];
  falsePositivePairs?: CheckIssue[]; contacts?: CheckIssue[]; warnings?: CheckIssue[];
  sourceComplete?: boolean; envelopeComplete?: boolean;
  thermalStatus?: 'passed' | 'needs_review' | 'unknown' | 'failed';
  assemblyStatus?: 'passed' | 'needs_review' | 'unknown' | 'failed';
  errors?: CheckIssue[]; uncertainComponentIds?: string[];
};
export type ProjectDocument = { id: string; name: string; path?: string; size?: number; extractionStatus?: string; warnings?: string[]; text?: string };
export type ExportRecord = {
  stepReadable?: boolean; stepReadbackValid?: boolean; sourceTopologyValid?: boolean;
  status?: 'valid' | 'source_and_output_invalid_review_required' | 'source_defects_review_required';
  invalidSourceComponentIds?: string[]; warnings?: string[];
};
export type Project = {
  id: string; name: string; revision: number; status: string;
  units?: string; coordinateSystem?: { source: string; glb: string };
  tree: TreeNode[]; components: CadComponent[];
  artifacts: { originalGlb?: string; simplifiedGlb?: string; step?: string; report?: string; [key: string]: string | undefined };
  checks: Checks; activeJobId?: string;
  lastExport?: ExportRecord;
  documents?: ProjectDocument[];
  notes?: string; createdAt?: string; updatedAt?: string;
};
export type ProjectSummary = Pick<Project, 'id' | 'name' | 'revision' | 'status'>;
export type Job = {
  id?: string; jobId: string; projectId: string; kind: string;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  progress: number; message: string; result?: unknown; error?: string;
};
export type HostContext = { projectId?: string; revision?: number; apiBase?: string; theme?: string };
