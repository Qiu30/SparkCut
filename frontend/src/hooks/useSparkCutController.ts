import { ChangeEvent, DragEvent, MouseEvent, useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api';
import {
  configFromJob,
  fmtSize,
  normalizeConfigModels,
  readVideoMetadata,
  terminalStatuses,
} from '../appConfig';
import type { FeedbackStatus, Job, Material, Template, TemplateType, WorkspaceDetail, WorkspaceSummary } from '../types';
import { useJobConfig } from './useJobConfig';
import { usePipeline } from './usePipeline';
import { useSettings } from './useSettings';
import { useTemplates } from './useTemplates';

export function useSparkCutController() {
  const [workspaces, setWorkspaces] = useState<WorkspaceSummary[]>([]);
  const [workspace, setWorkspace] = useState<WorkspaceDetail | null>(null);
  const [storageSummary, setStorageSummary] = useState<string>('0 B');
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
  const logOffsetRef = useRef(0);

  const {
    config,
    activeTemplateByType,
    dirtyTemplateByType,
    normalizeCurrentConfig,
    updateConfig,
    setConfig,
    setActiveTemplateByType,
    setDirtyTemplateByType,
  } = useJobConfig();
  const { templates, clipTemplates, reviewTemplates, loadTemplates } = useTemplates();
  const {
    pipelineStatus,
    llmModels,
    defaultLlmModel,
    currentPipelineHint,
    llmModelOptions,
    loadPipelineStatus,
    loadLlmModels,
  } = usePipeline(normalizeCurrentConfig);
  const {
    settingsOpen,
    settingsDraft,
    settingsApiKey,
    settingsSaving,
    runtimeModelOptions,
    openSettings,
    closeSettings,
    saveSettings,
    setSettingsDraft,
    setSettingsApiKey,
  } = useSettings({ loadPipelineStatus, loadLlmModels, setError });

  const loadWorkspaces = useCallback(async () => {
    setWorkspaces(await api.listWorkspaces());
  }, []);

  const loadStorageSummary = useCallback(async () => {
    const summary = await api.getStorageSummary();
    setStorageSummary(fmtSize(summary.storage_bytes));
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

  function openWorkspaceModal() {
    setWorkspaceDraft('');
    setWorkspaceModalOpen(true);
  }

  function closeWorkspaceModal() {
    if (busy) return;
    setWorkspaceModalOpen(false);
    setWorkspaceDraft('');
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
    setError(warnings.length ? `当前任务有运行提醒：${warnings.join(' ')}` : null);
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


  return {
    workspaces,
    workspace,
    storageSummary,
    config,
    activeTemplateByType,
    dirtyTemplateByType,
    selectedJob,
    logs,
    busy,
    uploading,
    error,
    workspaceDraft, workspaceModalOpen,
    refineState,
    refineLoading,
    settingsOpen, settingsDraft, settingsApiKey, settingsSaving,
    currentPipelineHint,
    clipTemplates, reviewTemplates, llmModelOptions, runtimeModelOptions,
    openWorkspace,
    selectJob,
    updateConfig,
    openWorkspaceModal,
    closeWorkspaceModal,
    openSettings,
    closeSettings,
    saveSettings,
    createWorkspace,
    uploadFiles,
    dropUploadFiles,
    deleteMaterial,
    dropMaterial,
    applyTemplate,
    saveTemplate,
    deleteTemplate,
    duplicateTemplate,
    setDefaultTemplate,
    submitJob,
    cancelJob,
    retryJob,
    duplicateJob,
    submitOutputFeedback,
    submitRefine,
    setWorkspace,
    setWorkspaceDraft,
    setDraggingMaterial,
    setRefineState,
    setSettingsDraft,
    setSettingsApiKey,
  };
}

export type SparkCutController = ReturnType<typeof useSparkCutController>;
