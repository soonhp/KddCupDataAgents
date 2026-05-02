# KddCupDataAgents

KDD Cup 2026 DataAgent-Bench 제출을 위한 runner, Docker packaging, local public-demo scoring workflow를 담은 작업 저장소입니다.

이 저장소의 제출 경로는 공식 평가 계약을 기준으로 합니다.

- 입력: `/input/task_<id>/task.json` 및 `/input/task_<id>/context/`
- 출력: `/output/task_<id>/prediction.csv`
- 로그: `/logs/runtime.log`, `/logs/run_summary.json`, `/logs/task_<id>/`
- 모델: `MODEL_API_URL`, `MODEL_API_KEY`, `MODEL_NAME` 환경변수로 주입되는 OpenAI Chat Completions compatible endpoint

## 주요 구성

- `runner/evaluation_runner.py`
  - `/input` 아래 모든 `task_<id>`를 순회합니다.
  - starter-kit baseline 실행 결과를 `/output/task_<id>/prediction.csv`로 복사/정규화합니다.
  - context profiling, route decision, contract/sanity verification, semantic/agent review, retry orchestration 결과를 `/logs`에 남깁니다.
  - SIGTERM/SIGINT 수신 시 현재 task 종료 후 안전하게 summary를 기록합니다.
- `runner/scoring.py`, `scripts/score_predictions.py`
  - public demo `gold.csv` 기준 local metric을 계산합니다.
  - 공식 rules의 column-signature 방식에 맞춰 header/order를 무시하고 null/numeric/date/datetime 값을 정규화합니다.
  - 공식 λ 값은 공개되어 있지 않으므로 기본 `--lambda-penalty 0`을 사용합니다.
- `docker/Dockerfile`, `docker/entrypoint.sh`
  - 공식 starter-kit commit `c6992b07bcd320b7904505c92c6ba7f7c77e4857`을 기본값으로 고정합니다.
  - 컨테이너는 `/input`, `/output`, `/logs` 계약으로 실행됩니다.
- `scripts/build_submission.sh`
  - 기본 제출 이미지/아카이브인 `team0000:v3`, `team0000_v3.tar.gz`를 생성합니다.

## 모델 환경변수

평가/실험 시 아래 세 값이 필요합니다. API key는 코드, README, Dockerfile, Git commit에 넣지 않습니다.

```bash
export MODEL_API_URL="https://router.huggingface.co/v1"
export MODEL_API_KEY="$HF_TOKEN"
export MODEL_NAME="Qwen/Qwen3.5-35B-A3B"
```

공식 평가에서는 대회 시스템이 내부 Qwen endpoint를 같은 형식으로 주입합니다. OpenAI SDK는 client로만 사용하며, 실제 모델은 `MODEL_API_URL`과 `MODEL_NAME`이 결정합니다.

짧은 연결 테스트:

```bash
python - <<'PY'
import os
from openai import OpenAI

client = OpenAI(
    base_url=os.environ["MODEL_API_URL"],
    api_key=os.environ["MODEL_API_KEY"],
)
response = client.chat.completions.create(
    model=os.environ["MODEL_NAME"],
    messages=[{"role": "user", "content": "Return exactly: ok"}],
    temperature=0,
)
print(response.choices[0].message.content)
PY
```

Hugging Face Inference Providers에서 `402`가 발생하면 토큰 권한 문제가 아니라 월간 포함 크레딧 소진입니다. 그 상태에서 생성되는 fallback prediction의 score는 모델 성능 지표로 해석하면 안 됩니다.

## Public Demo 실행 및 채점

공식 starter-kit의 public demo dataset을 준비한 뒤 실행합니다.

```bash
python -m pip install \
  git+https://github.com/HKUSTDial/kddcup2026-data-agents-starter-kit@c6992b07bcd320b7904505c92c6ba7f7c77e4857

python -m runner.evaluation_runner \
  --input /path/to/public/input \
  --output /tmp/kdd_public_output \
  --logs /tmp/kdd_public_logs \
  --max-workers 1 \
  --task-timeout-seconds 900

python scripts/score_predictions.py \
  --prediction-root /tmp/kdd_public_output \
  --gold-root /path/to/public/output \
  --json-output /tmp/kdd_public_logs/public_score.json \
  --csv-output /tmp/kdd_public_logs/public_score.csv
```

## Docker 제출 검증

이미지 빌드 및 제출 archive 생성:

```bash
TEAM_ID=team0000 VERSION=v3 scripts/build_submission.sh
```

대회와 같은 mount 계약으로 실행:

```bash
docker run --rm \
  -e MODEL_API_URL \
  -e MODEL_API_KEY \
  -e MODEL_NAME \
  -v /path/to/public/input:/input:ro \
  -v /tmp/kdd_docker_output:/output \
  -v /tmp/kdd_docker_logs:/logs \
  team0000:v3
```

Docker 실행 결과 채점:

```bash
python scripts/score_predictions.py \
  --prediction-root /tmp/kdd_docker_output \
  --gold-root /path/to/public/output \
  --json-output /tmp/kdd_docker_logs/public_score.json \
  --csv-output /tmp/kdd_docker_logs/public_score.csv
```

검증된 제출 archive는 `team0000_v3.tar.gz`입니다. 대회 team id가 다르면 `TEAM_ID=<actual_team_id>`로 다시 생성합니다.

## 테스트

```bash
python -m unittest discover -s tests -p 'test_*.py'
python -m py_compile runner/*.py scripts/score_predictions.py
```

현재 테스트 커버리지:

- routing/context profiling/normalization/verification
- failure taxonomy
- repair/retry orchestration
- retry artifact run id collision 방지
- official-style public-demo scoring

## GitHub Workflow

`.github/workflows/`에는 `work` 브랜치 자동 PR/approve/auto-merge 보조 workflow와 CI가 있습니다.

- `ci.yml`: `py_compile` 및 `unittest`
- `auto-pr-from-work.yml`: `work` push 시 main 대상 PR 생성
- `auto-approve-work-pr.yml`: `work -> main` PR 자동 승인
- `auto-merge-after-review.yml`: 승인 조건 충족 시 auto-merge 활성화

기능 단위 변경은 별도 branch와 PR로 올리고, 제출용 credential이나 dataset artifact는 커밋하지 않습니다.
