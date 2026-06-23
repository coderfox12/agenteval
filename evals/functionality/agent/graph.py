"""
UseCaseAgent – generischer LangGraph-ReAct-Agent für alle Use Cases.

Tools, System-Prompt und Provider werden über den Konstruktor injiziert,
damit jeder UC ein eigenständiges, steckbares Paket bleibt.

Unterstützte API-Anbieter: alle OpenAI-kompatiblen Endpunkte.
Für Anthropic/Gemini etc. einfach OpenRouter als Proxy nutzen
(api_base=https://openrouter.ai/api/v1, Modellname z.B. anthropic/claude-3-haiku).
"""

import os
import time
from typing import Annotated

from langchain_core.messages import BaseMessage, SystemMessage
from langgraph.graph import START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from typing_extensions import TypedDict

from agenteval_ovb.pricing import calc_cost_usd


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


class UseCaseAgent:
    def __init__(
        self,
        tools: list,
        system_prompt: str,
        model: str | None = None,
        provider: str = "openai",
        api_key: str | None = None,
        api_base: str | None = None,
        provider_pin: str | None = None,
    ):
        model = model or os.environ.get("AGENT_MODEL_NAME") or os.environ.get("MODEL_NAME", "gpt-5.4-mini")
        self.model_name = model
        self.system_prompt = system_prompt
        self.tools = tools
        llm = self._make_llm(provider, model, api_key=api_key, api_base=api_base, provider_pin=provider_pin)
        self.llm_with_tools = llm.bind_tools(tools)
        self.graph = self._build_graph()

    def _make_llm(
        self, provider: str, model: str, api_key: str | None = None,
        api_base: str | None = None, provider_pin: str | None = None,
    ):
        if provider == "openai":
            from langchain_openai import ChatOpenAI
            # provider_pin (nur relevant bei OpenRouter): fixiert den
            # tatsächlichen Hosting-Anbieter über extra_body – OpenRouter
            # routet denselben Modellnamen sonst je nach Verfügbarkeit an
            # unterschiedliche Hosts mit teils stark abweichenden Preisen
            # (real gemessen: bis Faktor 3,4). Siehe agents_config.
            # provider_pin_extra_body(). Bei direkter Provider-API (kein
            # OpenRouter) bleibt provider_pin leer, extra_body={} ist dann
            # ein No-op.
            extra_body = {"provider": {"only": [provider_pin]}} if provider_pin else {}
            return ChatOpenAI(
                model=model, temperature=0, api_key=api_key, base_url=api_base,
                extra_body=extra_body,
            )
        raise ValueError(
            f"Unsupported provider '{provider}'. "
            "Add a branch here for langchain_anthropic / langchain_google_genai."
        )

    def _build_graph(self):
        def agent_node(state: AgentState) -> AgentState:
            messages = [SystemMessage(content=self.system_prompt)] + state["messages"]
            response = self.llm_with_tools.invoke(messages)
            return {"messages": [response]}

        tool_node = ToolNode(self.tools)

        graph = StateGraph(AgentState)
        graph.add_node("agent", agent_node)
        graph.add_node("tools", tool_node)
        graph.add_edge(START, "agent")
        graph.add_conditional_edges("agent", tools_condition)
        graph.add_edge("tools", "agent")

        return graph.compile()

    def run(self, task: str) -> dict:
        """
        Führt einen Multi-Step-Task aus und gibt Ergebnis + Wirtschaftlichkeitsdaten zurück.
        Token-Kosten werden via get_openai_callback erfasst (kein separates Eval-Framework nötig).
        """
        from langchain_community.callbacks import get_openai_callback

        start_time = time.time()

        with get_openai_callback() as cb:
            result = self.graph.invoke({"messages": [{"role": "user", "content": task}]})

        latency_ms = int((time.time() - start_time) * 1000)

        tools_called = []
        for msg in result["messages"]:
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    tools_called.append(tc["name"])

        # final_output kann leer sein (z.B. Content-Filter des Modells, bei
        # Gemini via OpenRouter beobachtet) – die Tokens wurden trotzdem
        # verbraucht und bei OpenRouter abgerechnet (cost_usd unten ist exakt),
        # daher hier NICHT werfen: der Aufrufer (test_functionality._run_and_record)
        # entscheidet, ob/wie ein leerer Output behandelt wird, behält aber in
        # jedem Fall die echten Kosten dieses Aufrufs.
        final_output = result["messages"][-1].content
        cost_usd = calc_cost_usd(self.model_name, cb.prompt_tokens, cb.completion_tokens)

        return {
            "output": final_output,
            "tools_called": tools_called,
            "messages": result["messages"],
            "cost": {
                "prompt_tokens": cb.prompt_tokens,
                "completion_tokens": cb.completion_tokens,
                "total_tokens": cb.total_tokens,
                "cost_usd": round(cost_usd, 6),
                "latency_ms": latency_ms,
            },
        }
