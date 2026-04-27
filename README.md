# KddCupDataAgents

KDD Cup 2026 Data Agents 대회 대응을 위한 분석/전략 문서를 `docs/`에 정리했고, 실제 제출 가능한 **starter-kit 기반 runner + Docker 구조**를 추가했습니다.

## 문서 목록
- `docs/01_대회_심층분석_및_실행계획.md`
- `docs/02_codex용_KDD규칙_AGENTS.md`
- `docs/03_starterkit_실행결과_인사이트.md`
- `docs/04_데이터셋_분석과_최고득점_전략.md`
- `docs/05_노션_공유본.md`
- `docs/06_slack_공유메시지_초안.md`

## 추가된 실행 구조

### 1) 평가 runner (`runner/evaluation_runner.py`)
- `/input/task_<id>/task.json` 기준으로 task를 자동 탐색합니다.
- 각 task 실행 결과를 `/output/task_<id>/prediction.csv`로 복사/생성합니다.
- task별 trace/log를 `/logs/task_<id>/`에 저장하고, 전체 요약을 `/logs/run_summary.json`에 기록합니다.
- 모델 호출 정보는 `MODEL_API_URL`, `MODEL_API_KEY`, `MODEL_NAME` 환경변수를 우선 사용합니다.
- task별 context 파일 인벤토리를 스캔해 `schema_memory.json`으로 저장합니다.
- `sql_first`, `python_first`, `document_first` 라우팅 점수/근거를 계산해 `task.log.json`에 기록합니다.
- 생성된 `prediction.csv`에 대해 null/공백 정규화를 수행합니다.
- contract/sanity 기반 dual verification 결과를 `task.log.json`에 함께 남깁니다.

### 2) Docker 제출 구조 (`docker/Dockerfile`)
- 이미지 빌드 시 공식 starter-kit 저장소를 `git clone`으로 실제 가져옵니다.
- starter-kit 패키지를 설치한 뒤, 본 저장소의 evaluation runner를 엔트리포인트로 실행합니다.
- 컨테이너 기본 실행 경로는 대회 계약(`/input`, `/output`, `/logs`)을 따릅니다.

## 로컬 실행 예시

```bash
python -m runner.evaluation_runner \
  --input /input \
  --output /output \
  --logs /logs
```

## Docker 빌드/실행 예시

```bash
docker build -f docker/Dockerfile -t kdd-dataagent-submission .

docker run --rm \
  -e MODEL_API_URL="$MODEL_API_URL" \
  -e MODEL_API_KEY="$MODEL_API_KEY" \
  -e MODEL_NAME="$MODEL_NAME" \
  -v /path/to/input:/input:ro \
  -v /path/to/output:/output \
  -v /path/to/logs:/logs \
  kdd-dataagent-submission
```
