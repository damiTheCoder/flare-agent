"""确定性 Mock 供应商（无网络/无 Key）：本地开发与单元测试。

模拟"会调用 echo 工具、能观察结果给出结论"的模型，返回结构化 JSON 决策串
（与真实 function-calling 同形态，graph 层负责解析）：
  - 需要工具: {"action": "call_tool", "tool": {"name": "echo", "args": {"text": <首个 user 消息>}}}
  - 已有工具观察: {"action": "final", "answer": "完成: <观察内容>"}
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator

from model_gateway.providers import (
    LLMMessage,
    LLMResponse,
    LLMUsage,
    ToolCall,
    ToolCallDecision,
)


def _summarise(observation: str) -> str:
    """Human-readable closing line; the UI shows the full result in a card."""
    # The graph prefixes observations with "[tool] "; strip it before parsing.
    body = observation
    if body.startswith("[") and "] " in body:
        body = body.split("] ", 1)[1]
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return f"完成: {observation}"
    invoice = payload.get("invoice") if isinstance(payload, dict) else None
    if isinstance(invoice, dict):
        return (
            f"Invoice {invoice.get('invoiceNumber')} created for {invoice.get('customer')} — "
            f"total {invoice.get('total')}. The journal is PENDING approval."
        )
    return f"完成: {observation}"


class MockModelProvider:
    """确定性 mock 供应商。"""

    model: str = "mock"

    def _decide(self, messages: list[LLMMessage]) -> ToolCallDecision:
        last = messages[-1] if messages else None
        if last is not None and last.role == "tool":
            return ToolCallDecision(action="final", answer=_summarise(last.content))
        user_text = next((m.content for m in messages if m.role == "user"), "")
        # F1.3 联调/演示触发器：消息含「沙箱执行」→ 调 sandbox_run（触发审批门，
        # 让 mock 环境下也能走通「人工审批 → 放行/拒绝」闭环；真实模型无需此分支）
        lowered = user_text.lower()
        # Demo trigger: the DSH-style UI sends "create an invoice ..." and expects
        # a structured tool card, so the mock emits a real create_invoice call
        # against the seeded demo tenant.
        if "invoice" in lowered:
            from datetime import date

            return ToolCallDecision(
                action="call_tool",
                tool=ToolCall(
                    name="create_invoice",
                    args={
                        "companyId": "acme",
                        "customerId": "cus_demo",
                        "date": date.today().isoformat(),
                        "items": [{"itemId": "itm_demo", "quantity": 2, "unitPrice": "250.00"}],
                    },
                ),
            )
        match = re.search(r"沙箱执行[:：]?\s*([\s\S]+)", user_text)
        if match:
            return ToolCallDecision(
                action="call_tool",
                tool=ToolCall(name="sandbox_run", args={"code": match.group(1).strip()}),
            )
        return ToolCallDecision(
            action="call_tool", tool=ToolCall(name="echo", args={"text": user_text})
        )

    async def chat(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict] | None = None,  # M4：mock 走确定性决策，忽略工具清单
    ) -> LLMResponse:
        content = self._decide(messages).model_dump_json()
        prompt_tokens = sum(len(m.content) for m in messages)
        return LLMResponse(
            content=content,
            model=model or self.model,
            usage=LLMUsage(prompt_tokens=prompt_tokens, completion_tokens=len(content)),
        )

    async def stream(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        tools: list[dict] | None = None,
    ) -> AsyncIterator[str]:
        response = await self.chat(messages, model=model, temperature=temperature, tools=tools)
        # 词级分块（更接近真实 token 流形状），勿让上层形成"逐字符"依赖（R4）
        for word in response.content.split(" "):
            yield word + " "
