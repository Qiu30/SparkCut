import {
  ArrowLeft,
  Ban,
  CheckCircle2,
  Copy,
  Download,
  FileVideo,
  HardDrive,
  ListRestart,
  MessageSquare,
  Plus,
  RotateCcw,
  Save,
  Settings,
  Star,
  Trash2,
  Upload,
  Wrench,
  XCircle,
} from 'lucide-react';
import { ChangeEvent, DragEvent, MouseEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from './api';
import type { FeedbackStatus, Job, JobConfig, JobStatus, Material, PipelineStatus, RuntimeSettings, Template, TemplateType, WorkspaceDetail, WorkspaceSummary } from './types';

const FALLBACK_LLM_MODEL = 'GLM-5.1';

const defaultConfig: JobConfig = {
  contentType: '高光',
  durationRange: '30 秒',
  outputCount: 1,
  pace: '强反转',
  targetPlatform: '通用',
  aspectRatio: '9:16',
  keepSuspense: true,
  clipRule: '前5秒必须有冲突或反转，成片30秒，结尾保留悬念。',
  reviewRule: '',
  clipModel: FALLBACK_LLM_MODEL,
  reviewModel: FALLBACK_LLM_MODEL,
  whisperModel: 'base',
  dramaName: '',
  fontColor: '#ffff00',
  cornerEnabled: true,
  endingEnabled: true,
};

function normalizeModel(value: string | undefined, models: string[], fallback: string, replaceBuiltInFallback = false): string {
  const trimmed = value?.trim();
  if (replaceBuiltInFallback && trimmed === FALLBACK_LLM_MODEL && models.length > 0 && !models.includes(trimmed)) {
    return models[0];
  }
  if (trimmed) return trimmed;
  return models[0] || fallback;
}

function normalizeConfigModels(
  config: JobConfig,
  models: string[],
  fallback: string,
  replaceBuiltInFallback = false,
): JobConfig {
  return {
    ...config,
    clipModel: normalizeModel(config.clipModel, models, fallback, replaceBuiltInFallback),
    reviewModel: normalizeModel(config.reviewModel, models, fallback, replaceBuiltInFallback),
  };
}

function configFromJob(job: Job, models: string[], fallback: string): JobConfig | null {
  const snapshotConfig = isRecord(job.input_snapshot.config) ? job.input_snapshot.config : null;
  if (!snapshotConfig) return null;
  return normalizeConfigModels({ ...defaultConfig, ...snapshotConfig } as JobConfig, models, fallback);
}

const statusLabels: Record<JobStatus, string> = {
  queued: '排队中',
  running: '执行中',
  cancelled: '已取消',
  done: '已完成',
  error: '失败',
};

const stageLabels: Record<string, string> = {
  queued: '排队',
  probe: '素材探查',
  asr: 'ASR 转写',
  analysis: '剧情分析',
  review: '审查过滤',
  compose: '视频合成',
  package: '视频包装',
  done: '完成',
  cancelled: '已取消',
};

const terminalStatuses = new Set<JobStatus>(['done', 'error', 'cancelled']);

const feedbackLabels: Record<FeedbackStatus, string> = {
  usable: '可用',
  needs_edit: '需修改',
  rejected: '不可用',
};

const asrStatusLabels: Record<string, string> = {
  pending: 'ASR 待处理',
  running: 'ASR 转写中',
  done: 'ASR 已转写',
  error: 'ASR 失败',
  not_started: 'ASR 未转写',
};

const evidenceLabels: Record<string, string> = {
  asr: 'ASR 证据',
  metadata: '元信息推断',
  model_fallback: '模型兜底',
};

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function fmtDate(value: string): string {
  return new Date(value).toLocaleString('zh-CN');
}

function statusClass(status?: string | null): string {
  return `status ${status || 'none'}`;
}

function fmtSeconds(value?: number | null): string {
  if (!value) return '0s';
  return value >= 60 ? `${Math.floor(value / 60)}m ${(value % 60).toFixed(0)}s` : `${value.toFixed(1)}s`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value));
}

function textValue(value: unknown, fallback = ''): string {
  return typeof value === 'string' && value.trim() ? value : fallback;
}

function numberValue(value: unknown, fallback = 0): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function pipelineHint(status: PipelineStatus | null): { tone: 'error' | 'warning'; text: string } | null {
  if (!status) return null;
  const blockingRequirements = Array.isArray(status.blocking_requirements) ? status.blocking_requirements : [];
  const warnings = Array.isArray(status.warnings) ? status.warnings : [];
  if (blockingRequirements.length > 0) {
    return {
      tone: 'error',
      text: `开始任务前需要补齐配置：${blockingRequirements.join(' ')}`,
    };
  }
  if (warnings.length > 0) {
    return {
      tone: 'warning',
      text: `当前项目可以启动，但任务会降级：${warnings.join(' ')}`,
    };
  }
  return null;
}

async function readVideoMetadata(file: File): Promise<{
  duration?: number;
  width?: number;
  height?: number;
  probeStatus: string;
}> {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file);
    const video = document.createElement('video');
    const finish = (value: { duration?: number; width?: number; height?: number; probeStatus: string }) => {
      URL.revokeObjectURL(url);
      resolve(value);
    };
    const timer = window.setTimeout(() => finish({ probeStatus: 'unknown' }), 2500);
    video.preload = 'metadata';
    video.onloadedmetadata = () => {
      window.clearTimeout(timer);
      finish({
        duration: Number.isFinite(video.duration) ? video.duration : undefined,
        width: video.videoWidth || undefined,
        height: video.videoHeight || undefined,
        probeStatus: 'browser',
      });
    };
    video.onerror = () => {
      window.clearTimeout(timer);
      finish({ probeStatus: 'unreadable' });
    };
    video.src = url;
  });
}

function App() {
  const [workspaces, setWorkspaces] = useState<WorkspaceSummary[]>([]);
  const [workspace, setWorkspace] = useState<WorkspaceDetail | null>(null);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [storageSummary, setStorageSummary] = useState<string>('0 B');
  const [pipelineStatus, setPipelineStatus] = useState<PipelineStatus | null>(null);
  const [llmModels, setLlmModels] = useState<string[]>([FALLBACK_LLM_MODEL]);
  const [defaultLlmModel, setDefaultLlmModel] = useState(FALLBACK_LLM_MODEL);
  const [config, setConfig] = useState<JobConfig>(defaultConfig);
  const [activeTemplateByType, setActiveTemplateByType] = useState<Record<TemplateType, string | null>>({ clip: null, review: null });
  const [dirtyTemplateByType, setDirtyTemplateByType] = useState<Record<TemplateType, boolean>>({ clip: false, review: false });
  const [selectedJob, setSelectedJob] = useState<Job | null>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draggingMaterial, setDraggingMaterial] = useState<string | null>(null);
  const [workspaceDraft, setWorkspaceDraft] = useState('');
  const [workspaceModalOpen, setWorkspaceModalOpen] = useState(false);
  const [refineState, setRefineState] = useState<{ outputId: string; action: 'adjust' | 'regenerate'; feedback: string } | null>(null);
  const [refineLoading, setRefineLoading] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsDraft, setSettingsDraft] = useState<RuntimeSettings | null>(null);
  const [settingsApiKey, setSettingsApiKey] = useState('');
  const [settingsSaving, setSettingsSaving] = useState(false);
  const logOffsetRef = useRef(0);

  const loadWorkspaces = useCallback(async () => {
    setWorkspaces(await api.listWorkspaces());
  }, []);

  const loadTemplates = useCallback(async () => {
    setTemplates(await api.listTemplates());
  }, []);

  const loadStorageSummary = useCallback(async () => {
    const summary = await api.getStorageSummary();
    setStorageSummary(fmtSize(summary.storage_bytes));
  }, []);

  const loadPipelineStatus = useCallback(async () => {
    setPipelineStatus(await api.getPipelineStatus());
  }, []);

  const loadLlmModels = useCallback(async () => {
    try {
      const response = await api.getLlmModels();
      const models = response.models;
      const defaultModel = response.default_model || models[0] || FALLBACK_LLM_MODEL;
      setLlmModels(models);
      setDefaultLlmModel(defaultModel);
      setConfig((current) => normalizeConfigModels(current, models, defaultModel, true));
    } catch {
      setLlmModels([]);
      setDefaultLlmModel(FALLBACK_LLM_MODEL);
      setConfig((current) => normalizeConfigModels(current, [], FALLBACK_LLM_MODEL));
    }
  }, []);

  const openWorkspace = useCallback(async (id: string) => {
    const detail = await api.getWorkspace(id);
    setWorkspace(detail);
    setSelectedJob(null);
    setLogs([]);
    logOffsetRef.current = 0;
  }, []);

  const refreshWorkspace = useCallback(async () => {
    if (!workspace) return;
    setWorkspace(await api.getWorkspace(workspace.id));
    setWorkspaces(await api.listWorkspaces());
  }, [workspace]);

  const loadLogs = useCallback(async (jobId: string, reset = false) => {
    const offset = reset ? 0 : logOffsetRef.current;
    const response = await api.getLogs(jobId, offset);
    logOffsetRef.current = response.next_offset;
    setLogs((current) => (reset ? response.lines : [...current, ...response.lines]));
  }, []);

  const selectJob = useCallback(
    async (jobId: string) => {
      const job = await api.getJob(jobId);
      setSelectedJob(job);
      setLogs([]);
      logOffsetRef.current = 0;
      await loadLogs(job.id, true);
    },
    [loadLogs],
  );

  useEffect(() => {
    if (!workspace || selectedJob || workspace.jobs.length === 0) return;
    selectJob(workspace.jobs[0].id).catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, [selectJob, selectedJob, workspace]);

  const currentPipelineHint = pipelineHint(pipelineStatus);

  useEffect(() => {
    loadWorkspaces().catch((err) => setError(err.message));
    loadTemplates().catch((err) => setError(err.message));
    loadStorageSummary().catch((err) => setError(err.message));
    loadPipelineStatus().catch((err) => setError(err.message));
    loadLlmModels();
  }, [loadLlmModels, loadPipelineStatus, loadStorageSummary, loadTemplates, loadWorkspaces]);

  useEffect(() => {
    if (!selectedJob || terminalStatuses.has(selectedJob.status)) return;
    const timer = window.setInterval(async () => {
      try {
        const job = await api.getJob(selectedJob.id);
        setSelectedJob(job);
        await loadLogs(job.id);
        await loadPipelineStatus();
        if (job.status === 'done' || job.status === 'error' || job.status === 'cancelled') {
          await refreshWorkspace();
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    }, 1400);
    return () => window.clearInterval(timer);
  }, [loadLogs, loadPipelineStatus, refreshWorkspace, selectedJob]);

  const clipTemplates = useMemo(() => templates.filter((template) => template.type === 'clip'), [templates]);
  const reviewTemplates = useMemo(() => templates.filter((template) => template.type === 'review'), [templates]);
  const llmModelOptions = useMemo(() => llmModels, [llmModels]);
  const runtimeModelOptions = useMemo(() => settingsDraft?.llm_models || [], [settingsDraft]);

  function markTemplateDirty(type: TemplateType | TemplateType[]) {
    const types = Array.isArray(type) ? type : [type];
    setDirtyTemplateByType((current) => {
      const next = { ...current };
      let changed = false;
      types.forEach((item) => {
        if (activeTemplateByType[item] && !next[item]) {
          next[item] = true;
          changed = true;
        }
      });
      return changed ? next : current;
    });
  }

  function updateConfig(patch: Partial<JobConfig>, dirtyType?: TemplateType | TemplateType[]) {
    setConfig((current) => ({ ...current, ...patch }));
    if (dirtyType) markTemplateDirty(dirtyType);
  }

  function openWorkspaceModal() {
    setWorkspaceDraft('');
    setWorkspaceModalOpen(true);
  }

  function closeWorkspaceModal() {
    if (busy) return;
    setWorkspaceModalOpen(false);
    setWorkspaceDraft('');
  }

  async function openSettings() {
    setSettingsOpen(true);
    setSettingsApiKey('');
    try {
      setSettingsDraft(await api.getRuntimeSettings());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  function closeSettings() {
    if (settingsSaving) return;
    setSettingsOpen(false);
    setSettingsDraft(null);
    setSettingsApiKey('');
  }

  async function saveSettings() {
    if (!settingsDraft) return;
    setSettingsSaving(true);
    try {
      const saved = await api.updateRuntimeSettings({
        pipeline_mode: settingsDraft.pipeline_mode,
        llm_endpoint: settingsDraft.llm_endpoint,
        llm_api_key: settingsApiKey,
        llm_model: settingsDraft.llm_model,
        default_whisper_model: settingsDraft.default_whisper_model,
        asr_clip_seconds: settingsDraft.asr_clip_seconds,
      });
      setSettingsDraft(saved);
      setSettingsApiKey('');
      await loadPipelineStatus();
      await loadLlmModels();
      setSettingsOpen(false);
      setSettingsDraft(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSettingsSaving(false);
    }
  }

  async function createWorkspace() {
    const name = workspaceDraft.trim();
    if (!name) return;
    setBusy(true);
    try {
      const created = await api.createWorkspace(name);
      await loadWorkspaces();
      closeWorkspaceModal();
      await openWorkspace(created.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function processUploadFiles(files: File[]) {
    if (!workspace || files.length === 0) return;
    setUploading(true);
    setError(null);
    try {
      for (const file of files) {
        const metadata = await readVideoMetadata(file);
        const form = new FormData();
        form.append('file', file);
        if (metadata.duration) form.append('duration', String(metadata.duration));
        if (metadata.width) form.append('width', String(metadata.width));
        if (metadata.height) form.append('height', String(metadata.height));
        form.append('probe_status', metadata.probeStatus);
        form.append('audio_status', 'unknown');
        await api.uploadVideo(workspace.id, form);
      }
      await refreshWorkspace();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setUploading(false);
    }
  }

  async function uploadFiles(event: ChangeEvent<HTMLInputElement>) {
    if (!event.target.files?.length) return;
    await processUploadFiles(Array.from(event.target.files));
    event.target.value = '';
  }

  async function dropUploadFiles(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    if (!event.dataTransfer.files?.length) return;
    await processUploadFiles(Array.from(event.dataTransfer.files));
  }

  async function deleteMaterial(material: Material) {
    if (!workspace || !window.confirm(`删除 ${material.filename}？`)) return;
    await api.deleteVideo(workspace.id, material.id);
    await refreshWorkspace();
  }

  async function dropMaterial(targetId: string) {
    if (!workspace || !draggingMaterial || draggingMaterial === targetId) return;
    const ids = workspace.materials.map((item) => item.id);
    const from = ids.indexOf(draggingMaterial);
    const to = ids.indexOf(targetId);
    if (from < 0 || to < 0) return;
    ids.splice(from, 1);
    ids.splice(to, 0, draggingMaterial);
    await api.reorderVideos(workspace.id, ids);
    setDraggingMaterial(null);
    await refreshWorkspace();
  }

  async function applyTemplate(template: Template) {
      setConfig((current) => normalizeConfigModels({ ...current, ...template.config }, llmModelOptions, defaultLlmModel, true));
    setActiveTemplateByType((current) => ({ ...current, [template.type]: template.id }));
    setDirtyTemplateByType((current) => ({ ...current, [template.type]: false }));
    await api.markTemplateUsed(template.id);
  }

  async function saveTemplate(type: TemplateType) {
    const name = window.prompt(type === 'clip' ? '剪辑模板名称' : '审查模板名称');
    if (!name?.trim()) return;
    const payload =
      type === 'clip'
        ? config
        : {
            reviewRule: config.reviewRule,
            reviewModel: config.reviewModel,
          };
    const created = await api.createTemplate(name.trim(), type, payload);
    setActiveTemplateByType((current) => ({ ...current, [type]: created.id }));
    setDirtyTemplateByType((current) => ({ ...current, [type]: false }));
    await loadTemplates();
  }

  async function deleteTemplate(template: Template, event: MouseEvent) {
    event.stopPropagation();
    if (!window.confirm(`删除模板 ${template.name}？`)) return;
    await api.deleteTemplate(template.id);
    if (activeTemplateByType[template.type] === template.id) {
      setActiveTemplateByType((current) => ({ ...current, [template.type]: null }));
      setDirtyTemplateByType((current) => ({ ...current, [template.type]: false }));
    }
    await loadTemplates();
  }

  async function duplicateTemplate(template: Template, event: MouseEvent) {
    event.stopPropagation();
    await api.duplicateTemplate(template.id);
    await loadTemplates();
  }

  async function setDefaultTemplate(template: Template, event: MouseEvent) {
    event.stopPropagation();
    await api.setDefaultTemplate(template.id);
    await loadTemplates();
  }

  async function submitJob() {
    if (!workspace) return;
    const blockingRequirements = Array.isArray(pipelineStatus?.blocking_requirements) ? pipelineStatus.blocking_requirements : [];
    const warnings = Array.isArray(pipelineStatus?.warnings) ? pipelineStatus.warnings : [];
    if (blockingRequirements.length) {
      setError(`开始任务前请先补齐必要配置：${blockingRequirements.join(' ')}`);
      return;
    }
    setBusy(true);
    setError(warnings.length ? `当前任务会降级运行：${warnings.join(' ')}` : null);
    try {
      const jobConfig = normalizeConfigModels(config, llmModelOptions, defaultLlmModel);
      setConfig(jobConfig);
      const job = await api.createJob(workspace.id, jobConfig);
      setSelectedJob(job);
      setLogs([]);
      logOffsetRef.current = 0;
      await loadLogs(job.id, true);
      await loadPipelineStatus();
      await refreshWorkspace();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function cancelJob() {
    if (!selectedJob) return;
    const job = await api.cancelJob(selectedJob.id);
    setSelectedJob(job);
    await loadLogs(job.id);
    await loadPipelineStatus();
    await refreshWorkspace();
  }

  async function retryJob() {
    if (!selectedJob) return;
    const job = await api.retryJob(selectedJob.id);
    setSelectedJob(job);
    setLogs([]);
    logOffsetRef.current = 0;
    await loadLogs(job.id, true);
    await loadPipelineStatus();
    await refreshWorkspace();
  }

  async function duplicateJob() {
    if (!selectedJob) return;
    const result = await api.duplicateJob(selectedJob.id);
    setSelectedJob(result.job);
    setLogs([]);
    logOffsetRef.current = 0;
    await loadLogs(result.job.id, true);
    await loadPipelineStatus();
    await refreshWorkspace();
  }

  async function submitOutputFeedback(outputId: string, status: FeedbackStatus) {
    if (!selectedJob) return;
    if (status === 'usable') {
      try {
        const job = await api.submitOutputFeedback(selectedJob.id, outputId, 'usable', '结果可直接使用');
        setSelectedJob(job);
        await loadLogs(job.id);
        await refreshWorkspace();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
      return;
    }
    setRefineState({ outputId, action: status === 'needs_edit' ? 'adjust' : 'regenerate', feedback: '' });
  }

  async function submitRefine() {
    if (!selectedJob || !refineState) return;
    const { outputId, action, feedback } = refineState;
    if (!feedback.trim()) return;
    setRefineLoading(true);
    try {
      await api.submitOutputFeedback(selectedJob.id, outputId, action === 'adjust' ? 'needs_edit' : 'rejected', feedback);
      const newJob = await api.refineOutput(selectedJob.id, outputId, action, feedback);
      setRefineState(null);
      setSelectedJob(newJob);
      const refinedConfig = configFromJob(newJob, llmModelOptions, defaultLlmModel);
      if (refinedConfig) setConfig(refinedConfig);
      logOffsetRef.current = 0;
      await loadLogs(newJob.id, true);
      await refreshWorkspace();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRefineLoading(false);
    }
  }

  const settingsModal = settingsOpen && (
    <div className="modal-backdrop" onClick={closeSettings}>
      <div className="modal-card settings-card" onClick={(event) => event.stopPropagation()}>
        <div className="modal-head">
          <h2>运行设置</h2>
          <button className="ghost icon-button" onClick={closeSettings} disabled={settingsSaving} title="关闭">
            <XCircle size={16} />
          </button>
        </div>
        {!settingsDraft ? (
          <div className="inline-empty">正在读取设置…</div>
        ) : (
          <>
            <div className="settings-stack">
              <section className="settings-section first">
                <div className="settings-section-title">基础运行</div>
                <div className="form-grid two compact">
                  <SelectField
                    label="Pipeline 模式"
                    value={settingsDraft.pipeline_mode}
                    options={['auto', 'real', 'mock']}
                    onChange={(pipeline_mode) => setSettingsDraft({ ...settingsDraft, pipeline_mode })}
                  />
                  <SelectField
                    label="默认 Whisper 模型"
                    value={settingsDraft.default_whisper_model}
                    options={['tiny', 'base', 'small', 'medium', 'large', 'large-v2', 'large-v3']}
                    onChange={(default_whisper_model) => setSettingsDraft({ ...settingsDraft, default_whisper_model })}
                  />
                </div>
              </section>

              <section className="settings-section">
                <div className="settings-section-title">LLM 服务</div>
                <ModelField
                  label="默认 LLM 模型"
                  value={settingsDraft.llm_model}
                  options={runtimeModelOptions}
                  onChange={(llm_model) => setSettingsDraft({ ...settingsDraft, llm_model })}
                />
                <label className="field">
                  <span>接口地址</span>
                  <input
                    value={settingsDraft.llm_endpoint}
                    placeholder="https://example.com 或 https://example.com/v1"
                    onChange={(event) => setSettingsDraft({ ...settingsDraft, llm_endpoint: event.target.value })}
                  />
                  <small className="field-hint">默认自动补 /v1/chat/completions；以 / 结尾不补 /v1；以 # 结尾强制使用原地址。</small>
                </label>
                <label className="field">
                  <span>API Key</span>
                  <input
                    type="password"
                    value={settingsApiKey}
                    placeholder={settingsDraft.llm_api_key_set ? `已设置 ${settingsDraft.llm_api_key_preview}，留空不修改` : '请输入 API Key'}
                    onChange={(event) => setSettingsApiKey(event.target.value)}
                  />
                </label>
              </section>

              <section className="settings-section">
                <div className="settings-section-title">ASR 转写</div>
                <label className="field">
                  <span>截取秒数</span>
                  <input
                    type="number"
                    min={0}
                    value={settingsDraft.asr_clip_seconds}
                    onChange={(event) => setSettingsDraft({ ...settingsDraft, asr_clip_seconds: Number(event.target.value) })}
                  />
                  <small className="field-hint">填 0 表示转写完整视频。保存后新任务会立即使用新配置。</small>
                </label>
              </section>
            </div>
            <div className="modal-actions">
              <button className="secondary" onClick={closeSettings} disabled={settingsSaving}>取消</button>
              <button className="primary" onClick={() => void saveSettings()} disabled={settingsSaving}>
                <Save size={16} /> {settingsSaving ? '保存中…' : '保存设置'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );

  if (!workspace) {
    return (
      <main className="app-shell">
      <header className="topbar">
        <h1>SparkCut</h1>
        <div className="topbar-actions">
          <span className="storage-pill"><HardDrive size={14} /> 存储 {storageSummary}</span>
          <button className="ghost icon-button" onClick={() => void openSettings()} title="运行设置">
            <Settings size={16} />
          </button>
        </div>
      </header>
        <section className="workspace-list">
          <div className="section-heading">
            <h2>工作空间</h2>
            <button className="primary" onClick={openWorkspaceModal} disabled={busy}>
              <Plus size={16} /> 新建工作空间
            </button>
          </div>
          {error && <div className="error-banner">{error}</div>}
          {currentPipelineHint && <div className={`notice-banner ${currentPipelineHint.tone}`}>{currentPipelineHint.text}</div>}
          {workspaces.length === 0 ? (
            <div className="empty-state">
              <p>暂无工作空间</p>
              <button className="primary" onClick={openWorkspaceModal}>
                <Plus size={16} /> 新建工作空间
              </button>
            </div>
          ) : (
            <div className="workspace-cards">
              {workspaces.map((item) => (
                <button className="workspace-card" key={item.id} onClick={() => openWorkspace(item.id)}>
                  <span className="workspace-name">{item.name}</span>
                  <span className="workspace-meta">
                    {item.material_count} 个素材 · {item.job_count} 个任务 · 更新于 {fmtDate(item.updated_at)}
                  </span>
                  {item.latest_job_status && (
                    <span className={statusClass(item.latest_job_status)}>{statusLabels[item.latest_job_status]}</span>
                  )}
                </button>
              ))}
            </div>
          )}
        </section>
        {workspaceModalOpen && (
          <div className="modal-backdrop" onClick={closeWorkspaceModal}>
            <div className="modal-card" onClick={(event) => event.stopPropagation()}>
              <div className="modal-head">
                <h2>新建工作空间</h2>
                <button className="ghost icon-button" onClick={closeWorkspaceModal} disabled={busy} title="关闭">
                  <XCircle size={16} />
                </button>
              </div>
              <label className="field">
                <span>工作空间名称</span>
                <input
                  autoFocus
                  value={workspaceDraft}
                  placeholder="例如：AI Agent 混剪测试"
                  onChange={(event) => setWorkspaceDraft(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' && workspaceDraft.trim()) {
                      void createWorkspace();
                    }
                  }}
                />
              </label>
              <div className="modal-actions">
                <button className="secondary" onClick={closeWorkspaceModal} disabled={busy}>取消</button>
                <button className="primary" onClick={() => void createWorkspace()} disabled={busy || !workspaceDraft.trim()}>
                  <Plus size={16} /> 创建
                </button>
              </div>
            </div>
          </div>
        )}
        {settingsModal}
      </main>
    );
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <h1>SparkCut</h1>
        <div className="topbar-actions">
          <span className="workspace-title">{workspace.name}</span>
          <button className="ghost icon-button" onClick={() => void openSettings()} title="运行设置">
            <Settings size={16} />
          </button>
          <button className="ghost" onClick={() => setWorkspace(null)}>
            <ArrowLeft size={16} /> 工作空间列表
          </button>
        </div>
      </header>
      <div className="workbench">
        <aside className="left-panel">
          {error && <div className="error-banner">{error}</div>}
          {currentPipelineHint && <div className={`notice-banner ${currentPipelineHint.tone}`}>{currentPipelineHint.text}</div>}
          <section className="panel-section">
            <div className="section-title">视频文件</div>
            <label className="upload-zone" onDragOver={(event) => event.preventDefault()} onDrop={dropUploadFiles}>
              <Upload size={22} />
              <span>{uploading ? '上传中...' : '拖拽或点击上传视频'}</span>
              <input type="file" multiple accept=".mp4,.mkv,.avi,.mov,.webm" onChange={uploadFiles} disabled={uploading} />
            </label>
            <div className="video-list">
              {workspace.materials.length === 0 ? (
                <div className="inline-empty">暂无素材</div>
              ) : (
                workspace.materials.map((material) => (
                  <div
                    className="video-row"
                    draggable
                    key={material.id}
                    onDragStart={() => setDraggingMaterial(material.id)}
                    onDragOver={(event: DragEvent) => event.preventDefault()}
                    onDrop={() => dropMaterial(material.id)}
                  >
                    <span className="drag-handle">☰</span>
                    <FileVideo size={16} />
                    <div className="video-main">
                      <span className="video-name">{material.filename}</span>
                      <span className="video-meta">
                        {fmtSize(material.size_bytes)}
                        {material.duration ? ` · ${material.duration.toFixed(1)}s` : ''}
                        {material.width && material.height ? ` · ${material.width}x${material.height}` : ''}
                      </span>
                      <span className={`asr-pill ${material.asr_status || 'not_started'}`} title={material.asr_error_message || undefined}>
                        {asrStatusLabels[material.asr_status || 'not_started'] || material.asr_status || 'ASR 未转写'}
                      </span>
                    </div>
                    <button className="danger icon-button" onClick={() => deleteMaterial(material)} title="删除">
                      <Trash2 size={15} />
                    </button>
                  </div>
                ))
              )}
            </div>
          </section>

          <section className="panel-section">
            <div className="section-title">混剪配置</div>
            <TemplateSelect
              title="剪辑模板"
              templates={clipTemplates}
              activeTemplateId={activeTemplateByType.clip}
              isActiveDirty={dirtyTemplateByType.clip}
              onApply={applyTemplate}
              onDelete={deleteTemplate}
              onDuplicate={duplicateTemplate}
              onDefault={setDefaultTemplate}
            />
            <div className="form-grid two">
              <SelectField label="内容类型" value={config.contentType} options={['高光', '悬疑', '搞笑', '情感', '动作', '剧情概要', '自定义']} onChange={(contentType) => updateConfig({ contentType }, 'clip')} />
              <SelectField label="成片时长" value={config.durationRange} options={['30 秒', '60 秒', '1-3 分钟', '3-5 分钟', '5-10 分钟', '自定义']} onChange={(durationRange) => updateConfig({ durationRange }, 'clip')} />
              <NumberField label="输出数量" value={config.outputCount} onChange={(outputCount) => updateConfig({ outputCount }, 'clip')} />
              <SelectField label="节奏风格" value={config.pace} options={['快节奏', '剧情向', '强反转', '情绪递进', '信息密集', '自定义']} onChange={(pace) => updateConfig({ pace }, 'clip')} />
              <SelectField label="目标平台" value={config.targetPlatform} options={['通用', '抖音', '快手', '视频号', '小红书', 'B站']} onChange={(targetPlatform) => updateConfig({ targetPlatform }, 'clip')} />
              <SelectField label="画幅" value={config.aspectRatio} options={['9:16', '16:9', '1:1', '保持原始']} onChange={(aspectRatio) => updateConfig({ aspectRatio }, 'clip')} />
            </div>
            <label className="check-row">
              <input type="checkbox" checked={config.keepSuspense} onChange={(event) => updateConfig({ keepSuspense: event.target.checked }, 'clip')} />
              保留悬念
            </label>
            <TextArea label="剪辑规则描述" value={config.clipRule} placeholder="如：选取高光时段，成片30秒，需要强反转开头" onChange={(clipRule) => updateConfig({ clipRule }, 'clip')} />
            <ModelField label="剪辑模型" value={config.clipModel} options={llmModelOptions} onChange={(clipModel) => updateConfig({ clipModel }, 'clip')} />
            <button className="secondary full" onClick={() => saveTemplate('clip')}>
              <Save size={15} /> 保存当前剪辑模板
            </button>

            <TemplateSelect
              title="审查模板"
              templates={reviewTemplates}
              activeTemplateId={activeTemplateByType.review}
              isActiveDirty={dirtyTemplateByType.review}
              onApply={applyTemplate}
              onDelete={deleteTemplate}
              onDuplicate={duplicateTemplate}
              onDefault={setDefaultTemplate}
            />
            <TextArea label="审查规则描述" value={config.reviewRule} placeholder="如：画面不能出现人民币、广告水印或二维码" onChange={(reviewRule) => updateConfig({ reviewRule }, 'review')} />
            <ModelField label="审查模型" value={config.reviewModel} options={llmModelOptions} onChange={(reviewModel) => updateConfig({ reviewModel }, 'review')} />
            <button className="secondary full" onClick={() => saveTemplate('review')}>
              <Save size={15} /> 保存当前审查模板
            </button>

            <div className="form-grid two">
              <SelectField label="Whisper 模型" value={config.whisperModel} options={['tiny', 'base', 'small', 'medium', 'large', 'large-v2', 'large-v3']} onChange={(whisperModel) => updateConfig({ whisperModel }, 'clip')} />
              <label className="field">
                <span>字幕颜色</span>
                <input type="color" value={config.fontColor} onChange={(event) => updateConfig({ fontColor: event.target.value }, 'clip')} />
              </label>
            </div>
            <label className="field">
              <span>剧名</span>
              <input value={config.dramaName} placeholder="输入剧名" onChange={(event) => updateConfig({ dramaName: event.target.value }, 'clip')} />
            </label>
            <div className="toggle-row">
              <label><input type="checkbox" checked={config.cornerEnabled} onChange={(event) => updateConfig({ cornerEnabled: event.target.checked }, 'clip')} /> 角标</label>
              <label><input type="checkbox" checked={config.endingEnabled} onChange={(event) => updateConfig({ endingEnabled: event.target.checked }, 'clip')} /> 片尾</label>
            </div>
            <button className="primary full submit-button" onClick={submitJob} disabled={busy || workspace.materials.length === 0}>
              <ListRestart size={16} /> 开始混剪
            </button>
          </section>

          <section className="panel-section">
            <div className="section-title">任务历史</div>
            <div className="job-list">
              {workspace.jobs.length === 0 ? (
                <div className="inline-empty">暂无任务</div>
              ) : (
                workspace.jobs.map((job) => (
                  <button className={`job-row ${selectedJob?.id === job.id ? 'active' : ''}`} key={job.id} onClick={() => selectJob(job.id)}>
                    <span className={statusClass(job.status)}>{statusLabels[job.status]}</span>
                    <span className="job-rule">{job.rule_summary}</span>
                    <span className="job-meta">
                      {fmtDate(job.created_at)} · whisper: {job.whisper_model} · 输出 {job.output_count}
                      {job.duration_seconds ? ` · ${job.duration_seconds}s` : ''}
                    </span>
                  </button>
                ))
              )}
            </div>
          </section>
        </aside>

        <section className="right-panel">
          <div className="progress-panel">
            <div className="progress-header">
              <div>
                <span className="muted">当前任务</span>
                <h2>{selectedJob ? stageLabels[selectedJob.stage] || selectedJob.stage : '等待任务'}</h2>
              </div>
              <strong>{selectedJob?.progress ?? 0}%</strong>
            </div>
            <div className="progress-track">
              <div className={`progress-fill ${selectedJob?.status === 'error' ? 'error' : ''}`} style={{ width: `${selectedJob?.progress ?? 0}%` }} />
            </div>
            <div className="stage-row">
              {['queued', 'probe', 'asr', 'analysis', 'review', 'compose', 'package', 'done'].map((stage) => (
                <span className={selectedJob?.stage === stage ? 'active' : ''} key={stage}>{stageLabels[stage]}</span>
              ))}
            </div>
            {selectedJob && (
              <div className="job-actions">
                <span className={statusClass(selectedJob.status)}>{statusLabels[selectedJob.status]}</span>
                {selectedJob.duration_seconds ? <span className="duration-pill">耗时 {selectedJob.duration_seconds}s</span> : null}
                {!terminalStatuses.has(selectedJob.status) && (
                  <button className="danger" onClick={cancelJob}><XCircle size={15} /> 取消</button>
                )}
                {selectedJob.status === 'error' && (
                  <button className="secondary" onClick={retryJob}><RotateCcw size={15} /> 重试</button>
                )}
                {terminalStatuses.has(selectedJob.status) && (
                  <button className="secondary" onClick={duplicateJob}><Copy size={15} /> 复制配置</button>
                )}
              </div>
            )}
          </div>

          <div className="split-content">
            <section className="log-panel">
              <div className="section-title">任务日志</div>
              <pre>{logs.length ? logs.join('') : '暂无日志'}</pre>
              {selectedJob && <InputSnapshot job={selectedJob} />}
            </section>
            <section className="results-panel">
              {selectedJob && <ExplainabilityPanel job={selectedJob} />}
              <div className="section-title">输出视频</div>
              {!selectedJob ? (
                <div className="inline-empty">暂无结果</div>
              ) : selectedJob.outputs.length === 0 ? (
                <div className="inline-empty">
                  {selectedJob.status === 'done'
                    ? '任务完成但无可预览视频'
                    : selectedJob.status === 'cancelled'
                      ? '任务已取消'
                      : '等待任务完成'}
                </div>
              ) : (
                <div className="result-grid">
                  {selectedJob.outputs.map((output) => (
                    <article className="result-card" key={output.id}>
                      <h3>{output.name}</h3>
                      <video controls src={`/api/jobs/${selectedJob.id}/outputs/${output.id}`} />
                      <div className="result-meta">
                        <span>{fmtSize(output.size_bytes)}</span>
                        <span className="status done">{output.review_status === 'passed' ? '审查通过' : output.review_status}</span>
                      </div>
                      <a className="download-link" href={`/api/jobs/${selectedJob.id}/outputs/${output.id}?download=true`}>
                        <Download size={15} /> 下载
                      </a>
                      <div className="feedback-box">
                        <span>
                          <MessageSquare size={14} />
                          {output.feedback_status
                            ? `反馈：${feedbackLabels[output.feedback_status]}`
                            : '结果反馈'}
                        </span>
                        {output.feedback_reason && <em>{output.feedback_reason}</em>}
                        <div className="feedback-actions">
                          <button className={output.feedback_status === 'usable' ? 'secondary active' : 'secondary'} onClick={() => submitOutputFeedback(output.id, 'usable')}>
                            <CheckCircle2 size={14} /> 可用
                          </button>
                          <button className={output.feedback_status === 'needs_edit' ? 'secondary active' : 'secondary'} onClick={() => submitOutputFeedback(output.id, 'needs_edit')}>
                            <Wrench size={14} /> 需修改
                          </button>
                          <button className={output.feedback_status === 'rejected' ? 'secondary active' : 'secondary'} onClick={() => submitOutputFeedback(output.id, 'rejected')}>
                            <Ban size={14} /> 不可用
                          </button>
                        </div>
                      </div>
                      {refineState?.outputId === output.id && (
                        <div className="refine-dialog">
                          <strong>{refineState.action === 'adjust' ? '调整方案' : '重新生成'}</strong>
                          <textarea
                            placeholder={refineState.action === 'adjust' ? '告诉 AI 哪里需要调整…' : '告诉 AI 你期望的方向…'}
                            value={refineState.feedback}
                            onChange={(e) => setRefineState({ ...refineState, feedback: e.target.value })}
                            rows={3}
                          />
                          <div className="refine-actions">
                            <button className="primary" onClick={submitRefine} disabled={!refineState.feedback.trim() || refineLoading}>
                              {refineLoading ? 'AI 优化中…' : refineState.action === 'adjust' ? '让 AI 调整' : '让 AI 重新生成'}
                            </button>
                            <button className="secondary" onClick={() => setRefineState(null)}>取消</button>
                          </div>
                        </div>
                      )}
                    </article>
                  ))}
                </div>
              )}
            </section>
          </div>
        </section>
      </div>
      {workspaceModalOpen && (
        <div className="modal-backdrop" onClick={closeWorkspaceModal}>
          <div className="modal-card" onClick={(event) => event.stopPropagation()}>
            <div className="modal-head">
              <h2>新建工作空间</h2>
              <button className="ghost icon-button" onClick={closeWorkspaceModal} disabled={busy} title="关闭">
                <XCircle size={16} />
              </button>
            </div>
            <label className="field">
              <span>工作空间名称</span>
              <input
                autoFocus
                value={workspaceDraft}
                placeholder="例如：AI Agent 混剪测试"
                onChange={(event) => setWorkspaceDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && workspaceDraft.trim()) {
                    void createWorkspace();
                  }
                }}
              />
            </label>
            <div className="modal-actions">
              <button className="secondary" onClick={closeWorkspaceModal} disabled={busy}>取消</button>
              <button className="primary" onClick={() => void createWorkspace()} disabled={busy || !workspaceDraft.trim()}>
                <Plus size={16} /> 创建
              </button>
            </div>
          </div>
        </div>
      )}
      {settingsModal}
    </main>
  );
}

function TemplateSelect({
  title,
  templates,
  activeTemplateId,
  isActiveDirty,
  onApply,
  onDelete,
  onDuplicate,
  onDefault,
}: {
  title: string;
  templates: Template[];
  activeTemplateId: string | null;
  isActiveDirty: boolean;
  onApply: (template: Template) => void;
  onDelete: (template: Template, event: MouseEvent) => void;
  onDuplicate: (template: Template, event: MouseEvent) => void;
  onDefault: (template: Template, event: MouseEvent) => void;
}) {
  const selectedTemplate = templates.find((template) => template.id === activeTemplateId) || null;
  const stateLabel = selectedTemplate ? (isActiveDirty ? '已修改' : '当前') : '未选择';
  return (
    <div className="template-block">
      <div className="template-select-head">
        <label className="field template-select-field">
          <span>{title}</span>
          <select
            value={activeTemplateId || ''}
            onChange={(event) => {
              const template = templates.find((item) => item.id === event.target.value);
              if (template) void onApply(template);
            }}
          >
            <option value="">选择模板</option>
            {templates.map((template) => (
              <option key={template.id} value={template.id}>
                {template.name}{template.is_default ? '（默认）' : ''}
              </option>
            ))}
          </select>
        </label>
        <div className="template-action-row">
          <button className="secondary icon-button" disabled={!selectedTemplate} onClick={(event) => selectedTemplate && onDuplicate(selectedTemplate, event)} title="复制模板">
            <Copy size={14} />
          </button>
          <button className="secondary icon-button" disabled={!selectedTemplate} onClick={(event) => selectedTemplate && onDefault(selectedTemplate, event)} title="设为默认">
            <Star size={14} />
          </button>
          <button className="danger icon-button" disabled={!selectedTemplate} onClick={(event) => selectedTemplate && onDelete(selectedTemplate, event)} title="删除模板">
            <Trash2 size={14} />
          </button>
        </div>
      </div>
      <div className={`template-state ${selectedTemplate?.is_default ? 'default' : ''} ${selectedTemplate ? 'active' : ''}`}>
        <span>{stateLabel}</span>
        {selectedTemplate?.is_default && <span>默认</span>}
        {selectedTemplate && <em>{selectedTemplate.name}</em>}
      </div>
    </div>
  );
}

function ExplainabilityPanel({ job }: { job: Job }) {
  const explainability = (job.explainability || {}) as Record<string, unknown>;
  const rawSummary = explainability.summary;
  const rawTimeline = explainability.timeline;
  const rawExcluded = explainability.excluded;
  const rawReview = explainability.review_report;
  const rawComparison = explainability.comparison;
  const timeline = Array.isArray(rawTimeline)
    ? rawTimeline.filter(isRecord).map((item, index) => ({
        source: textValue(item.source, textValue(item.filename, textValue(item.material_id, `片段 ${index + 1}`))),
        start: numberValue(item.start, numberValue(item.start_time)),
        end: numberValue(item.end, numberValue(item.end_time, numberValue(item.start) + numberValue(item.duration))),
        score: numberValue(item.score, 8.5),
        reason: textValue(item.reason, textValue(item.selection_reason, textValue(item.text_overlay, '历史任务未提供选择理由'))),
        evidence_source: textValue(item.evidence_source, textValue(item.evidenceSource, 'metadata')),
        evidence_text: textValue(item.evidence_text, textValue(item.evidenceText, '')),
      }))
    : [];
  const summary = isRecord(rawSummary)
    ? {
        title: textValue(rawSummary.title, '历史 AI 方案'),
        clip_count: numberValue(rawSummary.clip_count, timeline.length),
        estimated_duration: numberValue(rawSummary.estimated_duration),
        target_platform: textValue(rawSummary.target_platform, '-'),
        aspect_ratio: textValue(rawSummary.aspect_ratio, '-'),
        storyline: textValue(rawSummary.storyline, ''),
      }
    : typeof rawSummary === 'string' && rawSummary.trim()
      ? {
          title: '历史 AI 方案',
          clip_count: timeline.length,
          estimated_duration: timeline.reduce((sum, item) => sum + Math.max(0, item.end - item.start), 0),
          target_platform: '-',
          aspect_ratio: '-',
          storyline: rawSummary,
        }
      : null;
  const excluded = Array.isArray(rawExcluded)
    ? rawExcluded.map((item, index) =>
        isRecord(item)
          ? {
              source: textValue(item.source, textValue(item.filename, `排除片段 ${index + 1}`)),
              reason: textValue(item.reason, textValue(item.detail, '历史任务未提供排除原因')),
            }
          : {
              source: `排除片段 ${index + 1}`,
              reason: String(item),
            },
      )
    : [];
  const review = isRecord(rawReview)
    ? {
        status: textValue(rawReview.status, 'not_checked'),
        risk_level: textValue(rawReview.risk_level, '-'),
        model: textValue(rawReview.model, textValue((explainability.llm_source as Record<string, unknown> | undefined)?.model, '-')),
        items: Array.isArray(rawReview.items)
          ? rawReview.items.filter(isRecord).map((item) => ({
              time: textValue(item.time, '全片'),
              rule: textValue(item.rule, '历史审查'),
              result: textValue(item.result, '-'),
              action: textValue(item.action, '-'),
            }))
          : Array.isArray(rawReview.issues)
            ? rawReview.issues.map((item) =>
                isRecord(item)
                  ? {
                      time: textValue(item.time, '全片'),
                      rule: textValue(item.rule, '历史审查'),
                      result: textValue(item.result, textValue(item.detail, '-')),
                      action: textValue(item.action, '人工复核'),
                    }
                  : {
                      time: '全片',
                      rule: '历史审查',
                      result: String(item),
                      action: '人工复核',
                    },
              )
            : textValue(rawReview.details)
              ? [
                  {
                    time: '全片',
                    rule: '历史审查',
                    result: textValue(rawReview.details),
                    action: rawReview.status === 'passed' ? '允许输出' : '人工复核',
                  },
                ]
              : [],
      }
    : null;
  const comparison = Array.isArray(rawComparison)
    ? rawComparison.filter(isRecord).map((item, index) => ({
        name: textValue(item.name, `方案 ${index + 1}`),
        duration_seconds: numberValue(item.duration_seconds, summary?.estimated_duration || 0),
        clip_count: numberValue(item.clip_count, timeline.length),
        strength: textValue(item.strength, textValue(item.summary, '-')),
        tradeoff: textValue(item.tradeoff, textValue(item.risk, '-')),
      }))
    : isRecord(rawComparison)
      ? [
          {
            name: '历史方案对比',
            duration_seconds: summary?.estimated_duration || 0,
            clip_count: timeline.length,
            strength: textValue(rawComparison.value_gain, textValue(rawComparison.new_structure, '-')),
            tradeoff: textValue(rawComparison.original_structure, '需结合人工复核判断'),
          },
        ]
      : [];

  return (
    <section className="explain-panel">
      <div className="section-title">AI 时间线草稿</div>
      {!summary ? (
        <div className="inline-empty">
          {job.status === 'done' ? '暂无可解释数据' : '任务完成后生成方案解释'}
        </div>
      ) : (
        <>
          <div className="summary-strip">
            <div>
              <span>方案</span>
              <strong>{summary.title}</strong>
            </div>
            <div>
              <span>片段</span>
              <strong>{summary.clip_count} 个</strong>
            </div>
            <div>
              <span>预计时长</span>
              <strong>{fmtSeconds(summary.estimated_duration)}</strong>
            </div>
            <div>
              <span>平台/画幅</span>
              <strong>{summary.target_platform} · {summary.aspect_ratio}</strong>
            </div>
          </div>
          <p className="storyline">{summary.storyline}</p>

          <details className="explain-detail" open>
            <summary>时间线草稿</summary>
            {timeline.length === 0 ? (
              <div className="inline-empty">暂无入选片段</div>
            ) : (
              <div className="timeline-list">
                {timeline.map((item, index) => (
                  <div className="timeline-item" key={`${item.source}-${index}`}>
                    <span className="timeline-index">{index + 1}</span>
                    <div>
                      <strong>{item.source}</strong>
                      <p>{fmtSeconds(item.start)} - {fmtSeconds(item.end)} · 评分 {item.score}</p>
                      <span className={`evidence-pill ${item.evidence_source || 'metadata'}`}>
                        {evidenceLabels[item.evidence_source || 'metadata'] || '元信息推断'}
                      </span>
                      <em>{item.reason}</em>
                      {item.evidence_source !== 'asr' && (
                        <small className="evidence-note">该片段尚未由字幕验证</small>
                      )}
                      {item.evidence_text && <small className="evidence-note">{item.evidence_text}</small>}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </details>

          <div className="explain-grid">
            <details className="explain-detail">
              <summary>排除片段</summary>
              {excluded.length === 0 ? (
                <div className="inline-empty">没有被排除的素材</div>
              ) : (
                <ul>
                  {excluded.map((item, index) => (
                    <li key={`${item.source}-${index}`}>
                      <strong>{item.source}</strong>
                      <span>{item.reason}</span>
                    </li>
                  ))}
                </ul>
              )}
            </details>

            <details className="explain-detail">
              <summary>审查报告</summary>
              {review ? (
                <>
                  <div className="review-head">
                    <span className={review.status === 'passed' ? 'status done' : 'status running'}>
                      {review.status === 'passed' ? '通过' : review.status}
                    </span>
                    <span>风险：{review.risk_level}</span>
                    <span>{review.model}</span>
                  </div>
                  <ul>
                    {review.items.map((item, index) => (
                      <li key={`${item.rule}-${index}`}>
                        <strong>{item.time} · {item.rule}</strong>
                        <span>{item.result}，{item.action}</span>
                      </li>
                    ))}
                  </ul>
                </>
              ) : (
                <div className="inline-empty">暂无审查报告</div>
              )}
            </details>
          </div>

          {comparison.length > 0 && (
            <div className="comparison-row">
              {comparison.map((item) => (
                <article className="comparison-card" key={item.name}>
                  <strong>{item.name}</strong>
                  <span>{fmtSeconds(item.duration_seconds)} · {item.clip_count} 段</span>
                  <p>{item.strength}</p>
                  <em>{item.tradeoff}</em>
                </article>
              ))}
            </div>
          )}
        </>
      )}
    </section>
  );
}

function InputSnapshot({ job }: { job: Job }) {
  const snapshot = job.input_snapshot as {
    materials?: Array<{ filename?: string; size_bytes?: number; duration?: number }>;
    config?: Partial<JobConfig>;
  };
  const materials = snapshot.materials || [];
  const config = snapshot.config || {};
  return (
    <details className="snapshot-panel">
      <summary>输入快照</summary>
      <div className="snapshot-grid">
        <span>素材</span>
        <strong>{materials.length} 个</strong>
        <span>规则</span>
        <strong>{config.clipRule || config.contentType || '未填写'}</strong>
        <span>模型</span>
        <strong>{config.clipModel || '-'} / {config.whisperModel || '-'}</strong>
        <span>包装</span>
        <strong>{config.dramaName || '无剧名'} · {config.fontColor || '#ffff00'}</strong>
      </div>
      {materials.length > 0 && (
        <ul className="snapshot-list">
          {materials.map((material, index) => (
            <li key={`${material.filename}-${index}`}>
              {index + 1}. {material.filename || '未命名'} {material.size_bytes ? `· ${fmtSize(material.size_bytes)}` : ''}
            </li>
          ))}
        </ul>
      )}
    </details>
  );
}

function SelectField({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (value: string) => void;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => (
          <option key={option} value={option}>{option}</option>
        ))}
      </select>
    </label>
  );
}

function ModelField({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (value: string) => void;
}) {
  const remoteOptions = Array.from(new Set(options.map((item) => item.trim()).filter(Boolean)));
  const selectValue = remoteOptions.includes(value) ? value : '__custom__';
  const isCustom = remoteOptions.length === 0 || selectValue === '__custom__';
  return (
    <label className="field model-field">
      <span>{label}</span>
      <div className={isCustom ? 'model-picker custom' : 'model-picker'}>
        <select
          value={remoteOptions.length > 0 ? selectValue : ''}
          onChange={(event) => {
            const next = event.target.value;
            onChange(next === '__custom__' ? '' : next);
          }}
          disabled={remoteOptions.length === 0}
        >
          {remoteOptions.length === 0 ? (
            <option value="">未获取到模型</option>
          ) : (
            <>
              <option value="__custom__">自定义模型...</option>
              {remoteOptions.map((option) => (
                <option key={option} value={option}>{option}</option>
              ))}
            </>
          )}
        </select>
        {isCustom && (
          <input value={value} placeholder="手动输入模型名" onChange={(event) => onChange(event.target.value)} />
        )}
      </div>
      <small className="field-hint">
        {remoteOptions.length > 0 ? (
          <>已获取 {remoteOptions.length} 个模型；选择自定义后可手动输入。</>
        ) : (
          <>当前接口未返回模型，可手动输入。</>
        )}
      </small>
    </label>
  );
}

function NumberField({ label, value, onChange }: { label: string; value: number; onChange: (value: number) => void }) {
  return (
    <label className="field">
      <span>{label}</span>
      <input type="number" min={1} max={5} value={value} onChange={(event) => onChange(Number(event.target.value))} />
    </label>
  );
}

function TextArea({
  label,
  value,
  placeholder,
  onChange,
}: {
  label: string;
  value: string;
  placeholder: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <textarea value={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

export default App;
