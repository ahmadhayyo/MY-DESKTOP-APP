"""
CLI entrypoint for HAYO.

Usage:
    python main.py
    python main.py --once "افتح كروم وحمّل ملف PDF من ..."

Async-first: the canonical workflow uses AsyncSqliteSaver, so we drive the
graph via .ainvoke under asyncio.run.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

# Load .env BEFORE importing the graph (LLM clients build at import time).
load_dotenv(Path(__file__).parent / ".env", override=True)

from agent.workflow import compile_graph  # noqa: E402

DEFAULT_WORKSPACE = Path(os.getenv("DEFAULT_WORKSPACE", str(Path(__file__).parent)))
MODEL_PROVIDER = os.getenv("MODEL_PROVIDER", "google").lower().strip()

console = Console()


from config import _is_placeholder  # noqa: E402 — reuse canonical version


def assert_keys_present() -> None:
    if MODEL_PROVIDER == "ollama":
        return
    key_map = {
        "anthropic": "ANTHROPIC_API_KEY",
        "google": "GOOGLE_API_KEY",
        "openai": "OPENAI_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "groq": "GROQ_API_KEY",
    }
    var_name = key_map.get(MODEL_PROVIDER)
    if var_name:
        val = os.getenv(var_name, "")
        if _is_placeholder(val):
            raise RuntimeError(
                f"MODEL_PROVIDER='{MODEL_PROVIDER}' but {var_name} is empty or "
                f"contains a placeholder value in .env\n"
                f"Tip: set MODEL_PROVIDER=ollama for free local AI (no API key needed)."
            )


def _print_response(state: dict) -> None:
    msgs = state.get("messages", [])
    for msg in msgs[-3:]:
        kind = msg.__class__.__name__
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        if not content.strip():
            continue
        console.print(Panel(Markdown(content[:4000]), title=kind, border_style="cyan"))


async def run_one(graph, message: str, thread_id: str) -> None:
    config = {"configurable": {"thread_id": thread_id}}
    initial = {
        "messages": [HumanMessage(content=message)],
        "plan": [],
        "completed_steps": [],
        "workspace": str(DEFAULT_WORKSPACE),
        "error_logs": [],
        "iteration_count": 0,
        "requires_human_approval": False,
        "pending_command": "",
    }
    try:
        final = await graph.ainvoke(initial, config=config)
    except Exception as exc:
        console.print(f"[red]Graph error: {type(exc).__name__}: {exc}[/red]")
        return
    _print_response(final)


async def amain() -> int:
    parser = argparse.ArgumentParser(description="HAYO local OS agent")
    parser.add_argument("--once", type=str, help="Run a single message and exit")
    args = parser.parse_args()

    try:
        assert_keys_present()
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        return 2

    console.print(
        Panel.fit(
            f"[bold green]HAYO AI AGENT[/bold green] — provider: [cyan]{MODEL_PROVIDER}[/cyan]\n"
            f"workspace: {DEFAULT_WORKSPACE}\n"
            f"اكتب طلبك بالعربية أو الإنجليزية. اكتب /quit للخروج.",
            border_style="green",
        )
    )

    graph = compile_graph()
    thread_id = str(uuid.uuid4())

    if args.once:
        await run_one(graph, args.once, thread_id)
        return 0

    while True:
        try:
            user = console.input("[bold yellow]> [/bold yellow]").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]bye[/dim]")
            return 0
        if not user:
            continue
        if user.lower() in ("/quit", "/exit", "exit", "quit"):
            return 0
        await run_one(graph, user, thread_id)


def main() -> int:
    return asyncio.run(amain())


if __name__ == "__main__":
    sys.exit(main())
