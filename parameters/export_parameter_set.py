# ============================================================
# 参数集导出 / 加载 / 校验
#
# 目的：让"这个仿真用的是哪套参数"从**进程内的运行时状态**变成
# 一个可以 diff、可以归档、可以复现的**文件**。
#
# 诚实地说明能存什么、不能存什么
#   派生参数集里有**函数**（实测 OCP 与 D_s 都是 Interpolant）。
#   PyBaMM 的 ParameterValues 没有通用序列化，函数装不进 JSON。
#   所以本模块**不假装**能存下整套参数集，而是存三样东西：
#     1. scalars   —— 纯数值条目的快照（可逐位比对）
#     2. inputs    —— 该参数集依赖的**输入文件 + sha256 指纹**
#                     （OCP 表、D_s 表、几何元数据…… 改了就校验得出）
#     3. callables —— 函数条目的名称与 repr（只作记录，并标明不可序列化）
#   外加一个 recipe：说明用什么函数、什么参数可以把这套集重建出来。
#
# 于是"自动生成参数集文件"有了确切含义：
#   文件能证明**用了哪些输入**、**标量是什么**、**怎么重建**；
#   函数体本身仍由代码提供，这是诚实的边界，不是缺陷。
#
# 本模块 import pybamm 是惰性的（只在真的要动 ParameterValues 时导入）。
# ============================================================

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]

EXPORT_VERSION = 1


class ParameterSetMismatch(RuntimeError):
    """文件与活着的参数集不一致（标量漂移或输入指纹变了）。"""


def sha256(path: Path | str, chunk: int = 1 << 20) -> str:
    p = Path(path)
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def _resolve(path: Path | str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else ROOT / p


def collect_scalars(pv) -> Dict[str, object]:
    """纯数值/字符串条目；函数与数组单独归类，不混进来。"""
    out: Dict[str, object] = {}
    for key in pv.keys():
        v = pv[key]
        if isinstance(v, (bool, int, float, str)) or v is None:
            out[str(key)] = v
    return out


def collect_non_scalars(pv) -> Dict[str, Dict[str, str]]:
    """
    函数与其他不可序列化条目：只记录名称与 repr。

    repr 里带地址（0x...）的部分会被抹掉——那种东西每次运行都不同，
    记下来只会让文件看起来在变。
    """
    import re

    out: Dict[str, Dict[str, str]] = {}
    for key in pv.keys():
        v = pv[key]
        if isinstance(v, (bool, int, float, str)) or v is None:
            continue
        r = re.sub(r"0x[0-9a-fA-F]+", "0x...", repr(v))
        kind = "callable" if callable(v) else type(v).__name__
        out[str(key)] = {
            "kind": kind,
            "repr": r[:200],
            "serialisable": False,
            "note": (
                "函数体不入文件：由 recipe 指定的代码重建。"
                "把这条记下来是为了让'改了什么'可审计，而不是为了反序列化。"
            ),
        }
    return out


def export_parameter_set(
    pv,
    out_path: Path | str,
    *,
    set_id: str,
    provenance: Optional[dict] = None,
    inputs: Optional[Iterable[Tuple[Path | str, str]]] = None,
    recipe: Optional[dict] = None,
    metadata: Optional[dict] = None,
) -> Path:
    """
    把一套 ParameterValues 写成一个可归档的 JSON 清单。

    inputs: 可迭代的 (路径, 用途说明)；会逐个记录 sha256。
    recipe: {"module":..., "function":..., "kwargs": {...}} —— 如何重建。
    """
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    input_records: List[dict] = []
    for path, role in (inputs or []):
        p = _resolve(path)
        rec = {"role": role, "path": str(p.relative_to(ROOT))
               if p.is_relative_to(ROOT) else str(p)}
        if p.is_file():
            rec["sha256"] = sha256(p)
            rec["size_bytes"] = p.stat().st_size
        else:
            rec["sha256"] = None
            rec["missing"] = True
        input_records.append(rec)

    payload = {
        "export_version": EXPORT_VERSION,
        "set_id": str(set_id),
        "scalars": collect_scalars(pv),
        "non_scalars": collect_non_scalars(pv),
        "inputs": input_records,
        "recipe": recipe or {},
        "metadata": metadata or {},
        "provenance": provenance or {},
        "wording": (
            "参数集清单：scalars 是数值条目的逐位快照，inputs 是输入文件的 "
            "sha256 指纹，recipe 说明如何重建。函数条目只记录不序列化——"
            "这是诚实的边界，不是缺项。"
        ),
    }
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    return out


def load_parameter_set(path: Path | str) -> dict:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"参数集清单不存在：{p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    if "export_version" not in data:
        raise ValueError(f"{p.name}：不像本模块导出的参数集清单")
    return data


def verify_inputs(loaded: dict, *, strict: bool = True) -> Dict[str, str]:
    """
    重新计算 inputs 的 sha256，与文件里记的比对。

    strict=True 时指纹不符**直接抛错**：一套参数集如果它的输入变了，
    那么归档记录就不再描述它了，必须显式处理而不是继续跑。
    """
    problems: Dict[str, str] = {}
    for rec in loaded.get("inputs", []):
        p = _resolve(rec["path"])
        if not p.is_file():
            problems[rec["path"]] = "文件不存在"
            continue
        got = sha256(p)
        if rec.get("sha256") and got != rec["sha256"]:
            problems[rec["path"]] = "sha256 不符（输入已改变）"
    if problems and strict:
        raise ParameterSetMismatch(
            f"参数集 {loaded.get('set_id')!r} 的输入指纹校验失败：{problems}"
        )
    return problems


def scalar_diff(pv, loaded: dict) -> Dict[str, tuple]:
    """
    活着的参数集 vs 文件快照。返回 {key: (live, file)}，只列**不一致**的键。

    用途：改了一个参数却忘了重新导出时，测试会当场失败。
    """
    live = collect_scalars(pv)
    saved = loaded.get("scalars", {})
    diff: Dict[str, tuple] = {}
    for key in sorted(set(live) | set(saved)):
        a, b = live.get(key, "<absent>"), saved.get(key, "<absent>")
        if isinstance(a, float) and isinstance(b, float):
            if a != b and not (a != a and b != b):      # NaN 视为相等
                diff[key] = (a, b)
        elif a != b:
            diff[key] = (a, b)
    return diff


def apply_scalars(base_pv, loaded: dict):
    """
    把文件里的标量层套回一套 ParameterValues（返回副本）。

    只覆盖文件里出现的键，并要求这些键**原本就存在**——
    往模型里塞一个它不认识的参数会静默地什么都不做，那是最坏的情况。
    """
    pv = base_pv.copy()
    missing = [k for k in loaded.get("scalars", {}) if k not in pv]
    if missing:
        raise KeyError(
            f"参数集 {loaded.get('set_id')!r} 里的这些键在目标集里不存在："
            f"{missing}。拒绝默默忽略。"
        )
    for key, value in loaded.get("scalars", {}).items():
        pv[key] = value
    return pv


def summarise(loaded: dict) -> dict:
    """给报告用的一行摘要。"""
    return {
        "set_id": loaded.get("set_id"),
        "n_scalars": len(loaded.get("scalars", {})),
        "n_non_scalars": len(loaded.get("non_scalars", {})),
        "n_inputs": len(loaded.get("inputs", [])),
        "inputs": [r["path"] for r in loaded.get("inputs", [])],
        "recipe": loaded.get("recipe", {}),
    }
