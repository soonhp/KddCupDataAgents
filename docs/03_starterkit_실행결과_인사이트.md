# Starter Kit 실행 결과 및 인사이트

## 1) 실행 로그 요약
- 저장소 클론: `git clone https://github.com/HKUSTDial/kddcup2026-data-agents-starter-kit /tmp/kdd_starter`
- 의존성 설치: `uv sync` (성공)
- 상태 점검: `uv run dabench status --config configs/react_baseline.example.yaml` (성공)

## 2) 관찰 결과
- baseline CLI는 정상 동작했다.
- 그러나 기본 상태에서 `data/public/input`이 없어 dataset_root가 missing으로 표시되었다.
- 즉, 로컬에서 바로 full benchmark를 돌리려면 별도 데이터셋 마운트/다운로드 절차가 필요하다.

## 3) 코드 구조 관점 인사이트
- Starter Kit은 ReAct 기반 단일 에이전트 + 툴 호출 구조로 시작하기 좋다.
- 제공 툴셋(`list_context`, `read_csv`, `inspect_sqlite_schema`, `execute_context_sql`, `execute_python`, `answer`)은 대회 요구사항의 핵심 흐름과 정합적이다.
- 상위권 목표를 위해선 단일 에이전트에서 멀티에이전트 오케스트레이션으로 확장해야 한다.

## 4) 개선 우선순위 (실행 가능한 백로그)
1. **Task Router**: question/context 기반으로 SQL-first vs Python-first 경로 분기.
2. **Schema Memory**: task 내 반복되는 스키마 탐색 결과 캐싱.
3. **Dual Verification**: SQL 경로와 Python 경로를 교차검증.
4. **Answer Normalizer**: 숫자/날짜/문자열 정규화 파이프라인.
5. **Failure Recovery**: 툴 에러 시 자동 fallback(예: SQL 실패→Python 재계산).

## 5) 점수 향상 관점 결론
- 대회는 모델 자체보다 **문제 분해·도구 선택·검증 루프·출력 정합성**에서 승부가 난다.
- Starter Kit은 “작동 가능한 최소 기반”으로 적합하며, 멀티에이전트 계층화가 핵심 승부처다.
