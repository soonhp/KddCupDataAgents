# KDD Data Agents 작업 공유 문서

작성일: 2026-04-29

## 1. 이번 작업의 목적

KDD Data Agents 대회용 실행 파이프라인을 단순 제출 스크립트 수준에서 끝내지 않고, 다음과 같은 **운영 가능한 multi-agent evaluation pipeline**으로 단계적으로 고도화했다.

- task 특성 기반 라우팅
- schema memory/profiling
- output contract 기반 검증
- deterministic multi-agent review
- semantic sanity review
- repair planning
- safe repair execution
- retry brief generation

핵심 목표는 다음 두 가지였다.

1. **실패를 그냥 로그에 남기는 것이 아니라, 왜 실패했는지 구조적으로 설명할 수 있게 만들 것**
2. **안전하게 자동 수정 가능한 것은 수정하고, 남는 문제는 다음 solver pass용 retry brief로 넘길 것**

---

## 2. 지금까지 반영된 주요 단계

### 2.1 Task Router v2
`runner/task_intelligence.py`

기존의 단순 파일 타입 기반 라우팅에서 확장하여 아래 정보를 함께 본다.

- `task.json`의 `task_id`, `question`, `difficulty`
- context 내 CSV / DB / JSON / document / knowledge.md 존재 여부
- 질문 문장의 signal
  - SQL/table signal
  - Python/stat signal
  - document/rule signal

현재 route 후보

- `sql_first`
- `python_first`
- `document_first`
- `hybrid_sql_python`
- `hybrid_doc_table`

추가된 출력

- `recommended_tools`
- `risk_flags`
- route score / reasons

---

### 2.2 Schema Memory Profiling
`runner/task_intelligence.py`

context 파일의 구조를 후속 agent가 재활용할 수 있도록 `schema_hints`를 생성한다.

포함 내용

- CSV: header, sample row count
- JSON: top-level type, top-level keys
- SQLite: table / column 정보
- Markdown/TXT: preview

결과는 `schema_memory.json`으로 task log에 남긴다.

---

### 2.3 Prediction Verification Hardening
`runner/verification.py`

`prediction.csv`에 대한 generic CSV safety / quality 검증을 강화했다.

검사 항목 예시

- UTF-8 / CSV readability
- duplicate header
- header width / row width consistency
- suspicious traceback-like output
- single empty fallback answer
- 과도한 row / column / cell length

---

### 2.4 Task-specific Output Contract Extraction
`runner/verification.py`

`task.json` 또는 question에서 기대 output schema를 추론한다.

지원 항목

- `expected_columns`
- `output_schema`
- `answer_schema`
- `prediction_schema`
- question 내 `columns:` / `headers:` / `output fields:` 패턴
- `min_rows`, `max_rows`, `exact_columns`

이 contract는 verification 단계에서 실제 `prediction.csv`와 대조된다.

---

### 2.5 Deterministic Multi-Agent Review Loop
`runner/agent_review.py`

외부 LLM 호출 없이도 task 결과를 여러 agent 시각으로 독립 점검하도록 추가했다.

현재 review agent

- PM Agent
- Planner Agent
- Data Profiling Agent
- Verifier Agent
- Answer Contract Agent

각 agent는 task log에 독립 comment를 남긴다.

---

### 2.6 Deterministic Semantic Review Loop
`runner/semantic_review.py`

형식 검증을 통과했더라도 문제 의도와 결과 shape가 명백히 어긋나는 경우를 잡기 위한 sanity review를 추가했다.

현재 점검 예시

- numeric intent인데 숫자형 answer가 거의 없음
- compare / trend / by / per 계열인데 비교형 table output이 비어 있음
- document grounding signal이 있는데 문서 context가 없음
- hybrid route인데 tooling signal이 약함

출력

- semantic checks
- repair recommendations

---

### 2.7 Deterministic Repair Planner
`runner/repair_planner.py`

verification / semantic review / agent review 결과를 바탕으로 다음 실행 계획을 priority 기반 repair action queue로 만든다.

예시 action

- `fix_output_contract`
- `fix_task_contract`
- `recompute_numeric_answer`
- `regenerate_tabular_comparison`
- `restore_document_grounding`
- `expand_hybrid_tool_plan`

---

### 2.8 Deterministic Repair Executor
`runner/repair_executor.py`

repair plan 중 **안전하게 자동 적용 가능한 subset만 실제 반영**한다.

현재 자동 적용 범위

- expected output contract가 있고
- expected column width와 현재 width가 같을 때
- header rename만 안전하게 수행

중요 원칙

- answer value는 임의로 생성하지 않음
- 계산 결과를 지어내지 않음
- unsafe action은 `planned` 상태로 유지

repair execution 이후에는 아래를 재실행한다.

- verification
- semantic review
- agent review
- repair plan

---

### 2.9 Deterministic Retry Executor
`runner/retry_executor.py`

repair execution 이후에도 남은 문제를 다음 solver pass용 **retry brief**로 정리한다.

현재 retry focus 예시

- `output_contract`
- `numeric_recompute`
- `tabular_regeneration`
- `document_grounding`
- `hybrid_tooling`
- `verification`

중요 변경점

- 초기 구현은 `repair_execution_report.steps`만 보고 retry를 만들었음
- 이후 Codex review 피드백을 반영하여 **최신 `repair_plan` 기준으로 retry decision을 생성하도록 수정**함
- 따라서 safe repair 이후 이미 해결된 작업이 stale retry instruction으로 남지 않음

---

## 3. 현재 task 실행 흐름

현재 `runner/evaluation_runner.py` 기준 task 처리 흐름은 아래와 같다.

1. `task.json` / context profile 생성
2. route decision 생성
3. solver 실행 (`run_single_task`)
4. `prediction.csv` normalize
5. verification
6. semantic review
7. agent review
8. repair plan 생성
9. safe deterministic repair execution
10. repair가 실제 적용되면 검증/리뷰/repair plan 재계산
11. retry decision 생성
12. 모든 결과를 `task.log.json`에 기록

즉, 이제는 한 task에 대해 단순 success/fail만 남는 것이 아니라 아래 artifact가 함께 남는다.

- `schema_memory`
- `verification`
- `semantic_review`
- `agent_review`
- `repair_plan`
- `repair_execution`
- `retry_decision`
- `failure_taxonomy`

---

## 4. 품질 관련 이슈와 수정 이력

### 4.1 CI/Review 피드백 반영 사례

다음과 같은 실제 피드백을 받아 수정했다.

- `AgentReviewReport.all_passed`가 warning을 사실상 통과처럼 취급하던 문제 수정
- `task_contract_check`가 실행되지 않은 경우도 명시적 failure로 보이도록 수정
- blank CSV row에서 `shape_check`가 `IndexError`를 낼 수 있던 문제 수정
- retry decision이 stale repair step 기준으로 생성되던 문제 수정

즉, 파이프라인을 추가만 한 것이 아니라 리뷰/피드백을 통해 안정화까지 반복했다.

---

## 5. GitHub Actions 관련 메모

이번 작업 중 connector 상에서 특정 PR head commit에 대해 GitHub Actions status / workflow run이 보이지 않는 경우가 있었다.

현재 정리된 대응은 아래와 같다.

- CI workflow 파일(`.github/workflows/ci.yml`)에는 새 module / 새 test file을 계속 반영함
- compile 대상과 unittest discover 대상은 최신 상태로 유지함
- status API가 보이지 않는 경우에도 PR diff / code path / regression test consistency를 기준으로 subagent review 코멘트를 남김

즉, **workflow visibility 문제와 code correctness 검토를 분리해서 처리**했다.

---

## 6. 현재까지 추가된 대표 module 목록

- `runner/task_intelligence.py`
- `runner/verification.py`
- `runner/agent_review.py`
- `runner/semantic_review.py`
- `runner/repair_planner.py`
- `runner/repair_executor.py`
- `runner/retry_executor.py`

대표 테스트 확장

- `tests/test_task_intelligence.py`
- `tests/test_repair_executor.py`
- `tests/test_retry_executor.py`

---

## 7. 지금 시점의 한계

아직 아래는 남아 있다.

1. Retry decision이 생성되더라도 **실제 second-pass solver invocation**은 아직 없음
2. safe deterministic repair는 header rename 수준에 집중되어 있음
3. semantic review는 sanity layer이며, 실제 정답 의미 검증은 아님
4. task packaging / workflow visibility 문제는 운영 측면에서 추가 관찰 필요

---

## 8. 다음 추천 작업

다음으로 가장 자연스러운 작업은 아래 두 단계다.

### A. Retry Orchestrator 연결
- `retry_decision.should_retry == true` 인 경우
- 제한된 횟수 내에서
- `run_single_task` 재호출 또는 별도 orchestrator를 호출
- retry brief를 system prompt / execution context에 주입

### B. Repair-aware second pass
- route / schema memory / failed verification / semantic mismatch / repair plan / retry instruction을 묶어
- 다음 solver pass가 무엇을 고쳐야 하는지 명시적으로 이해하게 만들기

---

## 9. 팀원들이 바로 보면 좋은 포인트

팀원들이 코드를 볼 때는 아래 순서로 보면 이해가 쉽다.

1. `runner/evaluation_runner.py`
2. `runner/task_intelligence.py`
3. `runner/verification.py`
4. `runner/semantic_review.py`
5. `runner/agent_review.py`
6. `runner/repair_planner.py`
7. `runner/repair_executor.py`
8. `runner/retry_executor.py`

---

## 10. 한 줄 요약

이제 KDD Data Agents runner는 **실행 → 검증 → 의미 점검 → agent 리뷰 → repair 계획 → safe repair → retry brief 생성**까지 이어지는, 비교적 운영 가능한 deterministic evaluation pipeline으로 확장되었다.
