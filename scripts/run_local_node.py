import asyncio
import os
from pathlib import Path
import sys
import uuid

REPO_ROOT = Path(__file__).resolve().parents[1]
ACP_BRIDGE_DIR = REPO_ROOT / "acp-bridge"
sys.path.extend([str(REPO_ROOT), str(ACP_BRIDGE_DIR)])

import httpx
import uvicorn

import airi_embodiment.service
import digital_genesis_acp_bridge.acp_server
import digital_genesis_acp_bridge.main


async def heartbeat_and_drain_loop(
    cloud_router_url: str,
    acp_bridge_port: int,
    airi_port: int,
    interval: float,
) -> None:
    await asyncio.sleep(1.0)
    token = os.environ.get("HEARTBEAT_SECRET_TOKEN")
    headers = {"X-Heartbeat-Token": token} if token else {}
    seq = 0

    async with httpx.AsyncClient(timeout=20.0) as client:
        while True:
            try:
                mode_resp = await client.get(f"{cloud_router_url}/mode", headers=headers)
                cur_seq = 0
                if mode_resp.status_code == 200:
                    try:
                        cur_seq = int(mode_resp.json().get("last_seq", 0))
                    except Exception:
                        cur_seq = 0
                seq = max(seq + 1, cur_seq + 1)

                heartbeat_payload = {
                    "status": "online",
                    "seq": seq,
                    "nonce": str(uuid.uuid4()),
                    "capabilities": ["dsh", "airi", "acp-bridge"],
                    "endpoints": {
                        "acp_bridge": f"http://127.0.0.1:{acp_bridge_port}",
                        "airi": f"http://127.0.0.1:{airi_port}",
                    },
                }
                await client.post(
                    f"{cloud_router_url}/heartbeat",
                    json=heartbeat_payload,
                    headers=headers,
                )

                tasks_resp = await client.get(
                    f"{cloud_router_url}/tasks/pending",
                    headers=headers,
                )
                if tasks_resp.status_code == 200:
                    raw_data = tasks_resp.json()
                    pending_tasks = (
                        raw_data.get("tasks", [])
                        if isinstance(raw_data, dict)
                        else raw_data
                    )
                    for task in pending_tasks:
                        task_id = task["task_id"]
                        send_payload = {
                            "jsonrpc": "2.0",
                            "id": task_id,
                            "method": "message/send",
                            "params": {
                                "message": {
                                    "role": "user",
                                    "parts": [
                                        {
                                            "type": "text",
                                            "text": task.get("text", ""),
                                        }
                                    ],
                                }
                            },
                        }
                        send_resp = await client.post(
                            f"http://127.0.0.1:{acp_bridge_port}/",
                            json=send_payload,
                        )
                        result_data = (
                            send_resp.json()
                            if send_resp.headers.get("content-type", "").startswith("application/json")
                            else {"text": send_resp.text}
                        )
                        await client.post(
                            f"{cloud_router_url}/tasks/{task_id}/complete",
                            json={"result": result_data},
                            headers=headers,
                        )
            except Exception as e:
                # Log or ignore errors in loop to keep heartbeat running
                pass

            await asyncio.sleep(interval)


async def main() -> None:
    acp_bridge_port = int(os.environ.get("ACP_BRIDGE_PORT", "18090"))
    acp_server_port = int(os.environ.get("ACP_SERVER_PORT", "18091"))
    airi_port = int(os.environ.get("AIRI_PORT", "18092"))
    cloud_router_url = os.environ.get(
        "CLOUD_ROUTER_URL", "http://127.0.0.1:18082"
    ).rstrip("/")
    interval = float(os.environ.get("HEARTBEAT_INTERVAL_SECONDS", "5.0"))

    os.environ["ACP_ENDPOINT"] = f"http://127.0.0.1:{acp_server_port}"

    acp_server_app = digital_genesis_acp_bridge.acp_server.create_acp_server()
    bridge_app = digital_genesis_acp_bridge.main.app
    airi_app = airi_embodiment.service.create_app()

    server1 = uvicorn.Server(
        uvicorn.Config(acp_server_app, host="127.0.0.1", port=acp_server_port, log_level="warning")
    )
    server2 = uvicorn.Server(
        uvicorn.Config(bridge_app, host="127.0.0.1", port=acp_bridge_port, log_level="warning")
    )
    server3 = uvicorn.Server(
        uvicorn.Config(airi_app, host="127.0.0.1", port=airi_port, log_level="warning")
    )

    servers = [server1, server2, server3]

    await asyncio.gather(
        *(s.serve() for s in servers),
        heartbeat_and_drain_loop(
            cloud_router_url, acp_bridge_port, airi_port, interval
        ),
    )


if __name__ == "__main__":
    asyncio.run(main())
