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
- 실패 원인을 `runtime_timeout`, `output_contract_violation` 등 taxonomy tag로 분류해 task 로그와 `run_summary.json`에 집계합니다.
- task마다 `run_summary.json`을 중간 checkpoint로 갱신하고, SIGTERM/SIGINT 수신 시 현재 task 종료 후 안전 중단(interrupted) 상태를 기록합니다.

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

## 회귀 테스트

```bash
python -m unittest discover -s tests -p 'test_*.py'
```

- `tests/test_task_intelligence.py`: 라우팅/정규화/검증 회귀 테스트
- `tests/test_failure_taxonomy.py`: 실패 taxonomy 분류 및 집계 회귀 테스트

## work 브랜치 완전 자동화(PR 생성 → 리뷰 승인 → 자동 머지)

수동으로 `PR 만들기` 버튼을 누르지 않아도 되도록, `work` 브랜치 기준 자동 승격 파이프라인을 추가했습니다.

- `.github/workflows/auto-pr-from-work.yml`
  - `work` 브랜치 push 시 `main` 대상 PR을 자동 생성(이미 열려 있으면 재사용)
- `.github/workflows/auto-approve-work-pr.yml`
  - `work -> main` PR을 `github-actions[bot]`이 자동 승인
- `.github/workflows/auto-merge-after-review.yml`
  - 승인 조건 충족 시 auto-merge(squash) 활성화
- `.github/workflows/ci.yml`
  - PR 체크(py_compile + unittest) 통과 시 브랜치 보호 규칙과 함께 최종 merge 진행

> 참고: 실제 merge는 GitHub 브랜치 보호 규칙(필수 체크/리뷰 수) 충족 이후 수행됩니다.

## PR 리뷰 승인 후 자동 머지

저장소의 `main` 대상 PR에 대해, 아래 조건을 만족하면 GitHub Actions가 auto-merge(squash)를 활성화하도록 설정했습니다.

- PR이 `draft`가 아닐 것
- 최신 리뷰 상태 기준으로 `APPROVED`가 1개 이상일 것
- 최신 리뷰 상태에 `CHANGES_REQUESTED`가 없을 것

워크플로 파일: `.github/workflows/auto-merge-after-review.yml`

또한 PR/merge 안정성을 위해 `.github/workflows/ci.yml`에서 기본 검증(py_compile + unittest)을 실행하도록 추가했습니다.

> 참고: 워크플로는 auto-merge를 "활성화"합니다. 실제 머지는 브랜치 보호 규칙(필수 체크, 리뷰 수 등)을 모두 만족한 뒤 GitHub가 수행합니다.
