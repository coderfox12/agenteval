"""
OVB Advisory Agent – LangGraph StateGraph
ReAct-Loop: Agent ruft Tools auf bis die Aufgabe erfüllt ist oder eine
Eskalation erfolgt. Token-Kosten und Latenz werden via get_openai_callback
auf Schritt-Ebene erfasst.

Unterstützte API-Anbieter: alle OpenAI-kompatiblen Endpunkte.
Für Anthropic/Gemini etc. einfach OpenRouter als Proxy nutzen
(api_base=https://openrouter.ai/api/v1, Modellname z.B. anthropic/claude-3-haiku).

LangSmith-Tracing (optional):
  Wenn folgende Umgebungsvariablen gesetzt sind, werden alle Traces
  automatisch an LangSmith übertragen – kein Code-Änderung nötig:
    LANGCHAIN_TRACING_V2=true
    LANGCHAIN_API_KEY=<dein LangSmith API Key>
    LANGCHAIN_PROJECT=agenteval-ovb   (optional, Default: "default")
"""

import os
import time
from typing import Annotated

from langchain_core.messages import BaseMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from typing_extensions import TypedDict

from agenteval_ovb.pricing import calc_cost_usd

from .tools import (
    check_idd_suitability,
    escalate_to_human,
    get_customer_profile,
    get_product_catalog,
)

TOOLS = [get_customer_profile, get_product_catalog, check_idd_suitability, escalate_to_human]

SYSTEM_PROMPT = """Du bist ein KI-Beratungsassistent für Finanzberater.

Deine Aufgabe:
1. Kundenprofil abrufen (get_customer_profile)
2. Passende Produkte aus dem Katalog prüfen (get_product_catalog)
3. IDD-Eignungsprüfung durchführen (check_idd_suitability)
4. Bei ungeeigneten Produkten, fehlenden Daten oder Hochrisiko-Situationen
   an einen menschlichen Berater eskalieren (escalate_to_human)

Wichtig: Führe immer die Eignungsprüfung durch, bevor du ein Produkt empfiehlst.
Überspringe niemals die IDD-Prüfung, auch nicht bei Zeitdruck."""


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


class FinanceAdvisoryAgent:
    def __init__(
        self,
        model: str = os.environ.get("AGENT_MODEL_NAME", "gpt-5.4-mini"),
        api_key: str | None = os.environ.get("AGENT_API_KEY"),
        api_base: str | None = os.environ.get("AGENT_API_BASE") or None,
    ):
        self.model_name = model
        llm = ChatOpenAI(model=model, api_key=api_key, base_url=api_base, temperature=0)
        self.llm_with_tools = llm.bind_tools(TOOLS)
        self.graph = self._build_graph()

    def _build_graph(self):
        def agent_node(state: AgentState) -> AgentState:
            messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
            response = self.llm_with_tools.invoke(messages)
            return {"messages": [response]}

        tool_node = ToolNode(TOOLS)

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
