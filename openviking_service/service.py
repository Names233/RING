import json
import math
import os
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


def compute_confidence(
    c0: float, delta_days: float, access_count: int, lam: float = 0.03, alpha: float = 0.05
) -> float:
    return min(1.0, c0 * math.exp(-lam * max(0.0, delta_days)) + alpha * math.log(1 + max(0, access_count)))


def check_write_permission(agent_id: str, uri: str, operation: str = "write") -> tuple[bool, str]:
    if not (isinstance(uri, str) and uri.startswith("viking://")):
        return False, "invalid uri: must start with viking://"

    if operation == "delete" and agent_id != "governance" and (
        uri.startswith("viking://memories/users/") or uri.startswith("viking://memories/shared/")
    ):
        return False, "hard delete forbidden; submit soft-delete request to viking://memories/shared/requests/"

    allowed_prefixes: dict[str, tuple[str, ...]] = {
        "persona": ("viking://memories/agents/maibot/",),
        "maibot": ("viking://memories/agents/maibot/",),
        "airi": ("viking://memories/agents/airi/", "viking://memories/shared/requests/"),
        "dsh": (
            "viking://memories/agents/dsh/",
            "viking://resources/",
            "viking://skills/",
            "viking://memories/shared/requests/",
        ),
        "astrbot": (
            "viking://memories/users/",
            "viking://memories/agents/astrbot/",
            "viking://memories/shared/requests/",
        ),
        "governance": ("viking://",),
    }

    prefixes = allowed_prefixes.get(agent_id)
    if not prefixes:
        return False, f"unauthorized agent: {agent_id}"

    for prefix in prefixes:
        if uri.startswith(prefix):
            return True, "ok"

    return False, f"agent '{agent_id}' is not allowed to write to uri '{uri}'"


class WriteRequest(BaseModel):
    agent_id: str
    uri: str
    content: str
    l0_summary: str | None = None
    l1_summary: str | None = None
    confidence: float = 0.85
    tags: list[str] = Field(default_factory=list)


class RecallRequest(BaseModel):
    agent_id: str
    query: str
    namespaces: list[str] | None = None
    max_level: str = "L1"
    top_k: int = 5


class DeleteRequest(BaseModel):
    agent_id: str
    target_uri: str
    reason: str


def create_app(storage_root: str | Path | None = None) -> FastAPI:
    if storage_root is not None:
        root = Path(storage_root)
    elif os.getenv("OPENVIKING_DATA_DIR"):
        root = Path(os.getenv("OPENVIKING_DATA_DIR"))
    else:
        root = Path(os.getenv("TMP", "/tmp")) / "ring_openviking"

    root.mkdir(parents=True, exist_ok=True)
    records_dir = root / "records"
    records_dir.mkdir(parents=True, exist_ok=True)

    app = FastAPI(title="OpenViking Service")
    index: dict[str, dict[str, Any]] = {}

    # Preload existing records if any
    for record_file in records_dir.glob("*.json"):
        try:
            with open(record_file, "r", encoding="utf-8") as f:
                rec = json.load(f)
                index[rec["uri"]] = rec
        except Exception:
            pass

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "openviking", "storage_root": str(root)}

    @app.post("/write")
    def write_record(req: WriteRequest):
        allowed, reason = check_write_permission(req.agent_id, req.uri, "write")
        if not allowed:
            raise HTTPException(status_code=403, detail=reason)

        now = time.time()
        record_data = {
            "agent_id": req.agent_id,
            "uri": req.uri,
            "content": req.content,
            "l0_summary": req.l0_summary or req.content[:100],
            "l1_summary": req.l1_summary or req.content[:300],
            "confidence": req.confidence,
            "tags": req.tags,
            "created_at": now,
            "updated_at": now,
            "access_count": 0,
        }

        index[req.uri] = record_data
        file_name = f"{abs(hash(req.uri))}_{uuid.uuid4().hex[:8]}.json"
        record_path = records_dir / file_name
        with open(record_path, "w", encoding="utf-8") as f:
            json.dump(record_data, f, ensure_ascii=False, indent=2)

        return {"status": "ok", "uri": req.uri}

    @app.post("/recall")
    def recall_records(req: RecallRequest):
        if req.max_level == "L2" and req.agent_id not in ("dsh", "governance"):
            effective_level = "L1"
        else:
            effective_level = req.max_level

        query_terms = set(req.query.lower().split()) if req.query else set()
        query_chars = set(req.query.lower()) if req.query else set()

        scored = []
        now = time.time()

        for uri, record in index.items():
            if req.namespaces:
                if not any(uri.startswith(ns) for ns in req.namespaces):
                    continue

            # Compute match score based on token / character overlap
            text = f"{record.get('content', '')} {record.get('l0_summary', '')} {record.get('l1_summary', '')}".lower()
            text_tokens = set(text.split())
            text_chars = set(text)

            token_overlap = len(query_terms & text_tokens) / max(1, len(query_terms)) if query_terms else 0.0
            char_overlap = len(query_chars & text_chars) / max(1, len(query_chars)) if query_chars else 0.0
            overlap_score = 0.7 * token_overlap + 0.3 * char_overlap

            # Compute dynamic confidence
            created_at = record.get("created_at", now)
            delta_days = max(0.0, (now - created_at) / 86400.0)
            access_count = record.get("access_count", 0)
            c0 = record.get("confidence", 0.85)
            conf = compute_confidence(c0, delta_days, access_count)

            total_score = overlap_score + 0.5 * conf

            record["access_count"] = access_count + 1

            if effective_level == "L0":
                summary_text = record.get("l0_summary") or record.get("content", "")[:100]
            elif effective_level == "L1":
                summary_text = record.get("l1_summary") or record.get("content", "")[:300]
            else:
                summary_text = record.get("content", "")

            scored.append({
                "uri": record["uri"],
                "level": effective_level,
                "summary": summary_text,
                "score": round(total_score, 4),
            })

        scored.sort(key=lambda x: x["score"], reverse=True)
        return {
            "fragments": scored[: req.top_k],
            "effective_level": effective_level,
        }

    @app.post("/delete-request")
    def create_delete_request(req: DeleteRequest):
        req_id = uuid.uuid4().hex
        req_uri = f"viking://memories/shared/requests/{req_id}"

        data = {
            "agent_id": req.agent_id,
            "target_uri": req.target_uri,
            "reason": req.reason,
            "created_at": time.time(),
        }

        req_file = records_dir / f"del_req_{req_id}.json"
        with open(req_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return {"status": "queued", "request_uri": req_uri}

    return app


app = create_app()
