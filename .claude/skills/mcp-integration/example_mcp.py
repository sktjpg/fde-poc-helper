"""Reference: expose a capability as an MCP server, and consume an MCP tool from our agent.

The agent never sees MCP directly. Each MCP tool we choose to allow is wrapped in a typed
local Tool, so arguments are validated before the call and the response is validated after.
Verified against mcp 2.2:

    uv run python .claude/skills/mcp-integration/example_mcp.py
"""

import asyncio
from typing import Any

from mcp import Client
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError as McpToolError
from pydantic import BaseModel, Field, ValidationError

from app.agents.tools.base import Tool, ToolRegistry
from app.domain.errors import ToolError
from app.domain.models import ToolCall

# --- Server side: transport only. Business logic stays in a plain function. -------------

INVOICES = {"INV-1": {"invoice_id": "INV-1", "status": "paid", "amount": 120.0}}


def find_invoice(invoice_id: str) -> dict[str, Any] | None:
    return INVOICES.get(invoice_id)


server = MCPServer("billing")


@server.tool(description="Status and amount of one invoice, by id.")
def get_invoice(invoice_id: str) -> dict[str, Any]:
    invoice = find_invoice(invoice_id)
    if invoice is None:
        # A deliberate failure: reaches the caller as an is_error result, not a crash.
        raise McpToolError(f"Invoice {invoice_id} not found")
    return invoice


# --- Client side: one allowed MCP tool, wrapped as a typed local Tool. ------------------


class InvoiceArgs(BaseModel):
    invoice_id: str = Field(pattern=r"^INV-\d+$")


class Invoice(BaseModel):
    invoice_id: str
    status: str
    amount: float


def make_invoice_tool(client: Client) -> Tool[InvoiceArgs]:
    async def handler(args: InvoiceArgs) -> Invoice:
        result = await client.call_tool("get_invoice", args.model_dump())
        if result.is_error:
            raise ToolError("Billing could not return that invoice")
        try:
            # MCP output is external data: validate it before the agent relies on it.
            return Invoice.model_validate(result.structured_content)
        except ValidationError as exc:
            raise ToolError("Billing returned an unexpected response") from exc

    return Tool(
        name="get_invoice",
        description="Status and amount of one invoice. Use when the user names an invoice id.",
        args_model=InvoiceArgs,
        handler=handler,
    )


async def main() -> None:
    # In-process connection for the demo. In production pass a URL (Streamable HTTP) or
    # StdioServerParameters instead of the server object.
    async with Client(server) as client:
        listed = await client.list_tools()
        print("server offers:", [tool.name for tool in listed.tools])

        tools = ToolRegistry([make_invoice_tool(client)], timeout_seconds=5.0)
        for arguments in ({"invoice_id": "INV-1"}, {"invoice_id": "INV-404"}, {"invoice_id": "x"}):
            output = await tools.execute(ToolCall(id="c1", name="get_invoice", arguments=arguments))
            print("error " if output.is_error else "ok    ", output.content[:90])


if __name__ == "__main__":
    asyncio.run(main())
