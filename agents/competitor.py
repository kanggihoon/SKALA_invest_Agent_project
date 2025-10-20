from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from rag.prompts import system_prompt, COMP_SYS_DEFAULT, config_text


def competitor_chain(retriever, model: str = "gpt-4o-mini"):
    sys_msg = system_prompt("competitor_analysis", COMP_SYS_DEFAULT)
    cfg = config_text("competitor_analysis")
    msgs = [("system", sys_msg)] + ([("system", f"Config:\n{cfg}")] if cfg else []) + [
        (
            "human",
            """
Domain={domain}
Candidates={candidates}
Header={header}
Context:
{ctx}

지시: 위 Header를 그대로 사용하여 표 머리말을 구성하고, 후보들끼리 직접 비교하라. 불확실한 값은 '불명'.
""",
        ),
    ]
    prompt = ChatPromptTemplate.from_messages(msgs)
    llm = ChatOpenAI(model=model, temperature=0)

    def run(domain: str, candidates):
        # Normalize names from candidates list[dict|str]
        names = []
        for c in candidates or []:
            if isinstance(c, dict):
                n = c.get("name") if hasattr(c, "get") else None  # type: ignore
                if n:
                    names.append(str(n))
            else:
                names.append(str(c))
        names = names[:3] if names else []
        header = "| 기준 | " + " | ".join(names) + " |" if names else "| 기준 | 후보A | 후보B | 후보C |"
        query = f"{domain} competitors " + " ".join(names) if names else domain
        try:
            docs = retriever.invoke(query)
        except Exception:
            docs = retriever.get_relevant_documents(query)
        ctx = "\n\n".join(d.page_content[:1200] for d in docs)
        out = (prompt | llm).invoke({
            "domain": domain,
            "candidates": ", ".join(names) if names else "",
            "header": header,
            "ctx": ctx,
        }).content
        # Try parse JSON
        parsed = None
        try:
            import json as _json

            parsed = _json.loads(out)
        except Exception:
            try:
                start, end = out.find("{"), out.rfind("}")
                if start != -1 and end != -1:
                    import json as _json

                    parsed = _json.loads(out[start : end + 1])
            except Exception:
                parsed = None
        srcs = []
        snips = []
        for d in docs[:6]:
            s = d.metadata.get("source") or d.metadata.get("file_path")
            if s:
                srcs.append(s)
            snips.append({"src": s or "", "text": d.page_content[:400]})
        return {"text": out, "json": parsed, "sources": list(dict.fromkeys([s for s in srcs if s])), "snippets": snips}

    return run
