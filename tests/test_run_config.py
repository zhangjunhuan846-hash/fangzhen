# ============================================================
# Tests for the one-shot YAML run-config entry
# (--config in run_pipeline.py; additive, no pybamm needed)
# ============================================================

from pathlib import Path

import pytest

import run_pipeline as rp

ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------
# load_run_config
# --------------------------------------------------------------

def test_load_example_config():
    cfg = rp.load_run_config(ROOT / "configs" / "example.yaml")
    assert cfg["task"] == "baseline"
    assert cfg["dataset"] == "chen2020"
    assert str(cfg["cell"]) == "02"
    assert cfg["model"]["name"] == "SPMe"
    assert cfg["condition"]["rate"] == "C10"


def test_load_run_config_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        rp.load_run_config(tmp_path / "nope.yaml")


def test_load_run_config_bad_task(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("task: explode\n", encoding="utf-8")
    with pytest.raises(ValueError, match="task"):
        rp.load_run_config(p)


# --------------------------------------------------------------
# apply_run_config: config fills unset CLI fields
# --------------------------------------------------------------

def _args(argv):
    parser = rp.build_parser()
    return parser, parser.parse_args(argv)


def test_config_fills_defaults():
    parser, args = _args(["--config", "configs/example.yaml"])
    run_cfg = rp.load_run_config("configs/example.yaml")
    rp.apply_run_config(parser, args, run_cfg)

    assert args.task == "baseline"
    assert args.dataset == "chen2020"
    assert args.model == "SPMe"
    assert str(args.cell) == "02"
    assert args.rate == "C10"
    assert args.no_plot is False


def test_cli_flags_win_over_config():
    parser, args = _args(
        ["--config", "configs/example.yaml", "--model", "DFN"]
    )
    run_cfg = rp.load_run_config("configs/example.yaml")
    rp.apply_run_config(parser, args, run_cfg)

    assert args.model == "DFN"          # CLI wins
    assert args.dataset == "chen2020"   # config still fills the rest
    assert args.rate == "C10"


def test_config_save_curve_false_sets_no_plot(tmp_path):
    p = tmp_path / "noplot.yaml"
    p.write_text(
        "task: baseline\ndataset: chen2020\n"
        "output:\n  save_curve: false\n",
        encoding="utf-8",
    )
    parser, args = _args(["--config", str(p)])
    run_cfg = rp.load_run_config(p)
    rp.apply_run_config(parser, args, run_cfg)
    assert args.no_plot is True


def test_config_model_list_goes_to_models():
    parser, args = _args([])
    run_cfg = {
        "task": "benchmark",
        "dataset": "chen2020",
        "model": {"models": ["SPMe", "DFN"]},
    }
    rp.apply_run_config(parser, args, run_cfg)
    assert args.models == ["SPMe", "DFN"]


# --------------------------------------------------------------
# chemistry registry (configs/chemistry.yaml)
# --------------------------------------------------------------

def test_chemistry_registry_resolves():
    chem = rp.load_chemistry_description("NMC_Graphite")
    assert chem is not None
    assert "NMC" in chem["detail"]
    assert chem["default_parameter_set"] == "Chen2020"
    assert chem["grade"] == "A-exact"


def test_chemistry_registry_surrogate_grade():
    chem = rp.load_chemistry_description("LCO_Graphite")
    assert chem is not None
    assert chem["grade"] == "B-compatible_surrogate"


def test_chemistry_registry_unknown_returns_none():
    assert rp.load_chemistry_description("Unobtanium_Air") is None
