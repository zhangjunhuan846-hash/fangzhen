# -*- coding: utf-8 -*-
"""MODULES.yaml 的存在性与自洽性测试。

为什么要有这个测试：清单的价值在于"它不会腐烂"。
如果加了模块却不登记，清单就从契约退化成文档。
本测试把这件事变成红灯。

纯标准库，不 import pybamm、不需要网络。
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "MODULES.yaml"
CHECKER = ROOT / "scripts" / "check_module_manifest.py"


@pytest.fixture(scope="module")
def manifest_text() -> str:
    assert MANIFEST.is_file(), f"MODULES.yaml 不存在：{MANIFEST}"
    return MANIFEST.read_text(encoding="utf-8")


def test_manifest_exists():
    assert MANIFEST.is_file()


def test_manifest_declares_the_three_tiers(manifest_text):
    """三档必须都在，否则判据不完整。"""
    for tier in ("core:", "optional:", "scratch:"):
        assert tier in manifest_text, f"清单缺少分档：{tier}"


def test_manifest_states_the_operational_criterion(manifest_text):
    """判据必须是可执行的，不能是『重不重要』。"""
    assert "删掉" in manifest_text and "红" in manifest_text, (
        "清单必须写出『删了会不会红』这条判据 —— 这是它可验证的前提"
    )


def test_every_core_path_exists(manifest_text):
    """core 档登记的路径必须真实存在。"""
    core_block = manifest_text.split("optional:", 1)[0]
    missing = []
    for m in re.finditer(r"^\s*- path:\s*(\S+)", core_block, re.M):
        rel = m.group(1).strip().strip('"').strip("'")
        if rel.startswith(("Batter", "C:", "repos")) or "*" in rel:
            continue
        if not (ROOT / rel).exists():
            missing.append(rel)
    assert not missing, f"core 登记的路径不存在：{missing}"


def test_checker_script_is_registered_as_core(manifest_text):
    """校验器自己必须是 core —— 否则它可以被删掉而没人发现。"""
    assert "scripts/check_module_manifest.py" in manifest_text


def test_the_checker_passes_on_the_current_tree():
    """端到端：在本仓库当前状态下，校验器必须 rc=0。

    这条测试把『清单不会腐烂』变成红灯：谁加了模块不登记，这里就会变红。
    """
    assert CHECKER.is_file(), f"校验器不存在：{CHECKER}"
    proc = subprocess.run(
        [sys.executable, str(CHECKER)],
        cwd=str(ROOT), capture_output=True, text=True, timeout=180,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    assert proc.returncode == 0, f"清单校验未通过（rc={proc.returncode}）：\n{out}"


def test_checker_reports_fail_count_in_output():
    """校验器必须自报 FAIL 计数，否则失败时不好定位。"""
    proc = subprocess.run(
        [sys.executable, str(CHECKER)],
        cwd=str(ROOT), capture_output=True, text=True, timeout=180,
    )
    assert "FAIL" in (proc.stdout or "")


def test_pack_section_names_the_excluded_data_dir(manifest_text):
    """打包说明必须明确 data/ 被排除 —— 13 GB 不能进包。"""
    assert "data/" in manifest_text
    assert "13 GB" in manifest_text or "13GB" in manifest_text


def test_pack_section_records_the_non_git_risk(manifest_text):
    """两个非 git 仓库的备份风险必须写进清单。"""
    assert "is_git: false" in manifest_text
    assert "Battery-Sim-Agent" in manifest_text
