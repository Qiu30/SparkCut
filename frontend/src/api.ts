import type {
  Job,
  JobConfig,
  FeedbackStatus,
  LlmModelsResponse,
  LogsResponse,
  Material,
  PipelineStatus,
  RuntimeSettings,
  RuntimeSettingsUpdate,
  Template,
  TemplateType,
  StorageSummary,
  WorkspaceDetail,
  WorkspaceSummary,
} from './types';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || response.statusText);
  }
  return response.json() as Promise<T>;
}

export const api = {
  listWorkspaces: () => request<WorkspaceSummary[]>('/api/workspaces'),
  createWorkspace: (name: string) =>
    request<WorkspaceSummary>('/api/workspaces', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    }),
  getWorkspace: (id: string) => request<WorkspaceDetail>(`/api/workspaces/${id}`),
  uploadVideo: (workspaceId: string, form: FormData) =>
    request<Material>(`/api/workspaces/${workspaceId}/videos`, {
      method: 'POST',
      body: form,
    }),
  deleteVideo: (workspaceId: string, videoId: string) =>
    request<{ ok: boolean }>(`/api/workspaces/${workspaceId}/videos/${videoId}`, {
      method: 'DELETE',
    }),
  reorderVideos: (workspaceId: string, materialIds: string[]) =>
    request<Material[]>(`/api/workspaces/${workspaceId}/videos/order`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ material_ids: materialIds }),
    }),
  listTemplates: () => request<Template[]>('/api/templates'),
  createTemplate: (name: string, type: TemplateType, config: Partial<JobConfig>) =>
    request<Template>('/api/templates', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, type, config }),
    }),
  deleteTemplate: (id: string) =>
    request<{ ok: boolean }>(`/api/templates/${id}`, { method: 'DELETE' }),
  markTemplateUsed: (id: string) =>
    request<Template>(`/api/templates/${id}/use`, { method: 'POST' }),
  duplicateTemplate: (id: string) =>
    request<Template>(`/api/templates/${id}/duplicate`, { method: 'POST' }),
  setDefaultTemplate: (id: string) =>
    request<Template>(`/api/templates/${id}/default`, { method: 'POST' }),
  getStorageSummary: () => request<StorageSummary>('/api/storage/summary'),
  getPipelineStatus: () => request<PipelineStatus>('/api/pipeline/status'),
  getLlmModels: () => request<LlmModelsResponse>('/api/llm/models'),
  getRuntimeSettings: () => request<RuntimeSettings>('/api/settings/runtime'),
  updateRuntimeSettings: (settings: RuntimeSettingsUpdate) =>
    request<RuntimeSettings>('/api/settings/runtime', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(settings),
    }),
  createJob: (workspaceId: string, config: JobConfig) =>
    request<Job>(`/api/workspaces/${workspaceId}/jobs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config }),
    }),
  getJob: (id: string) => request<Job>(`/api/jobs/${id}`),
  cancelJob: (id: string) => request<Job>(`/api/jobs/${id}/cancel`, { method: 'POST' }),
  retryJob: (id: string) => request<Job>(`/api/jobs/${id}/retry`, { method: 'POST' }),
  duplicateJob: (id: string) =>
    request<{ job: Job }>(`/api/jobs/${id}/duplicate`, { method: 'POST' }),
  getLogs: (id: string, offset: number) =>
    request<LogsResponse>(`/api/jobs/${id}/logs?offset=${offset}`),
  submitOutputFeedback: (jobId: string, outputId: string, status: FeedbackStatus, reason: string) =>
    request<Job>(`/api/jobs/${jobId}/outputs/${outputId}/feedback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status, reason }),
    }),
  refineOutput: (jobId: string, outputId: string, action: 'adjust' | 'regenerate', feedback: string) =>
    request<Job>(`/api/jobs/${jobId}/outputs/${outputId}/refine`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, feedback }),
    }),
};
