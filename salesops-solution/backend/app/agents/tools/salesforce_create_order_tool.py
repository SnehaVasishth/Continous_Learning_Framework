"""Create a Salesforce Order via the existing service helper."""
from __future__ import annotations

from typing import Any

from ...services import salesforce as sf_svc
from ...services import salesforce_orders as sf_orders
from ..base import AgentContext, Tool, ToolResult


class SalesforceCreateOrderTool(Tool):
    """Create a Salesforce Order (Draft for L3 staging, Activated for L4 auto)."""

    name = "salesforce_create_order"
    description = "Create a Salesforce Order with line items via the active connection."
    kb_namespaces: list[str] = []

    def invoke(self, ctx: AgentContext, **inputs: Any) -> ToolResult:
        try:
            account_id = inputs.get("account_id")
            extracted = inputs.get("extracted")
            intent = inputs.get("intent") or "po_intake"
            order_status = inputs.get("order_status") or "Draft"

            if not account_id:
                return ToolResult(name=self.name, ok=False, error="missing account_id")
            if not isinstance(extracted, dict):
                return ToolResult(name=self.name, ok=False, error="missing or invalid extracted dict")
            if order_status not in ("Draft", "Activated"):
                return ToolResult(
                    name=self.name,
                    ok=False,
                    error=f"invalid order_status '{order_status}' — must be Draft or Activated",
                )

            conn = sf_svc.get_active_connection(ctx.db)
            if not conn:
                return ToolResult(name=self.name, ok=False, error="no_active_salesforce_connection")

            try:
                result = sf_orders.create_order_for_account(
                    conn,
                    account_id=account_id,
                    extracted=extracted,
                    intent=intent,
                    order_status=order_status,
                )
            except Exception as e:
                return ToolResult(
                    name=self.name,
                    ok=False,
                    error=f"create_order_failed: {type(e).__name__}: {str(e)[:300]}",
                )

            if not result.get("applied"):
                return ToolResult(
                    name=self.name,
                    ok=False,
                    error=result.get("reason") or "create_order_returned_not_applied",
                    data=result,
                )

            notes: list[str] = []
            if result.get("activation_error"):
                notes.append(f"activation_error: {result['activation_error']}")
            if result.get("line_items_skipped"):
                notes.append(f"skipped {len(result['line_items_skipped'])} line(s) (missing PricebookEntry)")
            return ToolResult(name=self.name, ok=True, data=result, notes=notes)
        except Exception as e:
            return ToolResult(name=self.name, ok=False, error=f"{type(e).__name__}: {str(e)[:300]}")
