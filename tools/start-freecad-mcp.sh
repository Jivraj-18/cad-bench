#!/bin/bash
set -euo pipefail
# This process and the RPC service live INSIDE the task's agent container.
# The container has no hidden reference or verifier assets.
xvfb-run -a freecad /opt/cad-bench-tools/start-freecad-mcp.FCMacro > /tmp/cad-bench-mcp-gui.log 2>&1 &
cad_gui_pid=$!
trap 'kill "$cad_gui_pid" 2>/dev/null || true' EXIT
python3 - <<'PY'
import time, xmlrpc.client, socket
socket.setdefaulttimeout(2)
for attempt in range(60):
    try:
        with xmlrpc.client.ServerProxy('http://127.0.0.1:9875', allow_none=True) as server:
            if server.ping():
                break
    except Exception:
        time.sleep(1)
else:
    raise SystemExit('FreeCAD MCP GUI/RPC failed to start; inspect /tmp/cad-bench-mcp-gui.log')
PY
/opt/cad-bench-mcp/bin/python /opt/cad-bench-tools/run-freecad-mcp.py
