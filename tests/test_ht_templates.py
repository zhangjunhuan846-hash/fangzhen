"""商用石墨热处理梯度的四份元数据模板，必须自己先立得住。

模板是给**未来的人**看的：如果它自己都不满足契约，第一个学会的事就是忽略检查器。
所以这里把两件事钉死：

1. **报错集合恰好是"只有人能填的那 7 个数"** —— 多一个少一个都说明模板被改坏了；
2. **四份文件只差身份字段**（sample_id / 工艺 / 路径）—— 复制粘贴出来的漂移
   （某一份少了一个 measurement、某一处几何不一样）会直接毁掉样品间比较。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from battery_sim.datasets.material_metadata import (
    missing_fields,
    validate,
    validate_series,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def root():
    """仓库根 —— 模板与源码一起入库，测试直接读仓库里的那一份。"""
    return ROOT

#: 模板故意留空的字段 = 只有实验者才知道的实测量
EXPECTED_MISSING = (
    "source",
    "electrode.mass_loading_mg_cm2",
    "electrode.coating_thickness_um",
    "electrode.area_cm2",
    "particle.d50_um",
    "cell.counter_electrode",
    "cell.electrolyte",
)

SAMPLES = ("CG-AR", "CG-600", "CG-800", "CG-900")


def _path(root, sample):
    return root / "templates" / "commercial_graphite_ht" / "metadata" / \
        f"{sample}.yaml"


@pytest.fixture(scope="module")
def metas(root):
    return {s: yaml.safe_load(_path(root, s).read_text(encoding="utf-8"))
            for s in SAMPLES}


# ------------------------------------------------------------------
# 1 模板本身的契约状态
# ------------------------------------------------------------------
def test_the_expected_missing_set_is_exactly_the_human_only_numbers(metas):
    """这是模板的**产品说明**：跑一遍，它告诉你必须手填的只有这几个。"""
    for sample, meta in metas.items():
        assert tuple(missing_fields(meta)) == EXPECTED_MISSING, sample


def test_templates_report_only_missing_measurements_not_shape_errors(metas):
    """报错必须是"还没填"，不能是契约写错（键越界 / 词表外取值 / 自相矛盾）。"""
    for sample, meta in metas.items():
        result = validate(meta)
        assert len(result["errors"]) == len(EXPECTED_MISSING), sample
        for err in result["errors"]:
            assert err.startswith("缺字段"), (sample, err)
        assert result["warnings"] == [], (sample, result["warnings"])


def test_structure_blocks_are_declared_but_pending_with_a_reason(metas):
    """没测 ≠ 忘了写：三个块都要 available:false + 原因。"""
    for sample, meta in metas.items():
        for block in ("xrd", "raman", "bet"):
            entry = meta["structure"][block]
            assert entry["available"] is False, (sample, block)
            assert str(entry["not_available_reason"]).strip(), (sample, block)
    assert len(validate(metas["CG-AR"])["pending"]) >= 3


# ------------------------------------------------------------------
# 2 梯度：四份只差身份
# ------------------------------------------------------------------
def _normalised(meta):
    """抹掉身份字段后的可比较形态（路径里含 sample_id，一并抹掉）。"""
    sid = str(meta["sample_id"])

    def walk(node):
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        if isinstance(node, str):
            return node.replace(sid, "<SAMPLE>")
        return node

    out = walk(meta)
    out.pop("sample_id", None)
    out.pop("processing", None)
    out.pop("source", None)
    return out


def test_the_four_files_differ_only_in_identity_and_treatment(metas):
    reference = _normalised(metas["CG-AR"])
    for sample in SAMPLES[1:]:
        assert _normalised(metas[sample]) == reference, (
            f"{sample} 与 CG-AR 除了身份/工艺之外还有差异 —— "
            f"复制粘贴漂移会让样品间比较失效"
        )


def test_treatment_temperature_is_the_independent_variable(metas):
    assert metas["CG-AR"]["processing"]["applied"] is False
    temps = {s: metas[s]["processing"]["temperature_C"] for s in SAMPLES[1:]}
    assert temps == {"CG-600": 600, "CG-800": 800, "CG-900": 900}
    for sample in SAMPLES[1:]:
        proc = metas[sample]["processing"]
        assert proc["applied"] is True
        assert str(proc["atmosphere"]).strip()
        assert proc["duration_h"] > 0
        # 处理质量两项故意留空：必须来自管式炉记录，不能预填
        assert proc["mass_before_mg"] is None
        assert proc["mass_after_mg"] is None


def test_the_templates_form_a_valid_series(metas):
    """系列级判据（工艺真的不同、编号唯一、电极一致）现在就成立。"""
    assert validate_series([metas[s] for s in SAMPLES])["errors"] == []


def test_material_class_describes_origin_not_treatment(metas):
    """四份都是原生石墨（不是回收料）；差异由 processing 承载。

    把"热处理过"混进 material_class，会让同批料的两个工艺状态看起来是
    两种材料，而这正是契约要避免的混淆。
    """
    assert {m["material_class"] for m in metas.values()} == {"pristine"}
    assert all("recycling" not in m for m in metas.values())


# ------------------------------------------------------------------
# 3 预登记的测量与角色
# ------------------------------------------------------------------
def _by_file(meta):
    return {str(m["file"]).rsplit("/", 1)[-1]: m for m in meta["measurements"]}


def test_measurement_roles_are_registered_before_the_data_exists(metas):
    """角色是**预先登记**的：1C 留下来做预测检验，不许事后改口径。"""
    for sample, meta in metas.items():
        files = _by_file(meta)
        for name in ("gcd_0p1C.csv", "rate_0p2C.csv", "gitt.csv",
                     "ocp_c20.csv"):
            assert files[name]["role"] == "identification", (sample, name)
        for name in ("rate_0p5C.csv", "rate_1C.csv", "rate_2C.csv"):
            assert files[name]["role"] == "validation", (sample, name)
        assert "Level 4" in files["rate_1C.csv"]["notes"], sample


def test_gitt_protocol_in_the_template_matches_the_design_document(metas):
    """模板里的协议数值必须与设计文档一致，否则两处会各自漂移。"""
    for sample, meta in metas.items():
        notes = _by_file(meta)["gitt.csv"]["notes"]
        assert "10 min" in notes and "30 min" in notes and "双向" in notes


def test_eis_is_declared_and_its_limitation_is_written_down(metas):
    """测了但没有拟合通路 —— 这句话必须写在数据里，不能只写在文档里，
    否则报告会把它写成「没测」（两者含义相反）。"""
    for sample, meta in metas.items():
        notes = _by_file(meta)["eis.csv"]["notes"]
        assert "100 kHz" in notes and "not_measured" in notes


def test_every_declared_file_lives_under_the_sample_directory(metas):
    for sample, meta in metas.items():
        for item in meta["measurements"]:
            assert item["file"].startswith(f"data/raw/graphite_ht/{sample}/"), \
                (sample, item["file"])


# ------------------------------------------------------------------
# 4 数据集的角色分配片段
# ------------------------------------------------------------------
def test_datasets_snippet_separates_the_holdout(root):
    """1C 留出集必须在**平台层**也是 validation，光写 metadata 不够。"""
    path = root / "templates" / "commercial_graphite_ht" / \
        "datasets_yaml_snippet.yaml"
    text = path.read_text(encoding="utf-8")
    doc = yaml.safe_load(text)
    assert set(doc) >= {f"graphite_ht_{s.lower().replace('-', '_')}"
                        for s in SAMPLES}
    assert doc["graphite_ht_rate_holdout"]["dataset_role"] == "validation"
    for sample in SAMPLES:
        key = f"graphite_ht_{sample.lower().replace('-', '_')}"
        assert doc[key]["dataset_role"] == "identification"
    assert re.search(r"不要.*合进 configs", text)      # 空数据集不能进管线
