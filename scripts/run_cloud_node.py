import asyncio
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ACP_BRIDGE_DIR = REPO_ROOT / "acp-bridge"
sys.path.extend([str(REPO_ROOT), str(ACP_BRIDGE_DIR)])

import uvicorn
import ring_router.service
import openviking_service.service
import persona_plan_b.service


async def main() -> None:
    openviking_data_dir = os.environ.get(
        "OPENVIKING_DATA_DIR", "/opt/ring/data/openviking"
    )
    openviking_port = int(os.environ.get("OPENVIKING_PORT", "18080"))
    persona_port = int(os.environ.get("PERSONA_PORT", "18081"))
    router_port = int(os.environ.get("ROUTER_PORT", "18082"))

    os.environ.setdefault("OPENVIKING_URL", f"http://127.0.0.1:{openviking_port}")
    os.environ.setdefault("PERSONA_PROVIDER_URL", f"http://127.0.0.1:{persona_port}")
    os.environ.setdefault("ACP_BRIDGE_URL", "http://127.0.0.1:18090")
    os.environ.setdefault("AIRI_EMBODIMENT_URL", "http://127.0.0.1:18092")

    openviking_app = openviking_service.service.create_app(
        storage_root=openviking_data_dir
    )
    persona_app = persona_plan_b.service.create_app()
    router_app = ring_router.service.create_app(
        secret_token=os.environ.get("HEARTBEAT_SECRET_TOKEN")
    )

    ov_config = uvicorn.Config(openviking_app, host="127.0.0.1", port=openviking_port, log_level="info")
    persona_config = uvicorn.Config(persona_app, host="127.0.0.1", port=persona_port, log_level="info")
    router_config = uvicorn.Config(router_app, host="127.0.0.1", port=router_port, log_level="info")

    ov_server = uvicorn.Server(ov_config)
    persona_server = uvicorn.Server(persona_config)
    router_server = uvicorn.Server(router_config)

    await asyncio.gather(
        ov_server.serve(),
        persona_server.serve(),
        router_server.serve(),
    )


if __name__ == "__main__":
    asyncio.run(main())
