#!/usr/bin/env python3

import asyncio
import json
import traceback
from pathlib import Path

from mcp.client import Client

OUT = Path('results')
OUT.mkdir(exist_ok=True)
URL = 'https://mcp.flightpoints.com/mcp'

async def main():
    output = {'url': URL}
    try:
        async with Client(URL) as client:
            listed = await client.list_tools()
            output['status'] = 'ok'
            output['protocol_version'] = str(client.protocol_version)
            output['server_info'] = client.server_info.model_dump(mode='json') if client.server_info else None
            output['tools'] = [tool.model_dump(mode='json') for tool in listed.tools]
    except Exception as exc:
        output['status'] = 'error'
        output['error'] = f'{type(exc).__name__}: {exc}'
        output['traceback'] = traceback.format_exc(limit=20)
    (OUT/'flightpoints_tools.json').write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(json.dumps(output, indent=2, ensure_ascii=False))

asyncio.run(main())
