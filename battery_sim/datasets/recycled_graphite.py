# ============================================================
# 回收石墨半电池 adapter —— 数据未到位时也能 import、能自检
#
# 为什么它现在就能落地
#   数据契约（metadata）与平台契约（canonical 四列）都可以**先于数据**定下来。
#   这一步做完，实验数据到手时的工作只剩"填 metadata + 跑自检"，而不是"设计字段"。
#   所以本模块有两种用法：
#
#   ① 数据未到位（现在）：
#        python -m battery_sim.datasets.recycled_graphite --validate
#      只检查**结构与契约**：目录布局、metadata 合法性、哪些测量还缺
#      （缺 = pending，**不是 error** —— 那时"还没做实验"，不是"做错了"）。
#
#   ② 数据到位后：
#      把 templates/recycled_graphite/datasets_yaml_snippet.yaml 的块贴进
#      configs/datasets.yaml，实现下面 5 个 hook，然后
#        python -m battery_sim.datasets.template --check recycled_graphite
#      （模板自检比本模块的 --validate 更严：它会真的读数据并验 canonical 契约。）
#
# 三条口径（写在这里，因为它决定字段怎么填）
#   1. **fresh 参照必须是本实验室自己的 G0**。公开数据集（SINTEF/DLR/CALCE）
#      不能当 baseline：不同批料、不同仪器、不同配方之间的差异不可归因。
#   2. **粒径处理前后都要测**。D ∝ R²：粒径差 2 倍 = D_s 差 4 倍，
#      而"回收料的容量恢复"常常来自破碎与细粉，不是本征改善。
#   3. **结构表征只填测量量**（d002_nm / id_ig / surface_area_m2_g），
#      不填"缺陷多/石墨化好"这类解释 —— 那条关联属于分析层（Phase 3）。
#
# 目录布局（样品是 metadata 里的字段，**不是**目录层级：否则加一个样品就要改代码）
#   data/raw/LIB/recycled_graphite/
#     metadata.yaml
#     raw/electrochemistry/{gcd,gitt,eis}.<ext>     ← 半电池 GCD / GITT / EIS
#     raw/structure/{xrd,raman,bet}.<ext>
#     processed/canonical.csv
# ============================================================

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

from battery_sim.datasets.material_metadata import (
    load_metadata,
    render,
    structure_available,
    validate,
)
from battery_sim.datasets.template import ROOT, NewDatasetAdapter

DATASET_ID = "recycled_graphite"

#: 数据未到位时的占位来源。它不是"来源"，所以自检会把它报成 pending。
PENDING_SOURCE = "PENDING —— 数据到达前占位（本实验室批次/日期待填）"

#: 期望的目录（相对 dataset root）
LAYOUT_DIRS = ("raw/electrochemistry", "raw/structure", "processed")

#: 元数据文件名（样品/再生条件/几何/粒径/测了什么 都在里面）
METADATA_NAME = "metadata.yaml"

DEFAULT_ROOT_REL = "data/raw/LIB/recycled_graphite"
DEFAULT_METADATA_REL = f"{DEFAULT_ROOT_REL}/{METADATA_NAME}"

#: 结构块 → 它必须给出的那个关键测量量（报告里只报这个数）
STRUCTURE_KEY_FIELD = {
    "xrd": "d002_nm",
    "raman": "id_ig",
    "bet": "surface_area_m2_g",
}


def _stand_in_config(root_rel: str) -> SimpleNamespace:
    """数据未到位时用的最小配置（不写进 configs/datasets.yaml）。"""
    return SimpleNamespace(
        dataset_id=DATASET_ID,
        name="Recycled graphite half-cell (CR2032)",
        chemistry="graphite",
        ion="Li",
        raw_dir=root_rel,
        processed_dir=f"{root_rel}/processed",
        extra={"source": PENDING_SOURCE},
        cells=[],
        rates=[],
        nominal_capacity_Ah=None,
        lower_voltage_cutoff_V=None,
        upper_voltage_cutoff_V=None,
    )


class RecycledGraphiteAdapter(NewDatasetAdapter):
    """回收石墨半电池。数据未到位时用 :meth:`validate` 检查契约。"""

    def __init__(self, config=None, *, root=None, metadata_path=None):
        if config is None:
            config = _stand_in_config(str(root or DEFAULT_ROOT_REL))
        super().__init__(config)
        self.root = (Path(root) if root is not None
                     else ROOT / str(config.raw_dir))
        self.metadata_path = (Path(metadata_path) if metadata_path is not None
                              else self.root / METADATA_NAME)
        self.metadata: Optional[Dict[str, Any]] = None
        if self.metadata_path.is_file():
            self.metadata = load_metadata(self.metadata_path)

    # ------------------------------------------------------------------
    # 自检（导师定义的 Step 2 通过条件：空模板也过）
    # ------------------------------------------------------------------
    def validate(self, *, require_data: bool = False) -> Dict[str, Any]:
        """结构 + 契约自检。

        返回 ``{ok, errors, warnings, pending, root, metadata, layout}``。

        * ``ok=True`` 的含义是 **契约成立、等数据**（因此 pending 不影响 ok）。
        * ``require_data=True`` 时"数据不在"升级为 error —— 用于数据到手后的复核。
        """
        errors: List[str] = []
        warnings: List[str] = []
        pending: List[str] = []
        layout: Dict[str, bool] = {}

        # 1 metadata
        if self.metadata is None:
            pending.append(
                f"{self._rel(self.metadata_path)} 未建 —— 从 "
                f"templates/recycled_graphite/metadata.example.yaml 复制一份填"
            )
        else:
            res = validate(self.metadata)
            errors.extend(res["errors"])
            warnings.extend(res["warnings"])
            pending.extend(res["pending"])

        # 2 目录布局
        for rel_dir in LAYOUT_DIRS:
            exists = (self.root / rel_dir).is_dir()
            layout[rel_dir] = exists
            if not exists:
                pending.append(f"目录 {rel_dir}/ 未建")

        # 3 声明了的测量文件在不在
        declared = self._declared_files()
        for what, rel_path in declared:
            if not (ROOT / rel_path).is_file():
                pending.append(f"{what} 文件未就位：{rel_path}")

        # 4 结构块声明 available=true 就要有文件
        for block, entry in structure_available(self.metadata or {}).items():
            rel_path = str(entry.get("file") or "").strip()
            if not rel_path:
                errors.append(f"structure.{block}.available=true 但没有 file")
                continue
            if not (ROOT / rel_path).is_file():
                pending.append(f"结构 {block} 文件未就位：{rel_path}")

        # 5 占位来源
        if self.source == PENDING_SOURCE:
            if require_data:
                errors.append(
                    "extra.source 仍是占位值 —— 数据到手时必须填真实来源"
                    "（哪一批、谁做的、日期）"
                )
            else:
                pending.append("extra.source 待填真实来源（configs 的 extra.source）")

        if require_data:
            for item in list(pending):
                errors.append(f"（require_data）{item}")
            pending = []

        return {
            "ok": not errors,
            "errors": errors,
            "warnings": warnings,
            "pending": [] if require_data else pending,
            "root": self._rel(self.root),
            "metadata": self._rel(self.metadata_path),
            "layout": layout,
            "n_declared_files": len(declared),
            "structure_available": sorted(
                structure_available(self.metadata or {})),
        }

    # ------------------------------------------------------------------
    def _rel(self, path: Path) -> str:
        try:
            return str(Path(path).resolve().relative_to(ROOT)).replace("\\", "/")
        except ValueError:
            return str(path)

    def _declared_files(self) -> List[tuple]:
        """metadata 里声明的电化学/结构文件（相对仓库根）。"""
        out: List[tuple] = []
        meta = self.metadata or {}
        items = meta.get("measurements") or []
        if isinstance(items, dict):
            items = [items]
        for i, item in enumerate(items):
            if isinstance(item, dict) and str(item.get("file") or "").strip():
                tech = str(item.get("technique") or f"#{i}")
                out.append((f"{tech}", str(item["file"]).strip()))
        return out

    # ------------------------------------------------------------------
    # 数据到位后才用得上的 hook（现在故意留 NotImplementedError）
    # ------------------------------------------------------------------
    def read_source_table(self, cell) -> pd.DataFrame:
        raise NotImplementedError(
            f"{type(self).__name__}.read_source_table 未实现。\n"
            f"  按 docs/adding_a_dataset.md §2 先问清 10 个格式问题"
            f"（编码 / 表头行数 / 相位列 / 符号 / 单位 / 时间基准 / 分段）。"
        )

    def normalise_source_table(self, raw: pd.DataFrame, cell) -> pd.DataFrame:
        raise NotImplementedError(
            f"{type(self).__name__}.normalise_source_table 未实现。"
        )

    def select_discharge_window(self, raw, cell, rate) -> pd.DataFrame:
        raise NotImplementedError(
            f"{type(self).__name__}.select_discharge_window 未实现。"
        )

    def read_initial_state(self, cell) -> float:
        raise NotImplementedError(
            f"{type(self).__name__}.read_initial_state 未实现（静置后的实测 OCV）。"
        )

    def read_ambient_temperature(self, cell) -> float:
        raise NotImplementedError(
            f"{type(self).__name__}.read_ambient_temperature 未实现。"
            f"若温度逐点记录在文件里，就实现它；否则在 configs 写 "
            f"extra.ambient_temperature_C。"
        )

    # ------------------------------------------------------------------
    def material_summary(self) -> str:
        if self.metadata is None:
            return render(None)
        return render(self.metadata, validate(self.metadata))


def render_check(result: Dict[str, Any], *, name: str = DATASET_ID) -> str:
    """把自检结果排成人能读的清单。"""
    lines = [f"=== {name} 结构自检 ==="]
    lines.append(f"root       : {result['root']}")
    lines.append(f"metadata   : {result['metadata']}")
    lines.append("layout     : " + ", ".join(
        f"{d}{'✓' if ok else '✗'}" for d, ok in sorted(result["layout"].items())
    ))
    lines.append(f"declared   : {result['n_declared_files']} 个测量文件")
    if result["structure_available"]:
        lines.append(f"structure  : {result['structure_available']} 已声明可用")
    for item in result["errors"]:
        lines.append(f"  ERROR   {item}")
    for item in result["warnings"]:
        lines.append(f"  WARN    {item}")
    for item in result["pending"]:
        lines.append(f"  PENDING {item}")
    lines.append(
        f"=== {'PASS' if result['ok'] else 'FAIL'}"
        f"（{len(result['errors'])} 错 / {len(result['warnings'])} 警 / "
        f"{len(result['pending'])} 待办）==="
    )
    if result["ok"] and result["pending"]:
        lines.append(
            "说明：PASS 的含义是**契约成立、等数据**。"
            "PENDING 项要等实验做完再补，不是错误。"
        )
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m battery_sim.datasets.recycled_graphite",
        description="回收石墨数据集的结构自检（数据未到位也能跑）",
    )
    parser.add_argument("--validate", action="store_true",
                        help="检查目录布局 + metadata 契约（默认动作）")
    parser.add_argument("--require-data", action="store_true",
                        help="把「数据未就位」升级为错误（数据到手后用）")
    parser.add_argument("--root", default=None, help="数据集根目录（默认占位路径）")
    parser.add_argument("--metadata", default=None, help="metadata.yaml 路径")
    parser.add_argument("--summary", action="store_true",
                        help="顺便打印材料元数据清单")
    args = parser.parse_args(argv)

    adapter = RecycledGraphiteAdapter(root=args.root,
                                     metadata_path=args.metadata)
    result = adapter.validate(require_data=args.require_data)
    print(render_check(result))
    if args.summary:
        print()
        print(adapter.material_summary())
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "DATASET_ID",
    "DEFAULT_METADATA_REL",
    "DEFAULT_ROOT_REL",
    "LAYOUT_DIRS",
    "METADATA_NAME",
    "PENDING_SOURCE",
    "STRUCTURE_KEY_FIELD",
    "RecycledGraphiteAdapter",
    "main",
    "render_check",
]
