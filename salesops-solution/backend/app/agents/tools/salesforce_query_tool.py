"""Generic SOQL passthrough for ad-hoc agent queries."""
from __future__ import annotations

from typing import Any

from ...services import salesforce as sf_svc
from ..base import AgentContext, Tool, ToolResult


class SalesforceQueryTool(Tool):
    """Run an arbitrary SOQL query against the active Salesforce connection."""

    name = "salesforce_soql"
    description = "Run an arbitrary SOQL query and return records + totalSize."
    kb_namespaces: list[str] = []

    def invoke(self, ctx: AgentContext, **inputs: Any) -> ToolResult:
        try:
            soql = inputs.get("soql") or ""
            label = inputs.get("label") or ""
            if not soql.strip():
                return ToolResult(name=self.name, ok=False, error="empty soql")

            conn = sf_svc.get_active_connection(ctx.db)
            if not conn:
                return ToolResult(
                    name=self.name,
                    ok=False,
                    error="no_active_salesforce_connection",
                )
            try:
                sf = sf_svc.client_for(conn)
                res = sf.query(soql)
            except Exception as e:
                return ToolResult(
                    name=self.name,
                    ok=False,
                    error=f"soql_failed: {type(e).__name__}: {str(e)[:300]}",
                    data={"label": label, "soql": soql},
                )

            records = [_strip_attrs(r) for r in (res.get("records") or [])]
            return ToolResult(
                name=self.name,
                ok=True,
                data={
                    "label": label,
                    "soql": soql,
                    "records": records,
                    "totalSize": int(res.get("totalSize") or 0),
                    "done": bool(res.get("done", True)),
                },
            )
        except Exception as e:
            return ToolResult(name=self.name, ok=False, error=f"{type(e).__name__}: {str(e)[:300]}")


def _strip_attrs(rec: dict) -> dict:
    if not isinstance(rec, dict):
        return rec
    out = {k: v for k, v in rec.items() if k != "attributes"}
    for k, v in list(out.items()):
        if isinstance(v, dict):
            out[k] = _strip_attrs(v)
    return out
