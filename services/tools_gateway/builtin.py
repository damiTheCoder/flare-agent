"""内置工具集（挂到 ToolRegistry）。"""

from __future__ import annotations

from sandbox.sandbox_tools import build_sandbox_run_tool
from tools_gateway.accounting.assets import register_asset_tools
from tools_gateway.accounting.audit import register_audit_tools
from tools_gateway.accounting.banking import register_banking_tools
from tools_gateway.accounting.budgets import register_budget_tools
from tools_gateway.accounting.documents import register_document_tools
from tools_gateway.accounting.expenses import register_expense_tools
from tools_gateway.accounting.finance import register_finance_tools
from tools_gateway.accounting.integrations import register_integration_tools
from tools_gateway.accounting.inventory import register_inventory_tools
from tools_gateway.accounting.ledger import register_ledger_tools
from tools_gateway.accounting.payroll import register_payroll_tools
from tools_gateway.accounting.profile import register_profile_tools
from tools_gateway.accounting.projects import register_project_tools
from tools_gateway.accounting.purchases import register_purchases_tools
from tools_gateway.accounting.sales import register_sales_tools
from tools_gateway.accounting.tax import register_tax_tools
from tools_gateway.accounting.usage import register_usage_tools
from tools_gateway.registry import PERMISSION_READ, Tool, ToolRegistry, ToolResult


async def _echo(**kwargs: str) -> ToolResult:
    """原样返回输入文本（连通性/教学演示用）。"""
    return ToolResult(ok=True, content=f"echo: {kwargs['text']}")


def create_default_registry(sandbox=None) -> ToolRegistry:
    """创建含全部内置工具的注册表。

    sandbox：可选 SandboxRunner，传入则注册 sandbox_run 工具（M4，Agent 可执行代码）。
    """
    registry = ToolRegistry()
    registry.register(
        Tool(
            name="echo",
            description="把 text 参数原样返回，用于验证工具链路。",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            func=_echo,
            permission=PERMISSION_READ,  # F2.4：只读，无副作用
        )
    )
    if sandbox is not None:
        registry.register(build_sandbox_run_tool(sandbox))
    # MicroBalance accounting tools, one registrar per domain.
    register_ledger_tools(registry)
    register_sales_tools(registry)
    register_purchases_tools(registry)
    register_inventory_tools(registry)
    register_banking_tools(registry)
    register_audit_tools(registry)
    register_tax_tools(registry)
    register_payroll_tools(registry)
    register_expense_tools(registry)
    register_asset_tools(registry)
    register_budget_tools(registry)
    register_finance_tools(registry)
    register_project_tools(registry)
    register_profile_tools(registry)
    register_document_tools(registry)
    register_integration_tools(registry)
    register_usage_tools(registry)
    return registry
