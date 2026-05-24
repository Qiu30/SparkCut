import { Copy, RotateCcw, XCircle } from 'lucide-react';
import { stageLabels, statusClass, statusLabels, terminalStatuses } from '../appConfig';
import type { SparkCutController } from '../hooks/useSparkCutController';

export function JobProgressPanel({ controller }: { controller: SparkCutController }) {
  const { selectedJob, cancelJob, retryJob, duplicateJob } = controller;

  return (
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
  );
}
