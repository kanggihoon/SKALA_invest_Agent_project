from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from rag.prompts import system_prompt, TECH_SYS_DEFAULT, config_text


def tech_chain(retriever, model: str = "gpt-4o-mini"):
    # System prompt can be replaced by prompts/tech_summary.system.md (JSON-only spec allowed)
    sys_msg = system_prompt("tech_summary", TECH_SYS_DEFAULT)
    cfg = config_text("tech_summary")
    msgs = [("system", sys_msg)] + ([("system", f"Config:\n{cfg}")] if cfg else []) + [
        (
            "human",
            "Company={name}\nContext:\n{ctx}\n반드시 지시를 따르고 JSON만 출력하라.",
        ),
    ]
    prompt = ChatPromptTemplate.from_messages(msgs)
    llm = ChatOpenAI(model=model, temperature=0)

    def run(name: str, query: str, tech_raw: str | None = None):
        try:
            docs = retriever.invoke(f"{name} {query}")
        except Exception:
            docs = retriever.get_relevant_documents(f"{name} {query}")
        parts = []
        if tech_raw:
            parts.append(f"[DB] {tech_raw}")
        parts.extend(d.page_content[:1000] for d in docs)
        ctx = "\n\n".join(parts)
        out = (prompt | llm).invoke({"name": name, "ctx": ctx}).content
        srcs = []
        snips = []
        for d in docs[:6]:
            s = d.metadata.get("source") or d.metadata.get("file_path")
            if s:
                srcs.append(s)
            snips.append({"src": s or "", "text": d.page_content[:400]})
        return {"text": out, "sources": list(dict.fromkeys([s for s in srcs if s])), "snippets": snips}

    return run
