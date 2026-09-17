"""Run in the separate MCP environment; exercise the real MCP protocol, no providers."""
import json

import anyio
import httpx
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from reelforge_mcp import BearerAuth, ReelForgeClient, create_server


ACTION = "act_" + "a" * 32


def test_protocol_discovery_and_all_tools_use_existing_api():
    calls = []
    def upstream(request):
        calls.append(request)
        path = request.url.path
        if path == "/api/agent/capabilities":
            result = {"duration_sec": {"max": 300}}
        elif path == "/api/agent/actions":
            assert json.loads(request.content)["duration_sec"] == 300
            result = {"action_id": ACTION, "claim_token": "never-send-to-model", "status": "pending"}
        elif path.endswith("/artifacts"):
            result = {"artifacts": [{"kind": "video", "path": "/api/finished/job/artifact/video"}]}
        elif path.endswith("/dispatch"):
            result = {"job_id": "job", "status": "queued"}
        else:
            result = {"job_id": "job", "status": "rendering"}
        return httpx.Response(200, json=result)
    adapter = ReelForgeClient("https://studio.example", "r" * 48, httpx.MockTransport(upstream))
    server = create_server(adapter)
    async def run():
        async with create_connected_server_and_client_session(server) as session:
            discovered = await session.list_tools()
            assert {tool.name for tool in discovered.tools} == {
                "get_video_capabilities", "propose_video", "get_video_status",
                "get_video_diagnostics", "resume_video", "get_video_artifacts"}
            for name, args in [
                ("get_video_capabilities", {}),
                ("propose_video", {"topic": "Stoats", "duration_sec": 300, "cost_ceiling_usd": 10}),
                ("get_video_status", {"action_id": ACTION, "after": 17}),
                ("get_video_diagnostics", {"action_id": ACTION, "artifact": "script", "offset": 24000}),
                ("resume_video", {"action_id": ACTION}),
                ("get_video_artifacts", {"action_id": ACTION}),
            ]:
                response = await session.call_tool(name, args)
                assert not response.isError, response
                assert "never-send-to-model" not in response.model_dump_json()
                if name == "propose_video":
                    assert "approval_url" in response.model_dump_json()
            for args in [{"action_id": "../approve"}, {"action_id": ACTION, "after": -1}]:
                assert (await session.call_tool("get_video_status", args)).isError
            assert (await session.call_tool("get_video_diagnostics", {
                "action_id": ACTION, "artifact": "../../.env"})).isError
    anyio.run(run)
    assert len(calls) == 6
    assert calls[2].url.params["after"] == "17"
    assert calls[3].url.params["offset"] == "24000"
    assert calls[3].headers["authorization"] == "Bearer " + "r" * 48
    assert calls[4].headers["authorization"] == "Bearer " + ACTION
    assert not calls[0].headers.get("authorization")
    assert all(not call.url.path.endswith(("/approve", "/execute")) for call in calls)


def test_upstream_failure_is_tool_error_without_retry_or_credential_leak():
    calls = []
    def reject(request):
        calls.append(request)
        return httpx.Response(409, json={"detail": "SECRET-UPSTREAM-INTERNAL"})
    server = create_server(ReelForgeClient("https://studio.example", transport=httpx.MockTransport(reject)))
    async def run():
        async with create_connected_server_and_client_session(server) as session:
            result = await session.call_tool("resume_video", {"action_id": ACTION})
            assert result.isError
            assert "409" in result.model_dump_json()
            assert "SECRET-UPSTREAM" not in result.model_dump_json()
    anyio.run(run)
    assert len(calls) == 1


def test_streamable_http_auth_and_protocol():
    token = "m" * 48
    server = create_server(ReelForgeClient("https://studio.example", transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"duration_sec": {"max": 300}}))))
    inner = server.streamable_http_app()
    app = BearerAuth(inner, token)
    async def run():
        async with inner.router.lifespan_context(inner):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as client:
                body = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                    "protocolVersion": "2025-03-26", "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"}}}
                assert (await client.post("/mcp", json=body)).status_code == 401
                headers = {"Authorization": "Bearer " + token,
                           "Accept": "application/json, text/event-stream"}
                response = await client.post("/mcp", json=body, headers=headers)
                assert response.status_code == 200, response.text
                assert response.json()["result"]["serverInfo"]["name"] == "ReelForge"
                result = await client.post("/mcp", headers=headers, json={
                    "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {"name": "get_video_capabilities", "arguments": {}}})
                assert result.status_code == 200, result.text
                assert not result.json()["result"].get("isError")
                bad_origin = await client.post("/mcp", json=body,
                    headers={**headers, "Origin": "https://evil.example"})
                assert bad_origin.status_code == 403
    anyio.run(run)
    with pytest.raises(ValueError):
        BearerAuth(inner, "")


@pytest.mark.parametrize("origin", ["http://public.example", "https://user:pass@example.com",
                                      "https://example.com/path", "https://example.com?token=secret"])
def test_upstream_origin_rejects_unsafe_configuration(origin):
    with pytest.raises(ValueError):
        ReelForgeClient(origin)
