"""P2 — MCP 2025-11-25 server compliance: version negotiation, output schemas, structuredContent."""

import json

from indaga.interfaces.mcp import PROTOCOL_VERSION, IndagaMCPServer
from indaga.operations import bootstrap
from indaga.operations.model import Context
from indaga.store import Surface
from indaga.store.memory import InMemoryStore


def _server():
    bootstrap.load_all()
    ctx = Context(subject_id="demo", store=InMemoryStore(), surface=Surface.APP)
    return IndagaMCPServer(ctx)


def _call(srv, method, params=None, rid=1):
    return srv.handle({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})["result"]


def test_initialize_advertises_current_version():
    r = _call(_server(), "initialize", {"protocolVersion": "2025-11-25"})
    assert r["protocolVersion"] == "2025-11-25"
    assert "tools" in r["capabilities"]


def test_initialize_negotiates_supported_client_version():
    # echo back a version the client requested when we support it
    r = _call(_server(), "initialize", {"protocolVersion": "2025-06-18"})
    assert r["protocolVersion"] == "2025-06-18"


def test_initialize_falls_back_for_unknown_version():
    r = _call(_server(), "initialize", {"protocolVersion": "1999-01-01"})
    assert r["protocolVersion"] == PROTOCOL_VERSION


def test_tools_list_has_input_and_output_schema():
    tools = _call(_server(), "tools/list")["tools"]
    assert tools
    for t in tools:
        assert "inputSchema" in t
        assert t["outputSchema"]["type"] == "object"
        assert "annotations" in t


def test_tools_call_returns_structured_content():
    r = _call(_server(), "tools/call", {"name": "indaga.list_capabilities", "arguments": {}})
    assert r["isError"] is False
    assert r["structuredContent"] == json.loads(r["content"][0]["text"])
    assert "capabilities" in r["structuredContent"]


def test_tools_call_invalid_params_is_error():
    r = _call(_server(), "tools/call", {"name": "variant.resolve", "arguments": {"rsid": 123}})
    assert r["isError"] is True
    assert r["structuredContent"]["error"] == "invalid_params"
