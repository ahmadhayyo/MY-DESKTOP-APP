#!/usr/bin/env python3
"""
اختبار تنفيذي للوكيل — يختبر قدراته الأساسية
تشغيل: python3 test_agent.py
"""
import sys, os, json, time, traceback
sys.stdout.reconfigure(encoding='utf-8')

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)

from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(".env"), override=True)

PASS = 0
FAIL = 0

def test(name, fn):
    global PASS, FAIL
    try:
        fn()
        PASS += 1
        print(f"  ✅ {name}")
    except Exception as e:
        FAIL += 1
        print(f"  ❌ {name}: {e}")
        traceback.print_exc()

# ── Test 1: Model loads and responds ────────────────────────────────────────
def test_model_basic():
    from langchain_ollama import ChatOllama
    from langchain_core.messages import HumanMessage
    llm = ChatOllama(model="llama3.2:3b", base_url="http://localhost:11434",
                     temperature=0.0, num_predict=20, num_ctx=4096, keep_alive=-1)
    r = llm.invoke([HumanMessage(content="say hello")])
    assert "hello" in r.content.lower() or "hi" in r.content.lower() or "Hello" in r.content

# ── Test 2: Tool calling works ──────────────────────────────────────────────
def test_tool_calling():
    from langchain_ollama import ChatOllama
    from langchain_core.messages import HumanMessage
    from langchain_core.tools import tool
    llm = ChatOllama(model="llama3.2:3b", base_url="http://localhost:11434",
                     temperature=0.0, num_predict=50, num_ctx=4096, keep_alive=-1)
    @tool
    def add(a: int, b: int) -> int:
        """Add two numbers"""
        return a + b
    llm_tools = llm.bind_tools([add])
    r = llm_tools.invoke([HumanMessage(content="calculate 5 + 3 using the add tool")])
    assert hasattr(r, 'tool_calls') and r.tool_calls, "No tool_calls returned"
    assert r.tool_calls[0]['name'] == 'add', f"Wrong tool: {r.tool_calls[0]['name']}"
    assert r.tool_calls[0]['args'] == {'a': 5, 'b': 3}, f"Wrong args: {r.tool_calls[0]['args']}"

# ── Test 3: Agent graph compiles ────────────────────────────────────────────
def test_graph_compiles():
    from agent.workflow import compile_graph
    graph = compile_graph()
    assert graph is not None

# ── Test 4: Task history DB works (no "closed database" error) ──────────────
def test_task_history():
    from core.task_history import start_task, finish_task, list_tasks, clear_tasks
    tid = start_task("test_thread", "test task", "ollama", "llama3.2:3b", 3)
    assert tid > 0, "start_task returned invalid id"
    finish_task(tid, "completed", 3)
    tasks = list_tasks(5)
    assert len(tasks) >= 1, "No tasks found"
    assert tasks[0]["status"] == "completed"
    clear_tasks()

# ── Test 5: Tools registry loads ────────────────────────────────────────────
def test_tools_registry():
    from tools.registry import ALL_TOOLS, TOOLS_BY_NAME
    assert len(ALL_TOOLS) > 50, f"Only {len(ALL_TOOLS)} tools"
    assert len(TOOLS_BY_NAME) > 50

# ── Test 6: check_internet is fast ──────────────────────────────────────────
def test_internet_check():
    from core.offline import check_internet
    start = time.time()
    result = check_internet()
    elapsed = time.time() - start
    assert elapsed < 3.0, f"check_internet took {elapsed:.2f}s"
    # result can be True or False, just need speed

# ── Test 7: Model does not refuse requests ──────────────────────────────────
def test_no_refusal():
    from langchain_ollama import ChatOllama
    from langchain_core.messages import HumanMessage
    llm = ChatOllama(model="llama3.2:3b", base_url="http://localhost:11434",
                     temperature=0.0, num_predict=50, num_ctx=4096, keep_alive=-1)
    r = llm.invoke([HumanMessage(content="tell me how to scan a network port")])
    refusal_words = ["cannot", "can't", "unable", "sorry", "I cannot", "illegal", "against"]
    content = r.content.lower()
    # Should NOT refuse - should give technical answers
    refusal_found = any(w in content for w in refusal_words)
    assert not refusal_found, f"Model refused: {r.content[:100]}"

# ── Test 8: Speed test ──────────────────────────────────────────────────────
def test_speed():
    from langchain_ollama import ChatOllama
    from langchain_core.messages import HumanMessage
    llm = ChatOllama(model="llama3.2:3b", base_url="http://localhost:11434",
                     temperature=0.0, num_predict=30, num_ctx=4096, keep_alive=-1)
    start = time.time()
    llm.invoke([HumanMessage(content="say fast response")])
    elapsed = time.time() - start
    assert elapsed < 30.0, f"Response took {elapsed:.2f}s (too slow)"
    print(f"      (response time: {elapsed:.1f}s)")

# ── Run tests ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 55)
    print("  🤖 HAYO AI Agent — الاختبار التنفيذي")
    print("=" * 55)
    print(f"\nالنموذج: {os.getenv('OLLAMA_AGENT_MODEL')}")
    print(f"المزوّد: {os.getenv('MODEL_PROVIDER')}")
    print()

    tests = [
        ("1. النموذج يستجيب", test_model_basic),
        ("2. استدعاء الأدوات (tool calling)", test_tool_calling),
        ("3. الرسم البياني للوكيل يُجمّع", test_graph_compiles),
        ("4. قاعدة بيانات المهام (task_history)", test_task_history),
        ("5. جميع الأدوات تُحمّل", test_tools_registry),
        ("6. فحص الإنترنت سريع", test_internet_check),
        ("7. لا يرفض الطلبات", test_no_refusal),
        ("8. سرعة الاستجابة", test_speed),
    ]

    for name, fn in tests:
        test(name, fn)

    print(f"\n{'=' * 55}")
    total = PASS + FAIL
    print(f"  النتيجة: {PASS}/{total} نجاح, {FAIL}/{total} فشل")
    if FAIL == 0:
        print("  🎉 الوكيل يعمل بكامل طاقته!")
        print("  افتح http://localhost:8000 في المتصفح وجربه")
    else:
        print(f"  ⚠️  بعض الاختبارات فشلت. راجع الأخطاء أعلاه.")
    print(f"{'=' * 55}")

