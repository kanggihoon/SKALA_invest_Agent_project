from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Literal, Optional, TypedDict

from langgraph.graph import END, StateGraph

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

# Load .env if present
try:
    from dotenv import load_dotenv

    load_dotenv()
    load_dotenv(BASE.parent.parent / ".env")
except Exception:
    pass

from rag.loaders import load_dir
from rag.vector import as_retriever, build_index
from agents.scout import scout_chain
from agents.tech import tech_chain
from agents.market import market_chain
from agents.competitor import competitor_chain
from agents.decision import decision_chain
from agents.report import (
    write_report,
    generate_project_readme_md,
    write_text,
    write_docx_report,
)
from db.postgres import (
    get_engine,
    log_run,
    upsert_startup,
    update_startup_columns,
    get_startup_by_name,
    add_startup_sources,
)


class S(TypedDict, total=False):
    domain: str
    query: str
    target: Optional[str]
    tech_raw: Optional[str]
    tech: Optional[str]
    market: Optional[str]
    comp: Optional[str]
    decision: Optional[Literal["recommend", "hold", "pass"]]
    score: Optional[int]
    rationale: Optional[str]
    sources: List[str]
    report_path: Optional[str]
    report_docx_path: Optional[str]
    candidates: Optional[List[dict]]
    cand_idx: Optional[int]
    loop_count: Optional[int]
    snippets: Optional[List[dict]]
    market_struct: Optional[dict]
    comp_struct: Optional[dict]
    decisions: Optional[List[dict]]
    recommended: Optional[List[dict]]


INDEX_DIR = BASE / ".index"
DATA_DIRS = {
    "scout": BASE / "data" / "scout",
    "tech": BASE / "data" / "tech",
    "market": BASE / "data" / "market",
    "comp": BASE / "data" / "competitors",
}


def prepare():
    INDEX_DIR.mkdir(exist_ok=True)
    retrievers = {}
    for name, d in DATA_DIRS.items():
        idx_dir = INDEX_DIR / name
        if not idx_dir.exists():
            docs = load_dir(str(d))
            build_index(docs, str(idx_dir))
        if idx_dir.exists() and any(idx_dir.iterdir()):
            retrievers[name] = as_retriever(str(idx_dir))
    return retrievers


IDX = prepare()
PG_ENGINE = get_engine()


class _NullRetriever:
    def get_relevant_documents(self, *_args, **_kwargs):
        return []


def n_scout(s: S):
    run = scout_chain(IDX.get("scout", _NullRetriever()))

    # Use existing candidates if any
    cands = s.get("candidates") or []
    idx = s.get("cand_idx") if s.get("cand_idx") is not None else 0
    used_existing = False
    if cands and idx < len(cands):
        cand = cands[idx]
        s["cand_idx"] = idx + 1
        s["target"] = cand.get("name") or s.get("target")
        s["tech_raw"] = cand.get("tech") or s.get("tech_raw")
        used_existing = True
    else:
        # Always attempt an LLM-based scout, even without index
        def _filter_ai_logi(items: List[dict]) -> List[dict]:
            # Unified keyword list (OR)
            kw = [
                "ai",
                "인공지능",
                "머신러닝",
                "ml",
                "llm",
                "물류",
                "유통",
                "logistics",
                "supply chain",
                "scm",
            ]
            out = []
            for c in items:
                t = str(c.get("tech", "")).lower()
                if any(k in t for k in kw):
                    out.append(c)
            return out

        attempts = 3
        gathered: List[dict] = []
        seen = set()
        merged_sources: List[str] = []
        base_q = str(s.get("query") or "")
        for i in range(attempts):
            q = base_q if i == 0 else base_q + " AI 인공지능 머신러닝 ML LLM 물류 유통 logistics 'supply chain' SCM"
            res = run(s["domain"], q)  # type: ignore[index]
            items = res.get("candidates") or []
            items = [c for c in items if isinstance(c, dict) and c.get("name")]
            items = _filter_ai_logi(items)
            for c in items:
                n = str(c.get("name")).strip()
                if n and n.lower() not in seen:
                    gathered.append(c)
                    seen.add(n.lower())
                    if len(gathered) >= 3:
                        break
            merged_sources.extend([src for src in (res.get("sources") or []) if src])
            if len(gathered) >= 3:
                break

        s["candidates"] = gathered[:3]
        s["cand_idx"] = 1 if s["candidates"] else 0
        if s["candidates"]:
            s["target"] = s["candidates"][0].get("name") or s.get("target")
            s["tech_raw"] = s["candidates"][0].get("tech") or s.get("tech_raw")
        else:
            s["target"] = s.get("target") or "TOP-1-STARTUP"
        if merged_sources:
            s["sources"] = s.get("sources", []) + list(dict.fromkeys(merged_sources))  # type: ignore[arg-type]

    # Persist to DB
    if PG_ENGINE and s.get("target"):
        upsert_startup(
            PG_ENGINE,
            domain=s.get("domain", ""),
            query=s.get("query", ""),
            name=s["target"],  # type: ignore[index]
            tech_raw=s.get("tech_raw"),
        )
        if not used_existing and s.get("sources"):
            try:
                add_startup_sources(PG_ENGINE, s["target"], list(dict.fromkeys(s["sources"]))[:10])  # type: ignore[arg-type]
            except Exception:
                pass
    return s


def n_tech(s: S):
    run = tech_chain(IDX.get("tech", _NullRetriever()))
    if PG_ENGINE and s.get("target"):
        rec = get_startup_by_name(PG_ENGINE, s["target"])  # type: ignore[arg-type]
        if rec and rec.get("tech_raw"):
            s["tech_raw"] = rec.get("tech_raw")
    tech_res = run(s["target"], s["query"], s.get("tech_raw"))  # include DB tech_raw
    s["tech"] = tech_res.get("text") if isinstance(tech_res, dict) else tech_res
    # Fallback: if tech is empty but we have tech_raw, synthesize minimal JSON-like summary
    if not s.get("tech") and s.get("tech_raw"):
        tr = s.get("tech_raw") or ""
        s["tech"] = (
            '{"include": true, "is_ai": true, "company_name": "' + str(s.get("target") or "") + '",'
            ' "country": "", "segment": "", "summary": "' + str(tr).replace('"', '\\"')[:350] + '",'
            ' "tech_highlight": "' + str(tr).split("\n")[0].replace('"', '\\"')[:120] + '", "source_url": ""}'
        )
    # merge sources from retrieval
    if isinstance(tech_res, dict) and tech_res.get("sources"):
        s.setdefault("sources", []).extend(tech_res["sources"])  # type: ignore[index]
    if isinstance(tech_res, dict) and tech_res.get("snippets"):
        s.setdefault("snippets", []).extend(tech_res["snippets"])  # type: ignore[index]
    if PG_ENGINE and s.get("target"):
        update_startup_columns(PG_ENGINE, s["target"], {"tech_summary": s.get("tech")})  # type: ignore[arg-type]
    s.setdefault("sources", []).append("tech")
    return s


def n_market(s: S):
    run = market_chain(IDX.get("market", _NullRetriever()))
    market_res = run(s["domain"], s["target"])  # always callable
    s["market"] = market_res.get("text") if isinstance(market_res, dict) else market_res
    if isinstance(market_res, dict) and market_res.get("json"):
        s["market_struct"] = market_res["json"]
    if isinstance(market_res, dict) and market_res.get("sources"):
        s.setdefault("sources", []).extend(market_res["sources"])  # type: ignore[index]
    if isinstance(market_res, dict) and market_res.get("snippets"):
        s.setdefault("snippets", []).extend(market_res["snippets"])  # type: ignore[index]
    if PG_ENGINE and s.get("target"):
        update_startup_columns(PG_ENGINE, s["target"], {"market_eval": s.get("market")})  # type: ignore[arg-type]
    s.setdefault("sources", []).append("market")
    return s


def n_comp(s: S):
    run = competitor_chain(IDX.get("comp", _NullRetriever()))
    cands = s.get("candidates") or ([s.get("target")] if s.get("target") else [])
    comp_res = run(s["domain"], cands)  # always callable
    s["comp"] = comp_res.get("text") if isinstance(comp_res, dict) else comp_res
    if isinstance(comp_res, dict) and comp_res.get("json"):
        s["comp_struct"] = comp_res["json"]
    if isinstance(comp_res, dict) and comp_res.get("sources"):
        s.setdefault("sources", []).extend(comp_res["sources"])  # type: ignore[index]
    if isinstance(comp_res, dict) and comp_res.get("snippets"):
        s.setdefault("snippets", []).extend(comp_res["snippets"])  # type: ignore[index]
    if PG_ENGINE and s.get("target"):
        update_startup_columns(PG_ENGINE, s["target"], {"competitor_analysis": s.get("comp")})  # type: ignore[arg-type]
    s.setdefault("sources", []).append("competitors")
    return s


def n_decision(s: S):
    # Evaluate all candidates, not just the first target
    t_chain = tech_chain(IDX.get("tech", _NullRetriever()))
    m_chain = market_chain(IDX.get("market", _NullRetriever()))
    c_chain = competitor_chain(IDX.get("comp", _NullRetriever()))
    d_chain = decision_chain()

    cands = s.get("candidates") or ([] if not s.get("target") else [{"name": s.get("target")}] )
    results: List[dict] = []

    for cand in cands[:3]:
        name = cand.get("name") if isinstance(cand, dict) else str(cand)
        if not name:
            continue
        # Tech
        tech_res = t_chain(name, s.get("query") or "", (cand.get("tech") if isinstance(cand, dict) else None))
        tech_text = tech_res.get("text") if isinstance(tech_res, dict) else tech_res
        if isinstance(tech_res, dict):
            if tech_res.get("sources"):
                s.setdefault("sources", []).extend(tech_res["sources"])  # type: ignore[index]
            if tech_res.get("snippets"):
                s.setdefault("snippets", []).extend(tech_res["snippets"])  # type: ignore[index]
        # Market
        market_res = m_chain(s.get("domain") or "", name)
        market_text = market_res.get("text") if isinstance(market_res, dict) else market_res
        if isinstance(market_res, dict):
            if market_res.get("sources"):
                s.setdefault("sources", []).extend(market_res["sources"])  # type: ignore[index]
            if market_res.get("snippets"):
                s.setdefault("snippets", []).extend(market_res["snippets"])  # type: ignore[index]
        # Competitors use full candidate list
        comp_res = c_chain(s.get("domain") or "", cands)
        comp_text = comp_res.get("text") if isinstance(comp_res, dict) else comp_res
        if isinstance(comp_res, dict):
            if comp_res.get("sources"):
                s.setdefault("sources", []).extend(comp_res["sources"])  # type: ignore[index]
            if comp_res.get("snippets"):
                s.setdefault("snippets", []).extend(comp_res["snippets"])  # type: ignore[index]
        # Decision
        out = d_chain(tech_text or "", market_text or "", comp_text or "")
        rec = {
            "name": name,
            "score": out.get("score"),
            "verdict": out.get("verdict"),
            "rationale": out.get("rationale"),
        }
        results.append(rec)

    # Aggregate results
    s["decisions"] = results
    recommended = [r for r in results if str(r.get("verdict")).lower() == "recommend"]
    s["recommended"] = recommended
    # For graph branching, treat as recommend if any are recommended else pass
    if recommended:
        s["decision"] = "recommend"
        s["score"] = max((r.get("score") or 0) for r in recommended)
        s["rationale"] = "; ".join([str(r.get("rationale") or "") for r in recommended])[:800]
    else:
        s["decision"] = "pass"
        s["score"] = max((r.get("score") or 0) for r in results) if results else 0
        s["rationale"] = "; ".join([str(r.get("rationale") or "") for r in results])[:800]
    return s


def n_report(s: S):
    # Compose full report using LLM to better match requested outline
    try:
        from agents.report import compose_investment_brief

        md = compose_investment_brief(s)
        s["report_path"] = write_text(str(BASE / "outputs" / "investment_report.md"), md)
    except Exception:
        # Fallback to template formatter if compose fails
        s["report_path"] = write_report(
            verdict=s.get("decision") or "hold",
            score=s.get("score") or 0,
            rationale=s.get("rationale") or "",
            tech=s.get("tech") or "",
            market=s.get("market") or "",
            comp=s.get("comp") or "",
            actions="추가 레퍼런스/실사용 고객 MRR 증빙 요청",
            sources=list(dict.fromkeys(s.get("sources") or [])),
            candidates=s.get("candidates") or [],
            path=str(BASE / "outputs" / "investment_report.md"),
        )
    docx_path = write_docx_report(
        verdict=s.get("decision") or "hold",
        score=s.get("score") or 0,
        rationale=s.get("rationale") or "",
        tech=s.get("tech") or "",
        market=s.get("market") or "",
        comp=s.get("comp") or "",
        actions="추가 레퍼런스/실사용 고객 MRR 증빙 요청",
        sources=s.get("sources") or [],
        path=str(BASE / "outputs" / "investment_report.docx"),
    )
    if docx_path:
        s["report_docx_path"] = docx_path
    readme_md = generate_project_readme_md(s)
    # Save to outputs and project root for presentation
    write_text(str(BASE / "outputs" / "README.md"), readme_md)
    write_text(str(BASE / "README.md"), readme_md)
    log_run(PG_ENGINE, s)
    return s


def build_state_graph():
    g = StateGraph(S)
    g.add_node("startup_search", n_scout)
    g.add_node("tech_summary", n_tech)
    g.add_node("market_eval", n_market)
    g.add_node("competitor_analysis", n_comp)
    g.add_node("investment_decision", n_decision)
    g.add_node("report_writer", n_report)

    g.set_entry_point("startup_search")
    g.add_edge("startup_search", "tech_summary")
    g.add_edge("tech_summary", "market_eval")
    g.add_edge("market_eval", "competitor_analysis")
    g.add_edge("competitor_analysis", "investment_decision")

    def after_decision(s: S):
        v = (s.get("decision") or "").lower()
        if v in ("recommend", "invest"):
            return "invest"
        if v == "hold":
            return "hold"
        return END

    g.add_conditional_edges(
        "investment_decision",
        after_decision,
        {"invest": "report_writer", "hold": "startup_search", END: END},
    )
    g.add_edge("report_writer", END)
    return g


def build_graph():
    return build_state_graph().compile()


def save_graph_png(path: Path) -> Optional[str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Try using langchain_teddynote helper first
    try:
        from langchain_teddynote.graphs import visualize_graph  # type: ignore

        visualize_graph(build_state_graph(), filename=str(path))  # type: ignore[call-arg]
        return str(path)
    except Exception:
        pass
    # Fallback to LangGraph's built-in mermaid renderer
    try:
        app = build_graph()
        g = app.get_graph()
        # Newer versions
        if hasattr(g, "draw_mermaid_png"):
            g.draw_mermaid_png(output_file_path=str(path))  # type: ignore[attr-defined]
            return str(path)
        if hasattr(g, "draw_png"):
            g.draw_png(output_file_path=str(path))  # type: ignore[attr-defined]
            return str(path)
    except Exception:
        return None
    return None
    return g.compile()


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--domain", default="물류/유통")
    p.add_argument("--query", default="신선식품 라스트마일 냉장 물류 자동화")
    p.add_argument("--stream", action="store_true", help="Stream LangGraph updates with tqdm progress")
    p.add_argument("--trace", action="store_true", help="Enable LangSmith tracing")
    p.add_argument("--project", default="InvestAgent", help="LangSmith project name")
    p.add_argument("--viz", action="store_true", help="Save graph PNG to outputs/graph.png")
    args = p.parse_args()

    if args.trace:
        os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
        os.environ.setdefault("LANGCHAIN_PROJECT", args.project)

    app = build_graph()
    state: S = {
        "domain": args.domain,
        "query": args.query,
        "target": None,
        "tech_raw": None,
        "tech": None,
        "market": None,
        "comp": None,
        "decision": None,
        "score": None,
        "rationale": None,
        "sources": [],
        "report_path": None,
        "report_docx_path": None,
        "candidates": None,
        "cand_idx": 0,
    }

    def _summarize_node(node_name: str, st: dict) -> str:
        try:
            if node_name == "startup_search":
                tgt = st.get("target")
                return f"target={tgt or '-'}"
            if node_name == "tech_summary":
                t = (st.get("tech") or "").strip().splitlines()
                return f"tech={' '.join(t[:1])[:80]}" if t else "tech=-"
            if node_name == "market_eval":
                m = (st.get("market") or "").strip().splitlines()
                return f"market={' '.join(m[:1])[:80]}" if m else "market=-"
            if node_name == "competitor_analysis":
                c = (st.get("comp") or "").splitlines()
                rows = sum(1 for ln in c if '|' in ln)
                return f"competitors_rows={rows}"
            if node_name == "investment_decision":
                return f"verdict={st.get('decision')} score={st.get('score')}"
            if node_name == "report_writer":
                return f"report={st.get('report_path')}"
        except Exception:
            pass
        return "-"

    if args.stream:
        try:
            from tqdm import tqdm
        except Exception:
            tqdm = None  # type: ignore

        # Initialize with expected nodes; will grow if loops occur
        expected_nodes = 6
        pbar = tqdm(total=expected_nodes, unit="node", desc="Pipeline", dynamic_ncols=True) if 'tqdm' in globals() and tqdm else None
        final_state = None
        for updates in app.stream(state, stream_mode="updates", config={"recursion_limit": 50}):
            for node_name, delta in updates.items():
                if node_name == "__end__":
                    if isinstance(delta, dict) and "value" in delta:
                        final_state = delta["value"]
                    else:
                        final_state = delta
                    continue
                summary = _summarize_node(node_name, delta if isinstance(delta, dict) else {})
                if pbar:
                    pbar.update(1)
                    # If loops push beyond initial total, extend
                    if pbar.n > pbar.total:
                        pbar.total = pbar.n
                        pbar.refresh()
                    pbar.set_postfix_str(f"{node_name} | {summary}")
                else:
                    print(f"[node] {node_name} :: {summary}")
        if pbar:
            pbar.close()
        if isinstance(final_state, dict):
            out = final_state
        else:
            out = None
            for val in app.stream(state, stream_mode="values", config={"recursion_limit": 50}):
                out = val
            if out is None:
                out = {}
    else:
        out = app.invoke(state, config={"recursion_limit": 50})

    if args.viz:
        png = save_graph_png(BASE / "outputs" / "graph.png")
        if png:
            print(f"Graph image saved: {png}")

    print("Decision:", out.get("decision"))
    if out.get("report_path"):
        print("Report:", out["report_path"])  # type: ignore[index]
