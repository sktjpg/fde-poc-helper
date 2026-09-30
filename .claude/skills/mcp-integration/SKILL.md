---
name: mcp-integration
description: How to work with the Model Context Protocol in this codebase - exposing a capability as an MCP server, and letting the agent use tools from an MCP server safely. Use when a requirement mentions MCP, connecting to an existing MCP server, exposing internal tools to other agents or assistants, or choosing between an MCP tool and a plain function tool.
---

# MCP integration

The `mcp` Python SDK (2.x) is installed in the `extras` group; the skeleton does not depend
on it. Note that 2.x renamed the server class: `from mcp.server.mcpserver import MCPServer`
(the 1.x `FastMCP` import no longer exists), and the high-level client is `mcp.Client`.

## When MCP is the right answer

- The capability must be reusable by several clients (other agents, IDE assistants, a
  desktop assistant), not just this service: expose an MCP server.
- The customer already has MCP servers for their systems: consume them.
- The tool is used only by this agent, in this process: a plain typed `Tool` in
  `app/agents/tools/` is simpler. MCP adds a process boundary, a protocol and a failure
  mode; do not add it for its own sake.

## Reference implementation (verified, runnable)

`example_mcp.py` shows both directions in one file:

    uv run python .claude/skills/mcp-integration/example_mcp.py

- Server: an `MCPServer` with one `@server.tool`. The decorated function only adapts; the
  logic lives in a plain function that is testable without MCP.
- Client: one MCP tool wrapped as a typed local `Tool`, registered in our `ToolRegistry`.

## Consuming an MCP server: the rules

An MCP tool is an explicit capability boundary and its output is external data.

1. Allowlist. Do not hand the agent everything `list_tools()` returns. Wrap each tool you
   decide to allow; a server can add or change tools without telling you.
2. Typed arguments. The wrapper's `args_model` is ours, as tight as the use case needs,
   validated by `ToolRegistry` before anything is sent.
3. Validated results. Parse `result.structured_content` into a Pydantic model. Treat
   `result.is_error` and a validation failure as a `ToolError` with a safe message.
4. Untrusted text. Tool descriptions and results from a server we do not control can carry
   instructions. They go through the same content filter as any tool output, and they never
   reach the system prompt.
5. Timeouts and failure. The registry timeout applies; also set `read_timeout_seconds` on
   the client. A dead server must produce an error result, not a hung request.
6. Least privilege. Know what each tool can do on the other side and which credentials the
   server runs with. Side-effecting tools need the same approval gate as local ones.

Where it goes in the app: a port in `domain/ports.py` if the core needs the capability, the
MCP client in `adapters/mcp/`, the wrapped tools built in `dependencies.py`. The client
connection is opened in the FastAPI `lifespan` and closed there.

Transports: pass a URL for Streamable HTTP (remote servers), `StdioServerParameters` to
launch a local server as a subprocess, or the server object itself for in-process tests.

## Exposing an MCP server: the rules

- Transport code stays thin. Business logic is in services or plain functions, reused by
  the HTTP API and the MCP server alike.
- Deliberate failures raise the SDK's `ToolError`; they reach the caller as an error
  result. Anything else is reported as a generic crash and the detail stays in our logs.
- Validate inputs even though the caller is "just an agent".
- Tool names and descriptions are the interface: say what the tool does, when to use it
  and what it returns.
- Remote servers need authentication and per-caller authorisation. Stdio servers inherit
  the permissions of whoever launches them.
- `server.run()` defaults to stdio; `server.run("streamable-http")` for a network server.

## Testing

Connect the client to the server object in-process (`Client(server)`), as the example
does. No subprocess and no network, so it runs in the normal test suite.

## What to say aloud

"I treat the MCP server as an external dependency: I allowlist the tools I need, wrap each
one with my own typed arguments, and validate what comes back before the agent uses it."
