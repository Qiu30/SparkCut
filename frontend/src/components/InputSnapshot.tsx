import { fmtSize } from '../appConfig';
import type { Job, JobConfig } from '../types';

export function InputSnapshot({ job }: { job: Job }) {
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
