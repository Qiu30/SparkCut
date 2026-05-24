import { ArrowLeft, Settings } from 'lucide-react';
import type { SparkCutController } from '../hooks/useSparkCutController';
import { JobConfigForm } from './JobConfigForm';
import { JobHistoryPanel } from './JobHistoryPanel';
import { JobProgressPanel } from './JobProgressPanel';
import { LogPanel } from './LogPanel';
import { ResultsPanel } from './ResultsPanel';
import { VideoUploadSection } from './VideoUploadSection';
import { WorkspaceCreateModal } from './WorkspaceCreateModal';

export function WorkbenchView({ controller }: { controller: SparkCutController }) {
  const {
    workspace,
    busy,
    error,
    currentPipelineHint,
    workspaceModalOpen,
    workspaceDraft,
    openSettings,
    closeWorkspaceModal,
    createWorkspace,
    setWorkspaceDraft,
    setWorkspace,
  } = controller;

  if (!workspace) return null;

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
          <VideoUploadSection controller={controller} />
          <JobConfigForm controller={controller} />
          <JobHistoryPanel controller={controller} />
        </aside>

        <section className="right-panel">
          <JobProgressPanel controller={controller} />
          <div className="split-content">
            <LogPanel controller={controller} />
            <ResultsPanel controller={controller} />
          </div>
        </section>
      </div>
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
