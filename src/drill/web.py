"""Local HTTP API and UI. Binds to localhost and refuses cross-site requests."""
import json
import logging
from pathlib import Path

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse
from starlette.routing import Route

from . import agents, insights
from .coordinator import ROOT
from .errors import DrillError
from .operator import TOOLS
from .security import mask

MAX_BODY = 10_000
STATUS = {"MODEL_BUDGET": 429, "MODEL_FAILED": 502, "NOT_FOUND": 404, "VERSION_CONFLICT": 409, "NOT_ALLOWED": 409, "STALE_APPROVAL": 409}
HEADERS = {
    "content-security-policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                               "frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    "x-content-type-options": "nosniff", "referrer-policy": "no-referrer", "cache-control": "no-store",
}
log = logging.getLogger("drill.web")


def _refused(status, code, message, details=None):
    return JSONResponse(DrillError(code, message, details).to_dict(), status_code=status, headers=HEADERS)


class LocalOnly(BaseHTTPMiddleware):
    """Without this, any web page open in the same browser could POST an approval to localhost."""

    def __init__(self, app, port):
        super().__init__(app)
        self.hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    async def dispatch(self, request, call_next):
        host = request.headers.get("host", "")
        if host not in self.hosts:
            return _refused(403, "FORBIDDEN", "Unexpected Host header.")
        if request.method not in ("GET", "HEAD"):
            origin = request.headers.get("origin")
            if origin is not None and origin != f"http://{host}":
                return _refused(403, "FORBIDDEN", "Cross-origin requests are not allowed.")
            if request.url.path.startswith("/api/") and not request.headers.get(
                    "content-type", "").startswith("application/json"):
                return _refused(415, "INVALID_INPUT", "Content-Type must be application/json.")
            if len(await request.body()) > MAX_BODY:
                return _refused(413, "INVALID_INPUT", "Request body too large.")
        response = await call_next(request)
        response.headers.update(HEADERS)
        return response


async def _body(request):
    try:
        data = json.loads(await request.body())
    except (ValueError, UnicodeDecodeError) as exc:
        raise DrillError("INVALID_INPUT", "Body is not valid JSON.") from exc
    if not isinstance(data, dict):
        raise DrillError("INVALID_INPUT", "Body must be a JSON object.")
    return data


def api_routes(coord):
    def guarded(handler):
        async def endpoint(request):
            try:
                result = await handler(request)
                return result if hasattr(result, "status_code") else JSONResponse(result)
            except DrillError as exc:
                return JSONResponse(exc.to_dict(), status_code=STATUS.get(exc.code, 400))
            except Exception:
                log.exception("request failed")
                return _refused(500, "INTERNAL", "Unexpected error. See the server log.")
        return endpoint

    async def meta(_):
        config = agents.provider()
        keys = ("scenario_id", "title", "description", "expected_outcome", "application", "lag_threshold_seconds")
        return {"model": {"configured": bool(config), "provider": config and config["name"],
                          "model": config and config["model"]},
                "scenarios": [{k: s[k] for k in keys} for s in coord.operator.list_scenarios()],
                "knowledge": coord.knowledge.catalogue(coord.clock()), "tools": TOOLS}

    async def drills(request):
        if request.method == "GET":
            return {"drills": coord.store.list_drills()}
        data = await _body(request)
        allowed = {"scenario_id", "coordinator", "application", "runbook_id", "runbook_version", "participants", "scope"}
        if set(data) - allowed or not {"scenario_id", "coordinator"} <= set(data):
            raise DrillError("INVALID_INPUT", "Expected scenario_id and coordinator.")
        if not isinstance(data.get("participants") or [], list):
            raise DrillError("INVALID_INPUT", "participants must be a list.")
        return coord.create(**data)

    async def drill(request):
        return coord.view(request.path_params["drill_id"])

    async def command(request):
        data = await _body(request)
        name, version, args = data.get("command"), data.get("expected_version"), data.get("args", {})
        if not isinstance(name, str) or type(version) is not int or not isinstance(args, dict):
            raise DrillError("INVALID_INPUT", "Expected command, integer expected_version and object args.")
        if {"w", "drill_id", "command", "expected_version"} & set(args):
            raise DrillError("INVALID_INPUT", "Reserved argument name.")
        return coord.command(request.path_params["drill_id"], name, expected_version=version, **args)

    async def chat(request):
        drill_id, text = request.path_params["drill_id"], (await _body(request)).get("text")
        if not isinstance(text, str):
            raise DrillError("INVALID_INPUT", "Expected text.")
        result = coord.handle_text(drill_id, text)
        result.update(answered_by="deterministic coordinator", model_error=None)
        if result["intent"] == "question":
            result["answered_by"] = "approved-source search"
            if agents.provider():
                try:
                    model = await agents.answer(coord, drill_id, text)
                    result.update(reply=model["reply"], guard=model["guard"], answered_by=model["model"],
                                  view=coord.view(drill_id))
                except Exception as exc:  # the drill must keep working without the model
                    log.warning("model call failed: %s", type(exc).__name__)
                    result["model_error"] = f"Model call failed ({type(exc).__name__}). Showing approved sources."
        result["reply"] = mask(result["reply"])
        return result

    async def report(request):
        return coord.report(request.path_params["drill_id"])

    async def report_md(request):
        drill_id = request.path_params["drill_id"]
        return PlainTextResponse(coord.report_markdown(drill_id), media_type="text/markdown; charset=utf-8",
                                 headers={"content-disposition": f'attachment; filename="{drill_id}-report.md"'})

    async def brief(request):
        await _body(request)
        return await insights.brief(coord, request.path_params["drill_id"])

    async def analysis(request):
        drill_id = request.path_params["drill_id"]
        if request.method == "GET":
            coord.view(drill_id)
            return {"analysis": insights.latest_analysis(coord, drill_id)}
        await _body(request)
        return {"analysis": await insights.analyse(coord, drill_id)}

    async def interpret(request):
        return await insights.interpret(coord, (await _body(request)).get("text"))

    async def spans(request):
        drill_id = request.path_params["drill_id"]
        coord.view(drill_id)
        return {"spans": coord.store.get_spans(drill_id)}

    async def evaluation(_):
        def load(name):
            path = ROOT / "docs" / "evidence" / name
            return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
        return {**(load("evaluation.json") or {"available": False}), "model_eval": load("model_evaluation.json")}

    def static(name):
        async def serve(_):
            return FileResponse(ROOT / "src" / "web" / name)
        return Route("/" if name == "index.html" else f"/{name}", serve)

    return [
        static("index.html"), static("app.js"), static("style.css"),
        Route("/api/meta", guarded(meta)),
        Route("/api/drills", guarded(drills), methods=["GET", "POST"]),
        Route("/api/drills/{drill_id}", guarded(drill)),
        Route("/api/drills/{drill_id}/commands", guarded(command), methods=["POST"]),
        Route("/api/drills/{drill_id}/chat", guarded(chat), methods=["POST"]),
        Route("/api/drills/{drill_id}/report", guarded(report)),
        Route("/api/drills/{drill_id}/report.md", guarded(report_md)),
        Route("/api/drills/{drill_id}/spans", guarded(spans)),
        Route("/api/drills/{drill_id}/brief", guarded(brief), methods=["POST"]),
        Route("/api/drills/{drill_id}/analysis", guarded(analysis), methods=["GET", "POST"]),
        Route("/api/interpret", guarded(interpret), methods=["POST"]),
        Route("/api/evaluation", guarded(evaluation)),
    ]


def create_app(coord, port):
    return Starlette(routes=api_routes(coord), middleware=[Middleware(LocalOnly, port=port)])


def create_hosted_server(coord, port):
    """Foundry Responses host (POST /responses) with the drill UI and API on the same port."""
    from agent_framework_foundry_hosting import ResponsesHostServer

    server = ResponsesHostServer(agents.build_coordinator_agent(coord))
    server.router.routes[:0] = api_routes(coord)
    server.add_middleware(LocalOnly, port=port)
    return server
