from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from rag.prompts import system_prompt, MARKET_SYS_DEFAULT, config_text


def market_chain(retriever, model: str = "gpt-4o-mini"):
    sys_msg = system_prompt("market_eval", MARKET_SYS_DEFAULT)
    cfg = config_text("market_eval")
    msgs = [("system", sys_msg)] + ([("system", f"Config:\n{cfg}")] if cfg else []) + [
        (
            "human",
            "Domain={domain}\nTargets={name}\nContext:\n{ctx}\nReturn concise bullets, include numbers if present.",
        ),
    ]
    prompt = ChatPromptTemplate.from_messages(msgs)
    llm = ChatOpenAI(model=model, temperature=0)

    def run(domain: str, name: str):
        try:
            docs = retriever.invoke(f"{domain} {name} market size")
        except Exception:
            docs = retriever.get_relevant_documents(f"{domain} {name} market size")
        ctx = "\n\n".join(d.page_content[:1000] for d in docs)
        out = (prompt | llm).invoke({"domain": domain, "name": name, "ctx": ctx}).content
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
