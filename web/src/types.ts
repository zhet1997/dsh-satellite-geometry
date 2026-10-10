export type Strategy = 'original' | 'conservative' | 'box' | 'multibox' | 'recipe';
export type RecipePart = { id: string; name: string; kind: 'box' | 'cylinder' | 'source'; centerMm: number[]; sizeMm?: number[] | null; radiusMm?: number | null; heightMm?: number | null; axis?: number[] };
export type Thermal = { thicknessMm?: number | null; material?: string | null; massKg?: number | null; specificHeatJPerKgK?: number | null; conductivityWPerMK?: number | null; powerW?: number | null };
export type RecipeRegion = { id: string; name: string; partId: string; selector: 'xmin' | 'xmax' | 'ymin' | 'ymax' | 'zmin' | 'zmax' | 'lateral' | 'all' };
export type Recipe = { schemaVersion: 1; representation: 'source' | 'solid' | 'surface_shell'; parts: RecipePart[]; thermal: Thermal; regions: RecipeRegion[]; dimensionBasis: string; notes: string; legacyCandidateFile?: string | null; sources?: unknown[] };
export type RegionFace = { id: string; centerMm: number[]; normal?: number[] | null; boundsMm: number[]; verticesMm: number[][]; triangles: number[][]; areaMm2: number; geometryType: string };
export type InstallationRegion = RecipeRegion & { mappingStatus: string; faces: RegionFace[]; recipeFingerprint: string };
export type ThermalContact = { id: string; a: { componentId: string; regionId: string | null }; b: { componentId: string; regionId: string | null }; status: 'candidate' | 'confirmed' | 'needs_review' | 'excluded'; origin: 'manual' | 'document' | 'geometry'; areaMm2: number | null; conductanceWPerK: number | null; evidence: string; mappingStatus?: string; patches?: RegionFace[]; unknownFields?: string[]; sources?: unknown[] };
export type WorkflowBinding = { sessionId: string; projectId: string; skillId: string; skillFingerprint: string; boundAt: string; loadedAt: string | null };
export type SkillVersion = { id: string; label: string; fingerprint: string; content?: string; resources?: Record<string, string>; createdAt: string; immutable: boolean };
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
  sourceName?: string; displayName?: string; engineeringGroup?: string; nameStatus?: string; localBoundsMm?: number[];
  identityEvidence?: { basis: string; sources?: unknown[] };
  recipe?: Recipe; recipeFingerprint?: string;
  recipeCopies?: { id: string; name: string; at: string; fingerprint: string }[];
  installationRegions?: InstallationRegion[];
  outputGeometry?: { representation: string; valid: boolean; passed: boolean; faceCount: number; solidCount: number; areaMm2: number; volumeMm3: number };
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
  thermalContacts?: ThermalContact[]; contactDiscovery?: { status: string };
  workflowBindings?: Record<string, WorkflowBinding>;
};
export type ProjectSummary = Pick<Project, 'id' | 'name' | 'revision' | 'status'>;
export type Job = {
  id?: string; jobId: string; projectId: string; kind: string;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  progress: number; message: string; result?: unknown; error?: string;
};
export type HostContext = { projectId?: string; revision?: number; apiBase?: string; theme?: string };
