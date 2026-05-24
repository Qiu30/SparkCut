import type { SparkCutController } from '../hooks/useSparkCutController';
import { InputSnapshot } from './InputSnapshot';

export function LogPanel({ controller }: { controller: SparkCutController }) {
  const { logs, selectedJob } = controller;

  return (
            <section className="log-panel">
              <div className="section-title">任务日志</div>
              <pre>{logs.length ? logs.join('') : '暂无日志'}</pre>
              {selectedJob && <InputSnapshot job={selectedJob} />}
            </section>
  );
}
