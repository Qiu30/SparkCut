import { Plus, XCircle } from 'lucide-react';

interface WorkspaceCreateModalProps {
  workspaceModalOpen: boolean;
  busy: boolean;
  workspaceDraft: string;
  closeWorkspaceModal: () => void;
  createWorkspace: () => void;
  setWorkspaceDraft: (value: string) => void;
}

export function WorkspaceCreateModal({
  workspaceModalOpen,
  busy,
  workspaceDraft,
  closeWorkspaceModal,
  createWorkspace,
  setWorkspaceDraft,
}: WorkspaceCreateModalProps) {
  if (!workspaceModalOpen) return null;

  return (
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
  );
}
