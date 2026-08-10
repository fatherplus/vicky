"""MCP 协议层——stdlib JSON-RPC 2.0 over HTTP（stateless 形态）。

MCP streamable HTTP 的简化实现：POST /mcp 单请求单响应，无会话、无批处理、无 SSE 流。
规范要点（MCP 2024-11-05 / JSON-RPC 2.0）：
  - 请求:  {"jsonrpc":"2.0","method":...,"params":?,"id":?}
  - 响应:  {"jsonrpc":"2.0","result":...,"id":...}  或 {"jsonrpc":"2.0","error":{...},"id":...}
  - 通知:  无 id 的请求——服务端执行但不回响应体（web 层回 HTTP 202 空体）
  - 错误码: -32700 解析错误 / -32600 非法请求 / -32601 方法不存在 / -32602 参数非法 / -32603 内部错误

工具注册（P2 起使用）：
    router.tool_schemas["search_knowledge"] = {
        "name": "search_knowledge", "description": "...",
        "inputSchema": {"type": "object", "properties": {...}, "required": [...]}}
    router.register("search_knowledge", handler)   # handler(params) -> result dict

仅依赖 stdlib json，无第三方依赖。
"""

import json

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "vicky"
SERVER_VERSION = "0.1.0"

# JSON-RPC 2.0 标准错误码
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class RPCError(Exception):
    """JSON-RPC 错误：code/message 会进响应 error 对象。"""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class MCPRouter:
    """JSON-RPC 2.0 分发器。

    - register(name, handler): 注册 JSON-RPC 方法 / 工具执行器，handler(params) -> dict
    - dispatch(method, params): 核心分发，返回 result dict；失败抛 RPCError
    - handle_request(method, params, id): 完整信封，返回响应 dict；通知返回 None
    - tool_schemas: 工具注册表，key=工具名，value={name, description, inputSchema}
    """

    def __init__(self):
        self._handlers = {}
        self.tool_schemas = {}

    def register(self, name: str, handler):
        """注册方法处理器：handler(params) -> dict（即响应的 result）。"""
        self._handlers[name] = handler

    def dispatch(self, method, params):
        """核心分发：method -> result dict。错误抛 RPCError，由调用方组装信封。"""
        if method == "initialize":
            return {
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "capabilities": {"tools": {}},
                "protocolVersion": PROTOCOL_VERSION,
            }
        if method == "tools/list":
            return {"tools": list(self.tool_schemas.values())}
        if method == "tools/call":
            return self._call_tool(params)
        if method == "ping":
            return {}
        handler = self._handlers.get(method)
        if handler is None:
            raise RPCError(METHOD_NOT_FOUND, f"Method not found: {method}")
        try:
            return handler(params or {})
        except RPCError:
            raise
        except Exception as e:
            raise RPCError(INTERNAL_ERROR, str(e) or "Internal error") from e

    def _call_tool(self, params):
        """tools/call：按 name 分发到已注册的 tool handler（当前注册表为空，P2 填充）。"""
        params = params or {}
        name = params.get("name")
        if not isinstance(name, str) or not name:
            raise RPCError(INVALID_PARAMS, "tools/call 需要 name 参数")
        if name not in self.tool_schemas:
            raise RPCError(INVALID_PARAMS, f"Unknown tool: {name}")
        handler = self._handlers.get(name)
        if handler is None:
            raise RPCError(INTERNAL_ERROR, f"Tool '{name}' 已登记 schema 但未注册 handler")
        result = handler(params.get("arguments") or {})
        return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}

    def handle_request(self, method, params, request_id):
        """完整 JSON-RPC 信封。

        返回响应 dict（result 或 error 二选一）；通知（request_id is None）返回 None——
        服务端对通知永不回响应（JSON-RPC 2.0 §2.2）。
        """
        if request_id is None:
            try:
                self.dispatch(method, params)
            except RPCError:
                pass
            except Exception:
                pass
            return None
        try:
            result = self.dispatch(method, params)
            return {"jsonrpc": "2.0", "result": result, "id": request_id}
        except RPCError as e:
            return {"jsonrpc": "2.0",
                    "error": {"code": e.code, "message": e.message},
                    "id": request_id}
        except Exception as e:
            return {"jsonrpc": "2.0",
                    "error": {"code": INTERNAL_ERROR, "message": str(e) or "Internal error"},
                    "id": request_id}


# 模块级单例：web 层与测试共用同一个路由实例（工具注册在启动期/导入期完成）
router = MCPRouter()
