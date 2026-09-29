"""三个接缝的联合演示（纯契约层，不需要 pybamm）。

跑法（WSL，平台环境）：
  cd /mnt/c/Users/24330/WorkBuddy/Battery-Sim-Agent/battery_agent
  source ~/miniforge3/etc/profile.d/conda.sh && conda activate pybamm
  PYTHONIOENCODING=utf-8 python /mnt/c/Users/24330/WorkBuddy/仿真模拟/scripts/_seam_demo.py
"""

import sys
from pathlib import Path
from types import SimpleNamespace

# 脚本住在仿真模拟/scripts/，被测包在 Battery-Sim-Agent/battery_agent/。
# 显式把后者放进 sys.path，否则 import 会随 cwd 漂移。
_AGENT_ROOT = Path(
    "/mnt/c/Users/24330/WorkBuddy/Battery-Sim-Agent/battery_agent"
)
if not _AGENT_ROOT.is_dir():  # 也允许从 Windows 侧跑
    _AGENT_ROOT = Path(r"C:\Users\24330\WorkBuddy\Battery-Sim-Agent\battery_agent")
sys.path.insert(0, str(_AGENT_ROOT))

from param_capability import CURVE, check_declaration, initialisation_block
from sim_contract import (
    ParameterValue,
    Protocol,
    SimulationRequest,
    validate_request,
)
from simulator import _cell_configuration_for, build_overrides


def main() -> int:
    # --- 接缝 A：槽位从数据集声明里读出来（不是硬编码） -----------
    adapter = SimpleNamespace(
        config=SimpleNamespace(
            extra={
                "cell_configuration": "half_cell",
                "working_electrode": "positive",
                "physical_working_electrode": "graphite_negative",
            }
        )
    )
    cfg = _cell_configuration_for(adapter)
    print("接缝A 槽位解析 :", cfg)

    # --- 一条真实的回收石墨半电池请求 -----------------------------
    req = SimulationRequest(
        model_name="SPM",
        param_set="Ecker2015_graphite_halfcell",
        params={
            "particle_radius": ParameterValue(1.37e-5, "m", "measured_sem"),
            "particle_diffusivity": ParameterValue(
                3.06e-13, "m2/s", "gitt_window_x0p10"
            ),
            "initial_state": {
                "method": "fixed_initial_concentration",
                "stoichiometry_from_ocp": 0.001,
                "ocp_voltage_V": 0.780,
            },
        },
        protocol=Protocol(kind="experiment_replay"),
    )

    errors = validate_request(req)
    print("校验           :", errors or "PASS")

    overrides, records = build_overrides(
        req,
        representation_probe=lambda key: "scalar",
        cell_configuration=cfg,
    )
    print("接缝A 覆写键   :")
    for record in records:
        print(
            "                  ",
            record["logical_name"],
            "->",
            record["pybamm_parameter_name"],
        )

    # --- 接缝 C：初值块翻成平台消费的形状 -------------------------
    # 槽位必须传进去：平台拿这两个键名去参数集里查，
    # 硬编码 "positive" 会让负极槽位的石墨半电池查到一个不存在的键。
    block, refusal = initialisation_block(
        req.initial_state, cell_configuration=cfg
    )
    assert refusal is None, refusal
    print(
        "接缝C 初值块   :",
        {
            key: block[key]
            for key in (
                "method",
                "stoichiometry_from_ocp",
                "ocp_voltage_V",
                "concentration_parameter",
            )
        },
    )

    # --- 接缝 C 的负对照：缺 ocp_voltage_V 必须在桥侧就被拒 --------
    # 平台用 init_block["ocp_voltage_V"] 硬下标读取 ⇒ 桥放过它
    # 只会在求解时炸成 KeyError。
    _, no_v0 = initialisation_block(
        {
            "method": "fixed_initial_concentration",
            "stoichiometry_from_ocp": 0.001,
        },
        cell_configuration=cfg,
    )
    print(
        "接缝C 负对照   : 缺 ocp_voltage_V ->",
        "拒绝" if no_v0 else "**放过了（错）**",
    )

    # --- 接缝 B：曲线的拒绝消息指出正确通路 -----------------------
    verdict = check_declaration("ocp", "SPM", CURVE)
    assert verdict is not None
    print("接缝B 曲线拒绝 : 指向 adapter 通路 =", "ocp_table_path" in verdict[1])

    # --- 负对照：曲线给标量必须被拒，且不给数 ----------------
    print(
        "负对照         : particle_diffusivity 无 probe ->",
        "拒绝" if _refused(req) else "**放过了（错）**",
    )
    return 0


def _refused(req) -> bool:
    from simulator import ParameterRefused, build_overrides as bo

    sub = SimulationRequest(
        model_name=req.model_name,
        param_set=req.param_set,
        params={"particle_diffusivity": req.params["particle_diffusivity"]},
        protocol=req.protocol,
    )
    try:
        bo(sub)
    except ParameterRefused:
        return True
    return False


if __name__ == "__main__":
    raise SystemExit(main())
