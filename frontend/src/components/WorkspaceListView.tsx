import { HardDrive, Plus, Settings } from 'lucide-react';
import { fmtDate, statusClass, statusLabels } from '../appConfig';
import type { SparkCutController } from '../hooks/useSparkCutController';
import { WorkspaceCreateModal } from './WorkspaceCreateModal';

export function WorkspaceListView({ controller }: { controller: SparkCutController }) {
  const {
    workspaces,
    storageSummary,
    busy,
    error,
    currentPipelineHint,
    workspaceModalOpen,
    workspaceDraft,
    openSettings,
    openWorkspaceModal,
    closeWorkspaceModal,
    createWorkspace,
    setWorkspaceDraft,
    openWorkspace,
  } = controller;

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
        <WorkspaceCreateModal
          workspaceModalOpen={workspaceModalOpen}
          busy={busy}
          workspaceDraft={workspaceDraft}
          closeWorkspaceModal={closeWorkspaceModal}
          createWorkspace={createWorkspace}
          setWorkspaceDraft={setWorkspaceDraft}
        />
      </main>
  );
}
