# AGENTS.md

이 저장소는 KDD Cup 2026 DataAgent-Bench 대응을 위한 Codex Cloud 작업 저장소이다. 모든 에이전트와 자동화 작업은 아래 규칙을 우선 적용한다.

## 1. 실행 환경 원칙

- 작업은 로컬 머신이 아니라 Codex Cloud 환경에서 수행한다.
- 로컬 경로, 로컬 API key, 개인 PC에만 존재하는 파일에 의존하지 않는다.
- 모든 재현 가능한 실험은 GitHub 레포, Dockerfile, 설정 파일, 실행 스크립트로 남긴다.
- Slack, GitHub, Notion MCP는 협업/기록/리뷰용으로 사용하되, 평가 환경의 비밀값이나 대회 비공개 데이터를 외부로 노출하지 않는다.

## 2. 공식 대회 규칙 우선순위

- 공식 규칙 원문은 https://dataagent.top/rules 를 기준으로 한다.
- 공식 rules 문서와 이 파일이 충돌하면 공식 rules 문서를 우선한다.
- 공식 rules 변경 가능성이 있으므로, 제출 전에는 반드시 최신 rules를 다시 확인한다.
- 입력 데이터는 read-only로 취급한다.
- 정답 파일, hidden output, leaderboard leakage에 의존하는 로직을 작성하지 않는다.

## 3. 평가 환경 I/O 계약

- 평가 시 `/input`은 read-only mount이다.
- 평가 시 `/output`은 prediction 결과를 쓰는 read-write mount이다.
- 평가 시 `/logs`는 runtime log를 쓰는 read-write mount이다.
- 컨테이너는 `/input` 아래 모든 `task_<id>` 하위 디렉터리를 순회해야 한다.
- 각 task는 `/input/task_<id>/task.json`과 `/input/task_<id>/context/`를 가진다고 가정한다.
- 각 결과는 `/output/task_<id>/prediction.csv`에 작성한다.
- parent `/output`은 평가 시스템이 만든다고 가정하되, task별 output directory 존재 여부는 안전하게 확인한다.

## 4. 데이터 형식 규칙

- `task.json`에는 최소 `task_id`, `difficulty`, `question`이 있다.
- `context/` 하위에는 `csv/`, `db/`, `json/`, `doc/`, `knowledge.md` 중 일부가 존재할 수 있다.
- 모든 context 구조는 task마다 다르므로 하드코딩하지 않고 동적으로 탐색한다.
- CSV, JSON, SQLite/DB, Markdown/문서, knowledge 파일을 모두 처리할 수 있어야 한다.

## 5. 출력 계약

- 최종 출력은 UTF-8 CSV인 `prediction.csv`이다.
- 첫 행은 header이다. 공식 scoring은 column name보다 column content matching을 중시하지만, 사람이 읽기 쉬운 header를 유지한다.
- row order와 column order에 의존하지 않는 scoring을 고려해, 불필요한 extra column을 만들지 않는다.
- numeric value는 충분한 precision을 유지한다. 공식 평가는 2 decimal normalization을 적용할 수 있다.
- null 값은 빈 문자열로 쓰는 것을 기본값으로 한다.
- 이름 필드는 full name 또는 first/last split 허용 가능성이 있으나, 문제 요구사항을 우선한다.

## 6. 모델 호출 규칙

- 공식 평가 모델 호출 정보는 반드시 환경변수에서 읽는다.
  - `MODEL_API_URL`
  - `MODEL_API_KEY`
  - `MODEL_NAME`
- 평가 환경의 모델 서비스는 OpenAI Chat Completions 호환 endpoint라고 가정한다.
- 개발 환경에서 다른 모델을 테스트하더라도, 평가 모드에서는 반드시 주입된 환경변수만 사용한다.
- API URL, API Key, credential, token을 코드, 설정파일, Docker image, Slack, Notion, GitHub commit에 하드코딩하지 않는다.
- 평가 중 외부 인터넷 접근 또는 별도 LLM 서비스 호출을 시도하지 않는다.

## 7. 리소스/런타임 제약

- 공식 평가 리소스는 CPU 16 vCPU, x86-64, Memory 64GB RAM, GPU 없음으로 가정한다.
- 전체 task 처리 runtime limit은 12시간이다. per-task가 아니라 전체 제한이다.
- timeout/OOM 발생 시 전체 제출 결과가 무효화될 수 있으므로, task별 timeout, graceful SIGTERM 처리, partial result 저장 전략을 둔다.
- 병렬 처리는 task 단위로 하되, memory spike를 피하기 위해 worker 수를 보수적으로 제한한다.

## 8. 에이전트 팀 역할

- PM Agent: 목표, 우선순위, 일정, 리스크 관리.
- Planner Agent: task 분해, 실행 DAG, 도구 선택 계획 수립.
- Data Profiling Agent: 파일 구조, 스키마, 결측, 키, 단위 점검.
- SQL Analyst Agent: SQLite/DB 질의, 조인, 집계, 검증.
- Python Analyst Agent: pandas/polars/duckdb 기반 계산, 통계, 시계열 처리.
- Doc Reasoning Agent: 문서/텍스트 기반 조건 추출 및 규칙화.
- Verifier Agent: 독립 경로로 결과 검증, 반례 탐색, sanity check.
- Answer Contract Agent: 최종 CSV 포맷, 타입, 제출 계약 검증.

## 9. 기본 워크플로우

1. task.json을 읽고 질문의 요구 출력 형태를 먼저 정의한다.
2. context 전체를 탐색해 파일 타입, 스키마, 후보 키를 기록한다.
3. SQL-first, Python-first, Document-first 중 경로를 선택한다.
4. 중간 결과를 구조화된 JSON 또는 CSV로 남긴다.
5. 최소 한 번 이상 독립 검증 경로를 수행한다.
6. Answer Normalizer로 숫자/날짜/문자열을 정규화한다.
7. prediction.csv를 생성하고 컬럼/행/타입 검사를 통과시킨다.
8. 실험 결과와 실패 원인을 docs 또는 artifacts에 기록한다.

## 10. GitHub 작업 규칙

- main 브랜치에 직접 큰 변경을 누적하지 말고, 기능 단위 branch와 PR을 사용한다.
- 단, 저장소 초기화처럼 사용자가 명시한 경우에는 main에 최소 문서 파일을 커밋할 수 있다.
- PR에는 목적, 변경사항, 테스트 방법, 남은 리스크를 적는다.
- starter-kit 원본과의 차이는 문서화한다.
- 데이터셋, API key, 대용량 artifact는 Git에 커밋하지 않는다.

## 11. Slack 공유 규칙

- 주요 분석 결과, 실험 결과, 실패 원인, PR 링크는 Slack `#kdd-data-agents-team`에 공유한다.
- 공유 메시지는 결론, 근거, 다음 액션을 포함한다.
- 민감한 키나 비공개 데이터 샘플은 Slack에 붙여넣지 않는다.

## 12. Notion 기록 규칙

- 대회 분석, 실행 계획, 실험 결과, 데이터셋 인사이트는 Notion에 요약 문서로 남긴다.
- Notion 문서에는 레포 링크, PR 링크, 실행 커맨드, 관찰 결과, 다음 액션을 포함한다.

## 13. 구현 우선순위

1. starter-kit을 Codex Cloud에서 재현 실행한다.
2. 데이터셋 다운로드/마운트 방식을 정리한다.
3. Task Router, Schema Memory, Answer Normalizer를 구현한다.
4. SQL/Python dual verification을 구현한다.
5. 실패 taxonomy와 회귀 테스트셋을 만든다.
6. Docker 기반 제출 파이프라인을 정리한다.

## 14. 금지사항

- 평가 중 외부 인터넷 접근 금지.
- 평가 시스템의 injected model endpoint를 우회하는 별도 LLM 호출 금지.
- 평가 인프라 probing, 공격, container escape 시도 금지.
- `/input` 수정 금지.
- 환경변수 파괴 또는 변조 금지.
- 여러 팀 간 동일 Docker image 공유 금지.
- test set answer를 부정한 방식으로 획득하거나 사용하는 행위 금지.
- 수동 개입이 필요한 interactive runtime 금지.
- API key, token, credential 하드코딩 금지.
- 검증 없이 추측 기반 answer 생성 금지.
- 로컬 환경에서만 동작하는 경로/설정 커밋 금지.
