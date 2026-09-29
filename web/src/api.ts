import type { ComponentMetadata, Job, Project, ProjectDocument, ProjectSummary, Strategy } from './types';

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

export function createClient(apiBase: string) {
  const base = apiBase.replace(/\/$/, '');
  async function request<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(`${base}${path}`, { signal: AbortSignal.timeout(30_000), ...init, cache: 'no-store' });
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      const message = typeof body?.detail === 'string' ? body.detail
        : typeof body?.error === 'string' ? body.error
        : typeof body?.message === 'string' ? body.message
        : `请求失败（${response.status}）`;
      throw new ApiError(message, response.status);
    }
    return response.json() as Promise<T>;
  }
  const post = <T>(path: string, body: unknown) => request<T>(path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  const projectPath = (id: string) => `/projects/${encodeURIComponent(id)}`;
  const upload = <T>(path: string, file: File, onProgress?: (value: number) => void) => new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${base}${path}`);
    xhr.upload.onprogress = (event) => { if (event.lengthComputable) onProgress?.(event.loaded / event.total * 100); };
    xhr.onerror = () => reject(new Error('文件上传失败，请检查服务连接'));
    xhr.onload = () => {
      let body: Record<string, unknown>;
      try { body = JSON.parse(xhr.responseText); } catch { reject(new Error('服务返回了无法读取的结果')); return; }
      if (xhr.status < 200 || xhr.status >= 300) reject(new ApiError(String(body.detail ?? body.error ?? '文件上传失败'), xhr.status));
      else resolve(body as T);
    };
    const form = new FormData(); form.append('file', file); xhr.send(form);
  });
  return {
    list: async () => {
      const result = await request<ProjectSummary[] | { projects: ProjectSummary[] }>('/projects');
      return Array.isArray(result) ? result : result.projects ?? [];
    },
    create: (name: string) => post<Project>('/projects', { name }),
    get: (id: string) => request<Project>(projectPath(id)),
    uploadStep: (id: string, file: File, onProgress?: (value: number) => void) => upload<{ jobId: string }>(`${projectPath(id)}/import`, file, onProgress),
    uploadDocument: (id: string, file: File) => upload<unknown>(`${projectPath(id)}/documents`, file),
    document: (id: string, documentId: string) => request<ProjectDocument>(`${projectPath(id)}/documents/${encodeURIComponent(documentId)}`),
    simplify: (id: string, revision: number, options: { componentIds?: string[]; strategy: Exclude<Strategy, 'original'>; purpose: string; preserveContacts: boolean; contactToleranceMm: number }) => post<{ jobId: string }>(`${projectPath(id)}/simplify`, { revision, ...options }),
    check: (id: string, revision: number) => post<{ jobId: string }>(`${projectPath(id)}/check`, { revision }),
    export: (id: string, revision: number) => post<{ jobId: string }>(`${projectPath(id)}/export`, { revision }),
    restore: (id: string, cid: string, revision: number) => post<{ jobId: string }>(`${projectPath(id)}/components/${encodeURIComponent(cid)}/restore`, { revision, restoreGeometry: true, restorePose: true }),
    metadata: (id: string, revision: number, components: Array<{
      id: string; origin: 'manual' | 'document'; changedFields: string[];
    } & Partial<Record<keyof ComponentMetadata, string | number | boolean | null>>>) => post<Project>(`${projectPath(id)}/metadata`, { revision, components }),
    semantics: (id: string, revision: number, operation: { action: 'rename' | 'group' | 'ungroup'; componentIds?: string[]; groupId?: string; name?: string; reason: string }) => post<Project>(`${projectPath(id)}/semantics`, { revision, operations: [operation] }),
    job: (id: string) => request<Job>(`/jobs/${encodeURIComponent(id)}`),
    cancelJob: (id: string) => post<Job>(`/jobs/${encodeURIComponent(id)}/cancel`, {}),
    artifactUrl: (path?: string) => {
      if (!path) return undefined;
      if (/^https?:\/\//.test(path)) return path;
      if (path.startsWith('/api/')) return `${base}${path.slice(4)}`;
      return path.startsWith('/') ? `${new URL(base, window.location.href).origin}${path}` : `${base}/${path}`;
    },
  };
}
export type CadClient = ReturnType<typeof createClient>;
