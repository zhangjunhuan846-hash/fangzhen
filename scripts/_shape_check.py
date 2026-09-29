"""对比桥与平台适配器产生的 initialisation 块【形状】是否一致。

只比键集合与键名的槽位词，不比数值（数值来源不同是应该的）。
这是一次性交叉校验，不是测试；结论写进 archive「第七次瘦身」。
"""

import sys

_AGENT = "/mnt/c/Users/24330/WorkBuddy/Battery-Sim-Agent/battery_agent"
if not __import__("pathlib").Path(_AGENT).is_dir():
    _AGENT = r"C:\Users\24330\WorkBuddy\Battery-Sim-Agent\battery_agent"
sys.path.insert(0, _AGENT)

from param_capability import initialisation_block  # noqa: E402

bridge, refusal = initialisation_block(
    {
        "method": "fixed_initial_concentration",
        "stoichiometry_from_ocp": 0.001,
        "ocp_voltage_V": 0.780,
    },
    cell_configuration="half_cell_positive",
)
assert refusal is None, refusal

# 平台适配器的键（从 battery_sim/datasets/recycled_graphite.py:644-655 逐字抄，
# 不做导入以免拉起 pybamm）
PLATFORM_KEYS = {
    "method",
    "concentration_parameter",
    "max_concentration_parameter",
    "stoichiometry_from_ocp",
    "ocp_voltage_V",
    "mapping_reason",
}
PLATFORM_CONC = "Initial concentration in positive electrode [mol.m-3]"
PLATFORM_CMAX = "Maximum concentration in positive electrode [mol.m-3]"

bridge_keys = set(bridge)
print("桥的键            :", sorted(bridge_keys))
print("平台的键          :", sorted(PLATFORM_KEYS))
print("平台有而桥没有    :", sorted(PLATFORM_KEYS - bridge_keys) or "无")
print("桥有而平台没有    :", sorted(bridge_keys - PLATFORM_KEYS) or "无")
print("conc 键一致       :", bridge["concentration_parameter"] == PLATFORM_CONC)
print("cmax 键一致       :", bridge["max_concentration_parameter"] == PLATFORM_CMAX)

ok = (
    not (PLATFORM_KEYS - bridge_keys)
    and bridge["concentration_parameter"] == PLATFORM_CONC
    and bridge["max_concentration_parameter"] == PLATFORM_CMAX
)
print("结论:", "PASS" if ok else "**不一致（错）**")
raise SystemExit(0 if ok else 1)
