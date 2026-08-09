import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "run.py"), *args],
        cwd=ROOT, capture_output=True, text=True,
    )


def test_cli_runs_case1_and_prints_json():
    result = _run("cases/case1_feasible_even")
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["feasible"] is True
    assert payload["pay_shape_used"] == "even"


def test_cli_nonexistent_case_dir_nonzero_exit_stderr_only():
    result = _run("cases/does_not_exist")
    assert result.returncode != 0
    assert result.stdout.strip() == ""
    assert "error" in result.stderr.lower()


def test_cli_no_args_usage_message():
    result = _run()
    assert result.returncode != 0
    assert "usage" in result.stderr.lower()


def test_cli_deterministic_across_runs():
    r1 = _run("cases/case4_tiers")
    r2 = _run("cases/case4_tiers")
    assert r1.stdout == r2.stdout
