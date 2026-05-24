import './styles.css';
import { SettingsModal } from './components/SettingsModal';
import { WorkbenchView } from './components/WorkbenchView';
import { WorkspaceListView } from './components/WorkspaceListView';
import { useSparkCutController } from './hooks/useSparkCutController';

function App() {
  const controller = useSparkCutController();
  const view = controller.workspace ? <WorkbenchView controller={controller} /> : <WorkspaceListView controller={controller} />;

  return (
    <>
      {view}
      <SettingsModal
        settingsOpen={controller.settingsOpen}
        settingsDraft={controller.settingsDraft}
        settingsApiKey={controller.settingsApiKey}
        settingsSaving={controller.settingsSaving}
        runtimeModelOptions={controller.runtimeModelOptions}
        closeSettings={controller.closeSettings}
        saveSettings={controller.saveSettings}
        setSettingsDraft={controller.setSettingsDraft}
        setSettingsApiKey={controller.setSettingsApiKey}
      />
    </>
  );
}

export default App;
