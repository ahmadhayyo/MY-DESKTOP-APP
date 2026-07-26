"""
railway_tools.py — Manage your Railway deployments from the agent.

Connects to Railway's official Public GraphQL API (https://backboard.railway.com
/graphql/v2) using your account/team token. List projects & services, check
deployment status, read logs, trigger a redeploy, and read environment variables.

Setup (one line): put your token in .env →  RAILWAY_TOKEN=...
Get it from: Railway dashboard → Account Settings → Tokens (create an account token).

Tools:
  • railway_status()                              — verify the token / who am I
  • railway_projects()                            — list your projects (+ ids)
  • railway_services(project_id)                  — services + environments of a project
  • railway_deployments(service_id, env_id, project_id) — recent deployments + status
  • railway_logs(deployment_id)                   — build + deploy logs
  • railway_redeploy(deployment_id)               — trigger a redeploy
  • railway_variables(project_id, env_id, service_id) — environment variables
  • railway_graphql(query, variables)             — run any raw GraphQL (advanced)
"""
from __future__ import annotations

import json as _json
import os
import warnings
from typing import Annotated

from langchain_core.tools import tool

_ENDPOINT = "https://backboard.railway.com/graphql/v2"


def _token() -> str:
    return (os.getenv("RAILWAY_TOKEN") or os.getenv("RAILWAY_API_TOKEN") or "").strip()


def _no_token() -> str:
    return ("❌ لا يوجد RAILWAY_TOKEN في .env.\n"
            "   احصل عليه من: Railway → Account Settings → Tokens (Create Token)،\n"
            "   ثم أضِف في .env:  RAILWAY_TOKEN=رمزك")


def _gql(query: str, variables: dict | None = None) -> tuple[dict | None, str | None]:
    """POST a GraphQL query. Returns (data, error_str)."""
    import requests
    headers = {"Authorization": f"Bearer {_token()}",
               "Content-Type": "application/json"}
    payload = {"query": query, "variables": variables or {}}
    try:
        try:
            r = requests.post(_ENDPOINT, json=payload, headers=headers, timeout=30)
        except requests.exceptions.SSLError:
            warnings.filterwarnings("ignore")
            try:
                import urllib3
                urllib3.disable_warnings()
            except Exception:
                pass
            r = requests.post(_ENDPOINT, json=payload, headers=headers, timeout=30, verify=False)
    except Exception as e:
        return None, f"❌ تعذّر الاتصال بـ Railway: {e}"

    if r.status_code == 401 or r.status_code == 403:
        return None, "❌ التوكن غير صالح أو منتهي (401/403). جدّد RAILWAY_TOKEN."
    try:
        body = r.json()
    except Exception:
        return None, f"❌ رد غير متوقّع ({r.status_code}): {r.text[:200]}"
    if body.get("errors"):
        msgs = "; ".join(e.get("message", "?") for e in body["errors"])
        return None, f"❌ Railway API: {msgs}"
    return body.get("data"), None


def _edges(node_container: dict, *path) -> list:
    """Walk a {edges:[{node:{}}]} structure safely."""
    cur = node_container
    for p in path:
        cur = (cur or {}).get(p, {})
    return [e.get("node", {}) for e in (cur or {}).get("edges", [])]


# ═══════════════════════════════════════════════════════════════════════════════
@tool
def railway_status() -> str:
    """التحقق من توكن Railway وعرض الحساب المرتبط."""
    if not _token():
        return _no_token()
    data, err = _gql("query { me { name email } }")
    if err:
        return err
    me = (data or {}).get("me", {}) or {}
    return (f"✅ متصل بـ Railway كـ «{me.get('name') or '—'}»"
            f" ({me.get('email') or '—'}).")


@tool
def railway_projects() -> str:
    """عرض كل مشاريعك على Railway مع معرّفاتها (IDs)."""
    if not _token():
        return _no_token()
    q = "query { me { projects { edges { node { id name updatedAt } } } } }"
    data, err = _gql(q)
    if err:
        return err
    projects = _edges(data, "me", "projects")
    if not projects:
        return "ℹ️ لا توجد مشاريع على هذا الحساب."
    lines = [f"🚂 مشاريع Railway ({len(projects)}):"]
    for p in projects:
        lines.append(f"  • {p.get('name')}  (id: {p.get('id')})")
    lines.append("\n💡 لرؤية الخدمات: railway_services(project_id='...')")
    return "\n".join(lines)


@tool
def railway_services(
    project_id: Annotated[str, "Project id (from railway_projects)."],
) -> str:
    """عرض خدمات وبيئات مشروع Railway (مع معرّفاتها)."""
    if not _token():
        return _no_token()
    q = """query p($id: String!) {
      project(id: $id) {
        name
        services { edges { node { id name } } }
        environments { edges { node { id name } } }
      }
    }"""
    data, err = _gql(q, {"id": project_id})
    if err:
        return err
    proj = (data or {}).get("project") or {}
    if not proj:
        return f"❌ لم أجد مشروعاً بالمعرّف {project_id}."
    svcs = _edges(proj, "services")
    envs = _edges(proj, "environments")
    lines = [f"🚂 مشروع «{proj.get('name')}»", "", "🔧 الخدمات:"]
    lines += [f"  • {s.get('name')}  (id: {s.get('id')})" for s in svcs] or ["  (لا خدمات)"]
    lines += ["", "🌍 البيئات:"]
    lines += [f"  • {e.get('name')}  (id: {e.get('id')})" for e in envs] or ["  (لا بيئات)"]
    lines.append("\n💡 الحالة: railway_deployments(service_id, env_id, project_id)")
    return "\n".join(lines)


@tool
def railway_deployments(
    service_id: Annotated[str, "Service id (from railway_services)."],
    environment_id: Annotated[str, "Environment id (from railway_services)."],
    project_id: Annotated[str, "Project id."],
) -> str:
    """عرض آخر عمليات النشر (deployments) لخدمة وحالتها (نجح/فشل/قيد التشغيل)."""
    if not _token():
        return _no_token()
    q = """query d($p: String!, $e: String!, $s: String!) {
      deployments(first: 6, input: {projectId: $p, environmentId: $e, serviceId: $s}) {
        edges { node { id status createdAt staticUrl } }
      }
    }"""
    data, err = _gql(q, {"p": project_id, "e": environment_id, "s": service_id})
    if err:
        return err
    deps = _edges(data, "deployments")
    if not deps:
        return "ℹ️ لا توجد عمليات نشر لهذه الخدمة."
    icon = {"SUCCESS": "🟢", "FAILED": "🔴", "BUILDING": "🟡", "DEPLOYING": "🟡",
            "CRASHED": "🔴", "REMOVED": "⚪", "SKIPPED": "⚪", "QUEUED": "🟡"}
    lines = [f"🚀 آخر عمليات النشر ({len(deps)}):"]
    for d in deps:
        st = d.get("status", "?")
        lines.append(f"  {icon.get(st,'•')} {st}  —  {d.get('createdAt','')[:19]}"
                     f"  (id: {d.get('id')})")
        if d.get("staticUrl"):
            lines.append(f"      🔗 https://{d['staticUrl']}")
    lines.append("\n💡 السجلّات: railway_logs(deployment_id) | إعادة النشر: railway_redeploy(deployment_id)")
    return "\n".join(lines)


@tool
def railway_logs(
    deployment_id: Annotated[str, "Deployment id (from railway_deployments)."],
    limit: Annotated[int, "How many log lines."] = 80,
) -> str:
    """قراءة سجلّات البناء والنشر لعملية نشر محددة على Railway."""
    if not _token():
        return _no_token()
    out = []
    for kind, field in (("build", "buildLogs"), ("deploy", "deploymentLogs")):
        q = f"""query l($id: String!, $n: Int!) {{
          {field}(deploymentId: $id, limit: $n) {{ message timestamp severity }}
        }}"""
        data, err = _gql(q, {"id": deployment_id, "n": min(max(limit, 10), 300)})
        if err or not data:
            continue
        logs = data.get(field) or []
        if logs:
            out.append(f"── {kind} logs ({len(logs)}) ──")
            out += [f"  {l.get('message','')}" for l in logs[-limit:]]
    if not out:
        return "ℹ️ لا توجد سجلّات (قد يكون معرّف النشر خاطئاً أو لا سجلّات بعد)."
    return "\n".join(out)


@tool
def railway_redeploy(
    deployment_id: Annotated[str, "Deployment id to redeploy (from railway_deployments)."],
) -> str:
    """إعادة نشر (redeploy) عملية نشر موجودة على Railway."""
    if not _token():
        return _no_token()
    q = """mutation r($id: String!) {
      deploymentRedeploy(id: $id) { id status }
    }"""
    data, err = _gql(q, {"id": deployment_id})
    if err:
        return err
    dep = (data or {}).get("deploymentRedeploy") or {}
    return (f"✅ بدأت إعادة النشر. الحالة: {dep.get('status','?')} (id: {dep.get('id')})"
            if dep else "⚠️ لم تُرجع Railway تأكيداً — تحقّق من لوحة التحكم.")


@tool
def railway_variables(
    project_id: Annotated[str, "Project id."],
    environment_id: Annotated[str, "Environment id."],
    service_id: Annotated[str, "Service id."],
) -> str:
    """عرض متغيّرات البيئة (Environment Variables) لخدمة على Railway.

    ⚠️ القيم سرّية — تُعرض مختصرة. لا تشاركها.
    """
    if not _token():
        return _no_token()
    q = """query v($p: String!, $e: String!, $s: String!) {
      variables(projectId: $p, environmentId: $e, serviceId: $s)
    }"""
    data, err = _gql(q, {"p": project_id, "e": environment_id, "s": service_id})
    if err:
        return err
    vars_ = (data or {}).get("variables") or {}
    if not vars_:
        return "ℹ️ لا متغيّرات بيئة لهذه الخدمة."
    lines = [f"🔐 متغيّرات البيئة ({len(vars_)}):"]
    for k, v in vars_.items():
        masked = (str(v)[:4] + "…") if v else "(فارغ)"
        lines.append(f"  • {k} = {masked}")
    return "\n".join(lines)


@tool
def railway_graphql(
    query: Annotated[str, "A raw GraphQL query/mutation string."],
    variables: Annotated[str, "Optional JSON object of variables."] = "",
) -> str:
    """تشغيل استعلام GraphQL خام على Railway API (للعمليات المتقدّمة غير المغطّاة)."""
    if not _token():
        return _no_token()
    try:
        vars_ = _json.loads(variables) if variables.strip() else {}
    except Exception:
        return "❌ variables يجب أن تكون JSON صحيحاً."
    data, err = _gql(query, vars_)
    if err:
        return err
    return "📦 النتيجة:\n" + _json.dumps(data, ensure_ascii=False, indent=2)[:3000]
