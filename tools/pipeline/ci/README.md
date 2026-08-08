# Factory CI runner (Conversion Factory)

Replace the retired `VellumUeAgent` polling loop with a **self-hosted GitHub Actions runner** in an interactive logon session.

## Why interactive

UnrealEditor-Cmd fails under Session 0 / LocalSystem (matches prototype-v0). Autologon as `vellum` + runner as user process is the durable pattern.

## Install (Factory)

1. Create a GitHub fine-grained or classic PAT with `repo` scope (Actions self-hosted).
2. On Factory (interactive desktop):

```powershell
pwsh -File D:\dev\vellum\tools\pipeline\ci\install_runner.ps1 `
  -GitHubRepo AptlyClever/vellum `
  -Token <REGISTER_TOKEN>
```

3. Confirm runner appears in GitHub → Settings → Actions → Runners (`factory-vellum`).
4. Keep the machine awake; optional Task Scheduler "At logon" restart of `run.cmd` in the runner folder.

## Workflows

- [`.github/workflows/vellum-pipeline.yml`](../../../.github/workflows/vellum-pipeline.yml) — `workflow_dispatch` with `job` + `pack` inputs, `runs-on: [self-hosted, Windows, factory-vellum]`.

## Retired

Do not re-enable Scheduled Task `VellumUeAgent` without operator phrase `Unpark: Capture Agent`.
