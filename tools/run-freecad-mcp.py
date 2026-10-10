"""Run the frozen upstream server with only drawing-reconstruction tools."""
from freecad_mcp.server import mcp, state
from freecad_mcp.headless import parse_command

# Prebuilt parts would introduce a second source of geometry. FEM is unrelated
# to reconstructing these drawings. The original task contract still applies.
for name in ('insert_part_from_library', 'get_parts_list', 'run_fem_analysis'):
    mcp.remove_tool(name)
state.rpc_host = 'localhost'
state.only_text_feedback = False
state.freecadcmd = parse_command('/opt/conda/bin/freecadcmd')
mcp.run()
