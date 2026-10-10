#!/usr/bin/env python3
"""Exercise the actual isolated GUI, MCP tools, and FreeCAD runtime without a model."""
import asyncio
import json
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
ROOT=Path(__file__).resolve().parents[1]


async def main():
    params=StdioServerParameters(command='docker',args=[
        'run','--rm','-i','--network','none','--entrypoint',
        '/opt/cad-bench-tools/start-freecad-mcp.sh','cad-bench-mcp-smoke:1.1.0'])
    async with stdio_client(params) as (read,write):
      async with ClientSession(read,write) as session:
        await session.initialize()
        tools=await session.list_tools()
        names=[t.name for t in tools.tools]
        assert 'get_view' in names and 'execute_code' in names
        assert 'get_parts_list' not in names and 'insert_part_from_library' not in names
        headless=await session.call_tool('execute_code_headless',arguments={
            'code':"import FreeCAD as App\nassert App.Version()[:3]==['1','1','0']\nprint('FREECAD_RUNTIME_OK')"})
        assert not headless.is_error and any('FREECAD_RUNTIME_OK' in getattr(c,'text','') for c in headless.content)
        doc=await session.call_tool('create_document',arguments={'name':'Probe'})
        assert not doc.is_error
        shape=await session.call_tool('execute_code',arguments={'code':
            "import FreeCAD as App\ndoc=App.ActiveDocument\nbody=doc.addObject('PartDesign::Body','Body')\nbox=body.newObject('PartDesign::AdditiveBox','Box')\nbox.Length=10\nbox.Width=10\nbox.Height=10\ndoc.recompute()\nassert body.Shape.isValid()\nprint('GUI_GEOMETRY_OK')"})
        assert not shape.is_error and any('GUI_GEOMETRY_OK' in getattr(c,'text','') for c in shape.content)
        view_tool=next(t for t in tools.tools if t.name=='get_view')
        args={'doc_name':'Probe'}
        if 'view_name' in view_tool.input_schema.get('properties',{}):args['view_name']='Isometric'
        view=await session.call_tool('get_view',arguments=args)
        assert not view.is_error and any(c.type=='image' for c in view.content)
        output=ROOT/'runs/mcp-smoke.json'
        output.write_text(json.dumps({'status':'passed','tools':names,
            'headless_FreeCAD':'1.1.0','gui_geometry':'passed','image_feedback':'passed'},indent=2)+'\n')
        print('FreeCAD MCP GUI, geometry execution and image feedback passed.')


if __name__=='__main__':asyncio.run(main())
