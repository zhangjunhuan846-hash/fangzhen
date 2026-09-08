# ============================================================
# Battery Dataset Simulation Platform v0.1
# Model factory tests (Step 11)
# ============================================================

import pytest

pybamm = pytest.importorskip("pybamm")

from battery_sim.models.pybamm_factory import (  # noqa: E402
    build_model,
    load_parameter_values,
)


@pytest.mark.parametrize(
    "name, pybamm_type",
    [
        ("SPM", "SPM"),
        ("SPMe", "SPMe"),
        ("DFN", "DFN"),
    ],
)
def test_build_model(name, pybamm_type):
    model = build_model(name)

    assert model.__class__.__name__ == pybamm_type
    assert model.name


def test_build_model_accepts_lower_case():
    assert build_model("spme").__class__.__name__ == "SPMe"


def test_build_model_rejects_unknown():
    with pytest.raises(ValueError):
        build_model("nonsense")


def test_load_parameter_values_chen2020():
    params = load_parameter_values("Chen2020")

    assert float(params["Nominal cell capacity [A.h]"]) == pytest.approx(
        5.0
    )


def test_load_parameter_values_rejects_unknown():
    with pytest.raises(Exception):
        load_parameter_values("DoesNotExist")
