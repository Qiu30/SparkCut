import type { FeedbackStatus, Job, JobConfig, JobStatus, PipelineStatus } from './types';

export const FALLBACK_LLM_MODEL = 'GLM-5.1';

export const defaultConfig: JobConfig = {
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

export function normalizeModel(value: string | undefined, models: string[], fallback: string, replaceBuiltInFallback = false): string {
  const trimmed = value?.trim();
  if (replaceBuiltInFallback && trimmed === FALLBACK_LLM_MODEL && models.length > 0 && !models.includes(trimmed)) {
    return models[0];
  }
  if (trimmed) return trimmed;
  return models[0] || fallback;
}

export function normalizeConfigModels(
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

export function configFromJob(job: Job, models: string[], fallback: string): JobConfig | null {
  const snapshotConfig = isRecord(job.input_snapshot.config) ? job.input_snapshot.config : null;
  if (!snapshotConfig) return null;
  return normalizeConfigModels({ ...defaultConfig, ...snapshotConfig } as JobConfig, models, fallback);
}

export const statusLabels: Record<JobStatus, string> = {
  queued: '排队中',
  running: '执行中',
  cancelled: '已取消',
  done: '已完成',
  error: '失败',
};

export const stageLabels: Record<string, string> = {
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

export const terminalStatuses = new Set<JobStatus>(['done', 'error', 'cancelled']);

export const feedbackLabels: Record<FeedbackStatus, string> = {
  usable: '可用',
  needs_edit: '需修改',
  rejected: '不可用',
};

export const asrStatusLabels: Record<string, string> = {
  pending: 'ASR 待处理',
  running: 'ASR 转写中',
  done: 'ASR 已转写',
  error: 'ASR 失败',
  not_started: 'ASR 未转写',
};

export const evidenceLabels: Record<string, string> = {
  asr: 'ASR 证据',
  metadata: '元信息推断',
  model_fallback: '模型兜底',
};

export function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

export function fmtDate(value: string): string {
  return new Date(value).toLocaleString('zh-CN');
}

export function statusClass(status?: string | null): string {
  return `status ${status || 'none'}`;
}

export function fmtSeconds(value?: number | null): string {
  if (!value) return '0s';
  return value >= 60 ? `${Math.floor(value / 60)}m ${(value % 60).toFixed(0)}s` : `${value.toFixed(1)}s`;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value));
}

export function textValue(value: unknown, fallback = ''): string {
  return typeof value === 'string' && value.trim() ? value : fallback;
}

export function numberValue(value: unknown, fallback = 0): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export function pipelineHint(status: PipelineStatus | null): { tone: 'error' | 'warning'; text: string } | null {
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
      text: `当前项目可以启动，但有运行提醒：${warnings.join(' ')}`,
    };
  }
  return null;
}

export async function readVideoMetadata(file: File): Promise<{
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
