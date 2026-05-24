# Iteration Test Flow

Every completed iteration must pass the same release gate before the next iteration starts.

## Required Checks

1. Confirm services are reachable:
   - Backend: `http://127.0.0.1:8000/api/health`
   - Frontend: `http://127.0.0.1:5173/`
2. Run automated checks:
   - `cd backend && uv run pytest`
   - `cd frontend && npm run build`
3. Run an in-app browser smoke test:
   - Open `http://127.0.0.1:5173/`.
   - Create or open a QA workspace.
   - Ensure at least one MP4 material exists.
   - Open the workspace detail page.
   - Apply one clip template and one review template.
   - Click `开始混剪`.
   - Wait until the job reaches `已完成`.
   - Verify logs show all simulated pipeline stages.
   - Verify output video card appears with player and download link.
   - Click `复制配置`.
   - Cancel the duplicated running job.
   - Verify cancelled history item, logs, and output empty state.
   - Return to workspace list and verify the workspace card status.
4. Save screenshots under `test-artifacts/<iteration>/`.
5. Commit the completed iteration only after all required checks pass.

## Screenshot Evidence

Each iteration should save at least:

- `workspace-list.png`
- `job-completed.png`
- `job-cancelled.png`

Additional screenshots may be saved when an iteration adds a new major surface.
