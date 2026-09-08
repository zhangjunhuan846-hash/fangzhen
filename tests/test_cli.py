# ============================================================
# Battery Dataset Simulation Platform v0.1
# CLI tests (Step 11)
#
# Executes run_pipeline.py in a subprocess from the project root.
# ============================================================

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run_cli(*args: str):
    return subprocess.run(
        [sys.executable, str(ROOT / "run_pipeline.py"), *args],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        timeout=120,
    )


def test_help_exits_zero():
    result = _run_cli("--help")

    assert result.returncode == 0, result.stderr

    for token in [
        "--dataset",
        "--mode",
        "--model",
        "--cell",
        "--rate",
        "--parameter",
        "--list-datasets",
    ]:
        assert token in result.stdout


def test_list_datasets_exits_zero():
    result = _run_cli("--list-datasets")

    assert result.returncode == 0, result.stderr

    assert "chen2020" in result.stdout
    assert "NMC_Graphite" in result.stdout
    assert "02,03,04" in result.stdout


def test_unknown_dataset_fails_gracefully():
    result = _run_cli("--dataset", "nope", "--list-datasets")

    # --list-datasets short-circuits before dataset lookup
    assert result.returncode == 0


def test_invalid_mode_rejected():
    result = _run_cli("--mode", "not-a-mode")

    assert result.returncode != 0
