# AGENTS.md

이 저장소는 KDD Cup 2026 DataAgent-Bench 대응을 위한 Codex Cloud 작업 저장소이다. 모든 에이전트와 자동화 작업은 아래 규칙을 우선 적용한다.

## 1. 실행 환경 원칙

- 작업은 로컬 머신이 아니라 Codex Cloud 환경에서 수행한다.
- 로컬 경로, 로컬 API key, 개인 PC에만 존재하는 파일에 의존하지 않는다.
- 모든 재현 가능한 실험은 GitHub 레포, Dockerfile, 설정 파일, 실행 스크립트로 남긴다.
- Slack, GitHub, Notion MCP는 협업/기록/리뷰용으로 사용하되, 평가 환경의 비밀값이나 대회 비공개 데이터를 외부로 노출하지 않는다.

## 2. 대회 규칙 반영

- 공식 규칙 원문은 https://dataagent.top/rules 를 기준으로 한다.
- 단, 현재 이 파일은 커넥터가 직접 웹페이지를 읽지 못하는 환경에서 작성되었으므로, 공식 규칙 변경 시 반드시 사람이 원문과 대조해 갱신한다.
- 입력 데이터는 read-only로 취급한다.
- 정답 파일 또는 hidden output에 의존하는 로직을 작성하지 않는다.
- 공식 평가 모델, API URL, API Key는 코드에 하드코딩하지 않고 환경변수로만 주입한다.

## 3. 입출력 계약

- public demo 기준 starter-kit은 `data/public/input/task_<id>/task.json` 및 `context/`를 읽는다.
- hidden/evaluation 환경에서는 `/input/task_<id>/` 형태의 입력만 있다고 가정한다.
- 최종 결과는 task별 `prediction.csv`로 저장한다.
- 컬럼명, 행 수, 타입, 날짜/숫자/문자열 포맷은 문제 요구사항을 최우선으로 맞춘다.

## 4. 에이전트 팀 역할

- PM Agent: 목표, 우선순위, 일정, 리스크 관리.
- Planner Agent: task 분해, 실행 DAG, 도구 선택 계획 수립.
- Data Profiling Agent: 파일 구조, 스키마, 결측, 키, 단위 점검.
- SQL Analyst Agent: SQLite/DB 질의, 조인, 집계, 검증.
- Python Analyst Agent: pandas/polars/duckdb 기반 계산, 통계, 시계열 처리.
- Doc Reasoning Agent: 문서/텍스트 기반 조건 추출 및 규칙화.
- Verifier Agent: 독립 경로로 결과 검증, 반례 탐색, sanity check.
- Answer Contract Agent: 최종 CSV 포맷, 타입, 제출 계약 검증.

## 5. 기본 워크플로우

1. task.json을 읽고 질문의 요구 출력 형태를 먼저 정의한다.
2. context 전체를 탐색해 파일 타입, 스키마, 후보 키를 기록한다.
3. SQL-first, Python-first, Document-first 중 경로를 선택한다.
4. 중간 결과를 구조화된 JSON 또는 CSV로 남긴다.
5. 최소 한 번 이상 독립 검증 경로를 수행한다.
6. Answer Normalizer로 숫자/날짜/문자열을 정규화한다.
7. prediction.csv를 생성하고 컬럼/행/타입 검사를 통과시킨다.
8. 실험 결과와 실패 원인을 docs 또는 artifacts에 기록한다.

## 6. GitHub 작업 규칙

- main 브랜치에 직접 큰 변경을 누적하지 말고, 기능 단위 branch와 PR을 사용한다.
- PR에는 목적, 변경사항, 테스트 방법, 남은 리스크를 적는다.
- starter-kit 원본과의 차이는 문서화한다.
- 데이터셋, API key, 대용량 artifact는 Git에 커밋하지 않는다.

## 7. Slack 공유 규칙

- 주요 분석 결과, 실험 결과, 실패 원인, PR 링크는 Slack `#kdd-data-agents-team`에 공유한다.
- 공유 메시지는 결론, 근거, 다음 액션을 포함한다.
- 민감한 키나 비공개 데이터 샘플은 Slack에 붙여넣지 않는다.

## 8. Notion 기록 규칙

- 대회 분석, 실행 계획, 실험 결과, 데이터셋 인사이트는 Notion에 요약 문서로 남긴다.
- Notion 문서에는 레포 링크, PR 링크, 실행 커맨드, 관찰 결과, 다음 액션을 포함한다.

## 9. 구현 우선순위

1. starter-kit을 Codex Cloud에서 재현 실행한다.
2. 데이터셋 다운로드/마운트 방식을 정리한다.
3. Task Router, Schema Memory, Answer Normalizer를 구현한다.
4. SQL/Python dual verification을 구현한다.
5. 실패 taxonomy와 회귀 테스트셋을 만든다.
6. Docker 기반 제출 파이프라인을 정리한다.

## 10. 금지사항

- 공식 규칙 위반 가능성이 있는 네트워크 접근, 데이터 누수, 정답 파일 의존 로직 금지.
- API key, token, credential 하드코딩 금지.
- 검증 없이 추측 기반 answer 생성 금지.
- 로컬 환경에서만 동작하는 경로/설정 커밋 금지.
