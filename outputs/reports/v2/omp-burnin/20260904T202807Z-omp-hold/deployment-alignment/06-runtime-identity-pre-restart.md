# Deployment Alignment — Runtime Identity Before Restart

`state/extension-runtime-ready.json` is written once per extension factory
lifecycle (frozen-per-lifecycle model; see
`brainstem/prime-extension/README.md` "frozen-per-lifecycle semantics" and
`outputs/reports/v2/burnin/09-extension-lifecycle-freeze.json`). Deploying new
extension source bytes to the auto-discovery path does **not** retroactively
update this file for any OMP process that already loaded the old extension
into memory.

Current (pre-restart) content, unchanged by the file replacement in step 5:

```json
{
  "resolved_at": "2026-09-04T19:49:25.373Z",
  "home": "C:\\Users\\assas\\Documents\\The-Second-Brain\\.worktrees\\v2-one-shot",
  "runtime_python": "C:\\Users\\assas\\Documents\\The-Second-Brain\\.worktrees\\v2-one-shot\\.venv\\Scripts\\python.exe",
  "brain_version": "2.0.0-rc.1",
  "identity_hash": "a590f1614c1b3b03ed7b485bc8ca8071c9718fe8902cfd71662ecbfb7634c72a"
}
```

This is expected and is not itself a defect: it predates both the deployment
sync and the HTTP 429 boundary. A fresh OMP process must be started (next
step) so a new extension factory instance loads the now-synchronized
extension and overwrites this file with a fresh `resolved_at` timestamp,
proving the newly deployed code is actually what a live OMP session loads.
