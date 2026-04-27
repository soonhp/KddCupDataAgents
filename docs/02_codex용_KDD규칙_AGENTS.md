# AGENTS.md (KDD Cup 2026 Data Agents 규칙 반영 템플릿)

> 목적: Codex/에이전트가 대회 규칙을 위반하지 않도록 실행 규칙을 강제한다.

## Scope
- 이 파일이 위치한 디렉터리 하위 전체.

## Runtime & I/O Rules
1. 입력 데이터는 `/input/task_<id>/` 하위에서 읽는다.
2. 참가 코드(Agent)는 `/input`의 모든 task를 순차 처리할 수 있어야 한다.
3. 각 task 결과는 `/output/task_<id>/prediction.csv`에 기록한다.
4. `/input`은 read-only로 간주하고 절대 수정하지 않는다.

## Data Handling Rules
1. `task.json`에서 최소 `task_id`, `difficulty`, `question`을 읽는다.
2. `context/` 하위 데이터 소스는 고정되지 않으므로 동적으로 탐색한다.
3. 파일/테이블 경로 하드코딩 금지.

## Model Invocation Rules (중요)
1. 모델 호출 정보는 반드시 환경변수에서 읽는다.
   - `MODEL_API_URL`
   - `MODEL_API_KEY`
   - `MODEL_NAME` (평가 시 `qwen3.5-35b-a3b`)
2. API URL/Key를 코드, 설정파일, Docker 이미지에 하드코딩 금지.
3. 공식 평가에서는 주 추론 모델을 별도 LLM으로 대체 금지.

## Submission & Container Rules
1. 제출물은 Docker 이미지 기준으로 재현 가능해야 한다.
2. 런타임 제한(시간/메모리)을 고려한 안전한 timeout/oom 처리 포함.
3. 로그는 추적 가능하도록 task 단위로 남긴다.

## Output Contract Rules
1. `prediction.csv` 컬럼명/행 형식은 문제 요구사항과 정확히 일치해야 한다.
2. 타입 정규화(숫자/문자열/날짜/시간) 수행 후 저장한다.
3. 불확실한 경우에도 빈 출력이 아닌, 근거 기반 최선 답안을 제출한다.

## Prohibited Behaviors
1. 평가 환경 비밀값/API 정보 추정·노출 시도 금지.
2. 규정 외 네트워크/리소스 사용 시도 금지.
3. 데이터 누수 또는 정답 파일 의존 로직 금지.

## Engineering Checklist (PR 전 필수)
- [ ] `/input` read-only 준수 확인
- [ ] `context/` 동적 탐색 확인
- [ ] 환경변수 기반 모델 호출 확인
- [ ] `prediction.csv` 포맷 검증 통과
- [ ] timeout/예외 처리 검증
- [ ] task 단위 trace/log 저장 확인
