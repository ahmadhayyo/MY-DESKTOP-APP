"""
agent/workflow.py - LangGraph StateGraph compilation with persistent memory.

Checkpointer selection:
  1. AsyncSqliteSaver (preferred, supports Chainlit's astream_events)
  2. SqliteSaver (sync-only fallback)
  3. MemorySaver (last resort, no persistence)
"""

import logging
import os

from langgraph.graph import END, StateGraph

from agent.nodes import (
    planner_node,
    reviewer_node,
    should_continue,
    worker_node,
)
from core.state import AgentState

logger = logging.getLogger("hayo.workflow")

_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "agent_memory.db"
)

_COMPILED_GRAPH = None


def _build_checkpointer():
    """Pick the best available checkpointer."""
    try:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        import aiosqlite

        conn = aiosqlite.connect(_DB_PATH, check_same_thread=False)
        logger.info("Persistent memory (async): %s", _DB_PATH)
        return AsyncSqliteSaver(conn)
    except ImportError as exc:
        logger.warning("AsyncSqliteSaver unavailable (%s). pip install aiosqlite", exc)
    except Exception as exc:
        logger.warning("AsyncSqliteSaver init failed (%s)", exc)

    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
        import sqlite3

        conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
        logger.warning("Persistent memory (sync only): %s", _DB_PATH)
        return SqliteSaver(conn)
    except Exception as exc:
        logger.warning("SqliteSaver unavailable (%s)", exc)

    from langgraph.checkpoint.memory import MemorySaver
    logger.warning("Using MemorySaver — no persistence between restarts")
    return MemorySaver()


def compile_graph():
    """Build and compile the agent StateGraph (singleton)."""
    global _COMPILED_GRAPH
    if _COMPILED_GRAPH is not None:
        return _COMPILED_GRAPH

    # ── Housekeeping: prune the checkpoint DB BEFORE the saver opens it ────────
    # Runs only when the DB has grown past a threshold; keeps every graph step
    # fast and stops agent_memory.db from ballooning to tens of MB.
    try:
        from core.maintenance import auto_prune_if_needed
        auto_prune_if_needed(_DB_PATH, size_trigger_mb=25)
    except Exception as exc:
        logger.warning("Startup DB prune skipped: %s", exc)

    builder = StateGraph(AgentState)
    builder.add_node("planner", planner_node)
    builder.add_node("worker", worker_node)
    builder.add_node("reviewer", reviewer_node)
    builder.set_entry_point("planner")
    builder.add_edge("planner", "worker")
    builder.add_edge("worker", "reviewer")
    builder.add_conditional_edges(
        "reviewer",
        should_continue,
        {"worker": "worker", "__end__": END},
    )

    _COMPILED_GRAPH = builder.compile(checkpointer=_build_checkpointer())
    logger.info("Agent graph compiled successfully")

    # Early warmup: pre-load Ollama model so first user request is fast
    try:
        from agent.nodes import _get_main_llm, _PROVIDER
        if _PROVIDER == "ollama":
            import threading
            def _early_warmup():
                try:
                    from langchain_core.messages import HumanMessage
                    llm = _get_main_llm()
                    llm.invoke([HumanMessage(content="hi")], options={"num_predict": 1})
                    logger.info("Ollama model pre-warmed during startup")
                except Exception:
                    pass
            t = threading.Thread(target=_early_warmup, daemon=True)
            t.start()
    except Exception:
        pass

    return _COMPILED_GRAPH
