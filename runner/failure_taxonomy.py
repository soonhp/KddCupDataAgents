from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass

from runner.verification import VerificationReport


@dataclass(slots=True)
class FailureTag:
    code: str
    detail: str


@dataclass(slots=True)
class TaskFailureTaxonomy:
    task_id: str
    tags: list[FailureTag]


@dataclass(slots=True)
class FailureRollup:
    by_code: dict[str, int]


def classify_task_failure(
    *,
    task_id: str,
    succeeded: bool,
    failure_reason: str | None,
    verification_report: VerificationReport,
) -> TaskFailureTaxonomy:
    tags: list[FailureTag] = []

    reason = (failure_reason or "").strip().lower()
    if not succeeded:
        if "timeout" in reason:
            tags.append(FailureTag(code="runtime_timeout", detail=failure_reason or "timeout"))
        elif "memory" in reason or "oom" in reason:
            tags.append(FailureTag(code="runtime_oom", detail=failure_reason or "out of memory"))
        elif "api" in reason or "auth" in reason or "rate" in reason:
            tags.append(FailureTag(code="model_service_error", detail=failure_reason or "model service issue"))
        elif reason:
            tags.append(FailureTag(code="runner_failure", detail=failure_reason))
        else:
            tags.append(FailureTag(code="runner_failure", detail="unknown failure"))

    for check in verification_report.checks:
        if check.passed:
            continue
        if check.name == "contract_check":
            tags.append(FailureTag(code="output_contract_violation", detail=check.detail))
        elif check.name == "sanity_check":
            tags.append(FailureTag(code="output_sanity_violation", detail=check.detail))
        else:
            tags.append(FailureTag(code="verification_failure", detail=f"{check.name}: {check.detail}"))

    if not tags and succeeded:
        tags.append(FailureTag(code="passed", detail="all checks passed"))

    return TaskFailureTaxonomy(task_id=task_id, tags=tags)


def rollup_failure_taxonomy(task_failures: list[TaskFailureTaxonomy]) -> FailureRollup:
    counter: Counter[str] = Counter()
    for task_failure in task_failures:
        for tag in task_failure.tags:
            counter[tag.code] += 1
    return FailureRollup(by_code=dict(sorted(counter.items())))


def failure_taxonomy_to_dict(taxonomy: TaskFailureTaxonomy) -> dict:
    return asdict(taxonomy)


def failure_rollup_to_dict(rollup: FailureRollup) -> dict:
    return asdict(rollup)
