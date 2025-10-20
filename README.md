# AI Startup Investment Evaluation Agent

> **목적**: 물류/유통 도메인 스타트업을 중심으로, 기술성·시장성·경쟁력·리스크를 다각도로 평가해 **투자 판단**과 **보고서 자동 생성**을 수행하는 Multi‑Agent 시스템입니다. 코어 프레임은 **LangGraph**, 검색·근거 주입은 **Agentic RAG**로 구성합니다.

---

## 1) 한눈에 보기 (Overview)
- **Workflow**: Startup scouting → Tech summary → Market evaluation → Competitor analysis → Investment decision → (Hold loop or Report export)
- **핵심 가치**
  - 자료 기반(보고서/기사/PDF)의 **자동 정보 추출**과 **근거 중심 평가지표** 수립
  - 루프 기반 판단 보정(Hold 시 재탐색)으로 누락 정보 보완
  - **README/Investment Brief** 등 산출물 자동화

---

## 2) Agent 구성 (How we structure the agents)
- **Agent : Startup Scouting**
  - 입력: 도메인 키워드, 기존 DB 요약, 검색 의도
  - 출력: 후보 스타트업 목록, 핵심 기술/제품 요약(raw 메모 포함)
- **Agent : Tech Summary**
  - 입력: 스카우팅 결과 + RAG 컨텍스트
  - 출력: 기술 요약(핵심 기술·차별화·모델/데이터·IP), 기술 성숙도(TRL) 추정
- **Agent :  Market Evaluation**
  - 입력: 산업 리포트/뉴스 RAG 컨텍스트
  - 출력: 시장 크기/TAM·CAGR·수익화 모델, 규제/리스크, GTM 요약
- **Agent : Competitor Analysis**
  - 입력: 경쟁사 문서 RAG 컨텍스트
  - 출력: 주요 경쟁사 3~5개, 포지셔닝(가격·성능·세그먼트), 우위/열위
- **Agent : Investment Decision (Judge)**
  - 입력: DB에 축적된 Tech/Market/Competition 결과
  - 출력: **recommend/hold/pass** + 점수(0–100) + rationale
  - 분기: `hold` → 결측/불확실 항목을 쿼리로 반영하여 **Scouting으로 루프백**
- **Agent : Report Generator**
  - 입력: 최종 판단 및 근거
  - 출력: `outputs/investment_report.md(.docx)` / 프로젝트 `README.md`

> 각 Agent는 개별 프롬프트와 툴 체인을 갖고, **LangGraph** 상에서 **Node**로 배치됩니다.

---

## 3) 시스템 동작 (How it works end‑to‑end)
1. **도큐먼트 적재(Ingestion)**: `data/` 폴더의 PDF/웹캡처/CSV 등을 로더로 읽고, 청크 단위로 전처리
2. **임베딩 & 인덱스**: `multilingual-e5-base` 임베딩 → **Chroma** 컬렉션(tech/market/competitors/scout) 생성
3. **LangGraph 실행**
   - (병렬) **Tech Summary** 와 **Market/Competitor** 에이전트가 각자 필요한 RAG 컨텍스트를 조회
   - (직렬) **Investment Decision** 노드에서 점수화·판단
   - (분기) `hold` 시 **누락 신호를 질의어로 구성**해 **Startup Scouting**으로 피드백 루프
4. **저장 & 산출물**: 각 단계 결과는 **PostgreSQL**에 upsert, 최종 리포트/README를 파일로 출력

---

## 4) RAG 적용 위치와 동작 (Where RAG is used)
- **어디서?**
  - Scouting/Tech/Market/Competitor 단계에서 **문서 근거를 검색**해 요약·분석에 투입
- **어떻게?**
  1) **Chunking**: 문서 길이/섹션기반 청크(문단·표 캡션 포함)
  2) **Embedding**: `multilingual-e5-base` (cosine)
  3) **Retrieve**: 질의 재작성(Multi‑Query) → Top‑k(예: 6–12) 검색
  4) **Prompt Compose**: *retrieved contexts + DB 필드*를 시스템 프롬프트에 주입
  5) **Guardrails**: 출처 메타데이터(문서명/페이지/URL)와 함께 요약·근거를 출력
- **Agentic 포인트**
  - Judge가 `hold`를 내리면 **결핍 정보 키워드**를 자동 생성 → **재검색 쿼리**로 사용 → **루프 강화**

---

## 5) 저장소 설계 (DB & VectorDB)
- **RDBMS — PostgreSQL (`db/startups`)**
  - 스키마 예시
    - `id, name, domain, tech_raw, tech_summary, market_eval, competitor_analysis, decision, score, rationale, updated_at`
  - 흐름
    1) Scouting: `name, tech_raw` upsert
    2) Tech/Market/Competitor: 해당 필드 업데이트
    3) Decision: `decision/score/rationale` 기록
- **VectorDB — Chroma**
  - 컬렉션: `tech`, `market`, `competitors`, `scout`
  - 임베딩: `intfloat/multilingual-e5-large` (또는 base), metric: cosine
  - 메타: `source, title, section, page, url, timestamp`

---

## 6) LangGraph 설계 (Graph & Nodes)
- **State**: `query, candidate_list, db_record, tech_summary, market_eval, competitor_analysis, decision, score, rationale, missing_signals`
- **Nodes**
  - `startup_search` → `tech_summary` → (`market_eval` || `competitor_analysis`) → `investment_decision` → `report_export`
- **Edges**
  - 기본: 직렬 + **중간 병렬(Fan‑out/Fan‑in)**
  - 조건: `if decision==hold` → `startup_search` (루프)
- **장점**
  - 단계별 실패 격리, 재시도/분기 제어, 로깅 일관성
  <img width="269" height="753" alt="graph (3)" src="https://github.com/user-attachments/assets/71e66a40-84b2-4a67-ac55-3e542f17f81f" />

---

## 7) Tech Stack
- **Framework**: LangGraph, LangChain, Python
- **LLM**: GPT‑4o‑mini (OpenAI API)
- **Retrieval**: Chroma (FAISS 대체 가능)
- **Embedding**: `multilingual-e5-base` (HuggingFace)
- **DB**: PostgreSQL (SQLAlchemy로 연결)
- **Etc.**: python‑dotenv, `python-docx`(선택), `psycopg2-binary`

---

## 8) 디렉토리 & 실행
```
data/            # 도메인 문서 (tech/market/competitors/scout)
rag/             # 로더, 인덱스, RAG 유틸
prompts/         # 시스템/유저 프롬프트 템플릿
agents/          # 단계별 Agent
graph/           # LangGraph 엔트리(app.py)
db/              # PostgreSQL 로거
outputs/         # 리포트 산출물
```
**.env**
```
OPENAI_API_KEY=
LANGCHAIN_TRACING_V2=false
LANGCHAIN_PROJECT=SKALA
LANGCHAIN_ENDPOINT=
LANGCHAIN_API_KEY=
TAVILY_API_KEY=
DB_NAME=
DB_USER=
DB_PASSWORD=
DB_HOST=
DB_PORT=
```
**Run**
```bash
python SCM/invest-agent/graph/app.py
```

---

## 9) 산출물 (Artifacts)
- `outputs/investment_report.md` : **Investment Brief** (Verdict/Score/Rationale/Tech/Market/Competition)
- `outputs/investment_report.docx` : 동명 Word 리포트(옵션)
- `outputs/README.md` : 프로젝트 실행 요약(환경/파이프라인/결과 하이라이트)

---

## 10) 협업 가이드 (Git & 팀 운영)
- **브랜치 전략**: `main`(안정) / `dev`(통합) / `feature/*`(에이전트·RAG·DB 별)
- **PR 규칙**: 그래프 변경은 **Mermaid/다이어그램**과 함께 PR; 프롬프트 변경은 **diff와 샘플 출력** 첨부
- **데이터/키 관리**: `.env`는 로컬 전용, 공유는 `.env.sample`로 대체

---

## 11) 데모 시나리오 (예)
1) `도메인=물류/유통`, 키워드: “AI Fulfillment”, “Route Optimization”
2) Scouting: 후보 5개 도출, 각사 one‑liner & 링크
3) Tech/Market/Competitor: 근거 6–12개 검색/요약
4) Decision: **Score 85, recommend**, 리포트/README 생성

---

### Contributors
- 강기훈: rag 설계 및 구현, agent 병합 및 수정, 보고서 생성 
- 김채연: 스타트업 탐색 agent 기술요약 agent
- 이광호: 시장평가 agent, 경쟁사 비교 agent
- 이재하: 스타트업 탐색 agent 기술요약 agent

---
