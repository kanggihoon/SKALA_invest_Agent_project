from pathlib import Path


# Defaults (used if no external prompt file is present)
SCOUT_SYS_DEFAULT = (
    "You discover startups in the configured domain. "
    "Return a ranked list with name, one-liner, url."
)

TECH_SYS_DEFAULT = (
    "Summarize core tech, components, moat, risks ONLY from the given context."
)

MARKET_SYS_DEFAULT = (
    "Extract TAM/SAM/SOM estimates, segments, channels, regulation, unit economics from context."
)

COMP_SYS_DEFAULT = (
    "Compare competitors and produce a Markdown table (Company|Product|Moat|Price|KPI|Notes)."
)

DECISION_SYS_DEFAULT = (
    """Score with (Team, Tech, Market, Moat, Traction) each 0~20. Output JSON:
{{"score": int, "verdict": "recommend|hold|pass", "rationale": "...", "missing": ["..."]}}
"""
)

REPORT_TMPL_DEFAULT = """# 투자 보고서
## 최종 판단
{verdict} (점수 {score})

## 판단 근거
{rationale}

## 핵심 기술 요약
{tech}

## 시장 분석
{market}

## 경쟁사 비교
{comp}

## 후보별 핵심 기술(스카우트)
{candidates_tech}

## 보류 시 후속 액션
{actions}

## 출처
{sources}
"""


BASE = Path(__file__).resolve().parents[1]
PROMPTS_DIR = BASE / "prompts"


def _read_text(p: Path) -> str | None:
    try:
        if p.exists():
            return p.read_text(encoding="utf-8")
    except Exception:
        return None
    return None


def _escape_curly(text: str) -> str:
    # Prevent ChatPromptTemplate from treating JSON braces as variables.
    # System prompts typically don't need template vars; escape all braces.
    return text.replace("{", "{{").replace("}", "}}")


def system_prompt(name: str, default_text: str) -> str:
    # Prefer explicit .system.md but also allow plain .md
    for candidate in [PROMPTS_DIR / f"{name}.system.md", PROMPTS_DIR / f"{name}.md"]:
        t = _read_text(candidate)
        if t:
            return _escape_curly(t)
    return _escape_curly(default_text)


def config_text(name: str) -> str | None:
    """Read optional YAML/MD config for an agent and return as escaped text.

    Supported names: {name}.config.yaml | {name}.config.yml | {name}.config.md
    Returns None if no config file exists.
    """
    for candidate in [
        PROMPTS_DIR / f"{name}.config.yaml",
        PROMPTS_DIR / f"{name}.config.yml",
        PROMPTS_DIR / f"{name}.config.md",
    ]:
        t = _read_text(candidate)
        if t:
            return _escape_curly(t)
    return None


def report_template(default_text: str = REPORT_TMPL_DEFAULT) -> str:
    t = _read_text(PROMPTS_DIR / "report.template.md")
    return t or default_text


def project_readme_prompt() -> str:
    # Optional custom prompt to generate a project README via LLM
    t = _read_text(PROMPTS_DIR / "project_readme.system.md")
    return t or (
        "You are an assistant that writes a concise, clear project README for an investment scouting pipeline. "
        "Summarize the run (domain, query, target, verdict, score) and briefly describe each step's outputs. "
        "Use Markdown with sections: Overview, Run Summary, Tech, Market, Competitors, Decision, Files."
    )
