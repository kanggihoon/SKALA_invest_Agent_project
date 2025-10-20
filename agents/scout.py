import json
from typing import Dict

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from rag.prompts import system_prompt, SCOUT_SYS_DEFAULT, config_text

def _retrieve(retriever, query: str):
    try:
        return retriever.invoke(query)
    except Exception:
        return retriever.get_relevant_documents(query)


def scout_chain(retriever, model: str = "gpt-4o-mini"):
    sys_msg = system_prompt("startup_search", SCOUT_SYS_DEFAULT)
    cfg = config_text("startup_search")
    msgs = [("system", sys_msg)] + ([("system", f"Config:\n{cfg}")] if cfg else []) + [
        (
            "human",
            "Domain={domain}\nQuery={query}\nContext:\n{ctx}\nReturn top 5 as JSON list.",
        )
    ]
    prompt = ChatPromptTemplate.from_messages(msgs)
    llm = ChatOpenAI(model=model, temperature=0)

    def run(domain: str, query: str) -> Dict:
        # Strengthen retrieval with explicit unified keywords
        composed = f"{domain} AI 인공지능 머신러닝 ML LLM 물류 유통 logistics 'supply chain' SCM {query}"
        docs = _retrieve(retriever, composed)
        ctx = "\n\n".join(d.page_content[:1000] for d in docs)
        out = (prompt | llm).invoke({"domain": domain, "query": query, "ctx": ctx}).content

        def _normalize_item(item):
            try:
                if isinstance(item, dict):
                    key_map = {
                        "name": ["name", "company", "회사명", "기업명", "스타트업"],
                        "tech": ["tech", "기술", "핵심기술", "설명", "요약"],
                        "url": ["url", "link", "웹사이트", "홈페이지"],
                    }
                    norm = {}
                    for k, al in key_map.items():
                        for a in al:
                            if a in item and item[a]:
                                norm[k] = str(item[a]).strip()
                                break
                    if norm.get("name"):
                        norm.setdefault("tech", "")
                        norm.setdefault("url", "")
                        return norm
            except Exception:
                pass
            return {"name": str(item).strip(), "tech": "", "url": ""}

        def _extract_list(parsed):
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict):
                for key in ["items", "results", "companies", "startups", "후보", "목록"]:
                    val = parsed.get(key)
                    if isinstance(val, list):
                        return val
            return []

        data = []
        try:
            data = json.loads(out)
        except Exception:
            start, end = out.find("["), out.rfind("]")
            if start != -1 and end != -1:
                try:
                    data = json.loads(out[start : end + 1])
                except Exception:
                    data = []

        raw_list = _extract_list(data)
        candidates = []
        for item in raw_list:
            cand = _normalize_item(item)
            if cand.get("name"):
                candidates.append(cand)
            if len(candidates) >= 3:
                break
        # Filter: unified keyword list (OR matching)
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
        def _ok(c: Dict) -> bool:
            t = (c.get("tech") or "").lower()
            return any(k in t for k in kw)
        filtered = [c for c in candidates if _ok(c)]
        if filtered:
            candidates = filtered[:3]
        # pick first candidate as target
        target = candidates[0]["name"] if candidates else None
        tech_text = candidates[0]["tech"] if candidates else None
        sources = [d.metadata.get("source") or d.metadata.get("file_path") for d in docs[:5]]
        return {
            "target": target,
            "tech_raw": tech_text,
            "candidates": candidates,
            "sources": [s for s in sources if s],
        }

    return run
