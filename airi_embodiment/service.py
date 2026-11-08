from typing import Any
from fastapi import FastAPI, Request
from .core import (
    build_a2a_response,
    build_motion_completed_event,
    parse_a2a_request,
    plan_embodiment,
)


def create_app(
    available_motions: set[str] | None = None,
    available_expressions: set[str] | None = None,
) -> FastAPI:
    app = FastAPI(title="AIRI Embodiment Service")
    app.state.events = []

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "airi-embodiment",
            "events_emitted": len(app.state.events),
        }

    @app.get("/events")
    async def get_events() -> dict[str, Any]:
        return {"events": app.state.events}

    @app.post("/")
    @app.post("/a2a")
    async def handle_a2a(request: Request) -> dict[str, Any]:
        req = await request.json()
        parsed = parse_a2a_request(req)
        params = req.get("params") or {}
        emotion = (
            str(params["emotion"])
            if (parsed["emotion"] == "neutral" and params.get("emotion"))
            else parsed["emotion"]
        )
        requested_action = (
            parsed["requested_action"]
            or params.get("requested_action")
            or params.get("action")
        )
        plan = plan_embodiment(
            emotion,
            requested_action=requested_action,
            voice=parsed["voice"],
            available_motions=available_motions,
            available_expressions=available_expressions,
        )
        task_id = f"airi-{req.get('id', '1')}"
        trace_id = str(parsed.get("trace_id") or req.get("id", "trace-1"))
        event = build_motion_completed_event(
            trace_id=trace_id, task_id=task_id, plan=plan
        )
        app.state.events.append(event)
        return build_a2a_response(
            request_id=req.get("id", "1"), task_id=task_id, plan=plan
        )

    return app


app = create_app()
