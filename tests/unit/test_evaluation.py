import pytest

from tokenos.application.evaluation import Attempt, evaluate


def attempt(task, success, tokens, source="provider"):
    return Attempt(task_id=task, success=success, total_tokens=tokens, latency_ms=10, source=source)


def test_tps_counts_failed_task_tokens():
    report = evaluate([attempt("a", True, 100), attempt("b", False, 300)])
    assert report.tokens_per_success == 400 and report.success_rate == 0.5


def test_zero_success_and_missing_usage():
    assert evaluate([attempt("a", False, 100)]).tokens_per_success is None
    report = evaluate([attempt("a", True, None)])
    assert report.tokens_per_success is None and not report.accounting_complete


def test_simulation_cannot_mix_with_provider_results():
    with pytest.raises(ValueError, match="separately"):
        evaluate([attempt("a", True, 100), attempt("b", True, 10, "simulated")])


def test_retries_must_be_aggregated_and_dataset_not_empty():
    with pytest.raises(ValueError):
        evaluate([])
    with pytest.raises(ValueError, match="aggregate"):
        evaluate([attempt("a", False, 10), attempt("a", True, 10)])
