import asyncio
import os
import uvicorn

from backend.app import app


def create_server():
    host = os.getenv("WEBAPP_HOST", "0.0.0.0")
    port = int(os.getenv("WEBAPP_PORT", "8000"))
    config = uvicorn.Config(app, host=host, port=port, loop="asyncio", log_level="info")
    return uvicorn.Server(config)


async def start_fastapi_server():
    server = create_server()
    task = asyncio.create_task(server.serve())
    return server, task


async def stop_fastapi_server(server, task):
    if server:
        server.should_exit = True
    if task:
        await task
