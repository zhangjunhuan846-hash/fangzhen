# ============================================================
# Battery Dataset Simulation Platform v0.1
# Path helpers
#
# Works both on native Windows and inside WSL when the project
# is reached through /mnt/c/... (both resolve from __file__).
# ============================================================

from __future__ import annotations

from pathlib import Path

# project root = parents[1] of platform/paths.py
ROOT = Path(__file__).resolve().parents[1]

PLATFORM_DIR = Path(__file__).resolve().parent

CONFIGS_DIR = ROOT / "configs"
OUTPUTS_DIR = ROOT / "outputs"

# All platform-managed runs write under outputs/platform/
PLATFORM_OUTPUT_ROOT = OUTPUTS_DIR / "platform"


def dataset_raw_dir(dataset_id: str, raw_dir_rel: str) -> Path:
    """Resolve a raw dir from datasets.yaml relative to project root."""
    return ROOT / raw_dir_rel


def dataset_processed_dir(dataset_id: str, processed_dir_rel: str) -> Path:
    """Resolve a processed dir from datasets.yaml relative to project root."""
    return ROOT / processed_dir_rel


def platform_output_dir(dataset_id: str, mode: str, model: str, cell: str) -> Path:
    """
    Standard per-run output directory:

        outputs/platform/<dataset>/<mode>/<MODEL>/cell<cell>/
    """
    return (
        PLATFORM_OUTPUT_ROOT
        / dataset_id
        / mode
        / model.upper()
        / f"cell{cell}"
    )


def ensure_dir(path: Path) -> Path:
    """Create directory (parents=True, exist_ok=True) and return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path
