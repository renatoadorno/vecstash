from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any


@dataclass(frozen=True)
class JsonRpcRequest:
    id: str | int | None
    method: str
    params: dict[str, Any]


def parse_jsonrpc_line(raw: str) -> JsonRpcRequest:
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise ValueError("JSON-RPC payload must be an object.")
    if obj.get("jsonrpc") != "2.0":
        raise ValueError("jsonrpc field must be '2.0'.")

    method = obj.get("method")
    if not isinstance(method, str) or not method:
        raise ValueError("method must be a non-empty string.")

    params = obj.get("params", {})
    if not isinstance(params, dict):
        raise ValueError("params must be an object.")

    req_id = obj.get("id")
    return JsonRpcRequest(id=req_id, method=method, params=params)


def jsonrpc_result(req_id: str | int | None, result: dict[str, Any]) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result})


def jsonrpc_error(req_id: str | int | None, code: int, message: str) -> str:
    return json.dumps(
        {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}
    )
