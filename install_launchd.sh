#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
PLIST="$HOME/Library/LaunchAgents/com.designmastersolutions.metac-bot.plist"
if [[ "${1:-}" != "--print" ]]; then
  [[ -f "$HOME/.config/clauditor/metaculus_token" ]] || { echo "Missing human-provided Metaculus token; nothing installed"; exit 1; }
  [[ -x "$ROOT/.venv/bin/python" ]] || { echo "Create .venv first"; exit 1; }
fi
"$ROOT/.venv/bin/python" - "$ROOT" "$PLIST" "${1:-}" <<'PY'
import os, pathlib, plistlib, sys
root, target, mode = sys.argv[1:]
data = {
    'Label': 'com.designmastersolutions.metac-bot',
    'ProgramArguments': [root+'/.venv/bin/python', root+'/metac_bot.py'],
    'WorkingDirectory': root,
    'StartInterval': 1200,
    'EnvironmentVariables': {'PATH': os.environ['PATH'], 'HOME': str(pathlib.Path.home()),
        **{k:os.environ[k] for k in ('CODEX_HOME','CLAUDE_CONFIG_DIR') if k in os.environ}},
    'StandardOutPath': root+'/runtime/launchd.out.log',
    'StandardErrorPath': root+'/runtime/launchd.err.log',
}
if mode == '--print':
    print(plistlib.dumps(data).decode())
else:
    token=pathlib.Path.home()/'.config/clauditor/metaculus_token'
    if token.stat().st_mode & 0o077: raise SystemExit('Token must have mode 600')
    pathlib.Path(root+'/runtime').mkdir(exist_ok=True)
    pathlib.Path(target).parent.mkdir(parents=True,exist_ok=True)
    pathlib.Path(target).write_bytes(plistlib.dumps(data))
PY
if [[ "${1:-}" != "--print" ]]; then
  launchctl bootout "gui/$(id -u)/com.designmastersolutions.metac-bot" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$PLIST"
  echo "Installed 20-minute interval job (no KeepAlive); next run within 20 minutes."
fi
