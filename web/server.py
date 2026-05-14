import json
import logging
from pathlib import Path
from typing import Callable

logger = logging.getLogger("web")

try:
    from aiohttp import web
except ImportError:
    web = None

HERE = Path(__file__).parent
TEMPLATE_PATH = HERE / "templates" / "index.html"


async def start_web_server(orch, voice, router, cmd_handler: Callable):
    if web is None:
        logger.warning("aiohttp not installed — web server disabled. pip install aiohttp")
        return

    app = web.Application()

    async def handle_query(request):
        try:
            data = await request.json()
            message = data.get("message", "")
            agent = data.get("agent", "jarvis")
            channel = data.get("channel", "web")
        except Exception:
            return web.json_response({"error": "invalid json"}, status=400)
        result = await orch.route(agent, message, channel=channel)
        text = result.text
        if result.escalated_to and result.specialized:
            text += f"\n\n[Escalated to {result.escalated_to}]: {result.specialized}"
        return web.json_response({"response": text, "agent": agent})

    async def handle_voice(request):
        data = await request.post()
        audio_data = data.get("audio")
        if not audio_data:
            return web.json_response({"error": "no audio"}, status=400)
        audio_bytes = audio_data.file.read()
        import numpy as np
        audio_array = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        text = voice.stt.transcribe(audio_array)
        if not text:
            return web.json_response({"text": ""})
        result = await cmd_handler(text)
        return web.json_response(result)

    async def handle_agents(request):
        agents = orch.get_agent_list()
        return web.json_response({"agents": agents})

    async def handle_plugins(request):
        plugins = orch.plugin_manager.list_plugins()
        return web.json_response({"plugins": plugins})

    async def handle_index(request):
        try:
            html = TEMPLATE_PATH.read_text()
        except FileNotFoundError:
            html = "<h1>Template not found</h1>"
        return web.Response(text=html, content_type="text/html")

    app.router.add_get("/", handle_index)
    app.router.add_post("/api/query", handle_query)
    app.router.add_post("/api/voice", handle_voice)
    app.router.add_get("/api/agents", handle_agents)
    app.router.add_get("/api/plugins", handle_plugins)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8765)
    await site.start()
    logger.info("Web UI: http://localhost:8765")
