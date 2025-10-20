import json
import re
from typing import Any, Dict

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from rag.prompts import system_prompt, DECISION_SYS_DEFAULT, config_text


def _safe_json(s: str) -> Dict[str, Any]:
    s = s.strip()
    s = re.sub(r"^```json|^```|```$", "", s, flags=re.IGNORECASE | re.MULTILINE).strip()
    start, end = s.find("{"), s.rfind("}")
    if start != -1 and end != -1:
        s = s[start : end + 1]
    return json.loads(s)


def decision_chain(model: str = "gpt-4o-mini"):
    sys_msg = system_prompt("decision", DECISION_SYS_DEFAULT)
    cfg = config_text("decision")
    msgs = [("system", sys_msg)] + ([("system", f"Config:\n{cfg}")] if cfg else []) + [
        (
            "human",
            "Tech:\n{tech}\n\nMarket:\n{market}\n\nCompetitors:\n{comp}\nReturn JSON only.",
        ),
    ]
    prompt = ChatPromptTemplate.from_messages(msgs)
    llm = ChatOpenAI(model=model, temperature=0)

    def run(tech: str, market: str, comp: str) -> Dict[str, Any]:
        raw = (prompt | llm).invoke({"tech": tech, "market": market, "comp": comp}).content
        return _safe_json(raw)

    return run
