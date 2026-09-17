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

import numpy as np
import pandas as pd

from battery_sim.datasets.material_metadata import (
    load_metadata,
    render,
    structure_available,
    validate,
)
from battery_sim.datasets.ocp_lookup import inverse_ocp, load_ocp_curve
from battery_sim.datasets.template import (
    ROOT,
    CanonicalFormatError,
    NewDatasetAdapter,
)
from battery_sim.excitation.protocol import (
    KIND_PULSE,
    KIND_REST,
    PulseRelaxProtocol,
    Segment,
)

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


def _clean_token(value) -> str:
    """把相位/窗口这类**标签**列规整成干净字符串。

    为什么必须做：该列有空值时 pandas 会把整数读成浮点，`"3"` 变成 `"3.0"`，
    于是窗口 id 成了 `GITT#w3.0`（实测）。数字型标签去掉小数尾巴，
    非数字标签原样保留（真实仪器可能用任意字符串）。
    """
    if value is None:
        return ""
    if isinstance(value, float) and value != value:      # NaN
        return ""
    text = str(value).strip()
    if text.lower() in ("", "nan", "none", "<na>"):
        return ""
    try:
        num = float(text)
    except ValueError:
        return text
    return str(int(num)) if num.is_integer() else text


def _stand_in_config(root_rel: str, cells: Sequence[str] = ()) -> SimpleNamespace:
    """数据未到位时用的最小配置（不写进 configs/datasets.yaml）。

    半电池那几个键（``cell_configuration`` / ``working_electrode``）**必须有**：
    ``resolve_model_options`` 靠它们把模型翻成"石墨在正极槽位"的半电池，
    缺了就会去建全电池并在 'Negative electrode active material volume fraction'
    上 KeyError（G6.1a 踩过同一个坑）。
    """
    return SimpleNamespace(
        dataset_id=DATASET_ID,
        name="Recycled graphite half-cell (CR2032)",
        chemistry="graphite",
        ion="Li",
        raw_dir=root_rel,
        processed_dir=f"{root_rel}/processed",
        parameter_set="Ecker2015_graphite_halfcell",
        extra={
            "source": PENDING_SOURCE,
            "cell_configuration": "half_cell",
            "working_electrode": "positive",
            "physical_working_electrode": "graphite_negative",
            "counter_electrode": "lithium_metal",
            "model_options": {},
        },
        cells=[str(c) for c in cells],
        rates=["C0p2"],
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

        # 样品级 metadata：`metadata/<sample_id>.yaml`，**每样品一份**。
        # 为什么不是数据集级：再生条件/载量/粒径是**样品级**事实 ——
        # fresh / spent / regenerated 三份的处理历史完全不同，
        # 写在数据集级就等于把它们当成同一个材料。
        self.metadata_dir = self.root / "metadata"
        self.sample_metadata: Dict[str, Dict[str, Any]] = {}
        meta_paths = (sorted(self.metadata_dir.glob("*.yaml"))
                      if self.metadata_dir.is_dir() else [])
        for path in meta_paths:
            try:
                entry = load_metadata(path)
            except Exception:
                continue
            sid = str(entry.get("sample_id") or path.stem).strip()
            if sid:
                self.sample_metadata[sid] = entry
        if not getattr(config, "cells", None):
            config.cells = sorted(self.sample_metadata)
        self.samples = [str(c) for c in (getattr(config, "cells", None) or [])]

        # 来源：config 里的占位值要让位给样品 metadata 写明的来源
        # （夹具写的是 "SYNTHETIC FIXTURE —— …"，真实样品会写批次日）
        if self.source == PENDING_SOURCE:
            for sid in sorted(self.sample_metadata):
                cand = str(self.sample_metadata[sid].get("source") or "").strip()
                if cand:
                    self.source = cand
                    break

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
        pending: List[str] = []      # 数据没到位（require_data 会升级为错误）
        gaps: List[str] = []         # 已知空白（未测的项；**不**升级）
        layout: Dict[str, bool] = {}

        # 1 metadata —— 数据集级（若显式给了单个文件）或**每样品一份**
        if self.metadata is not None:
            res = validate(self.metadata)
            errors.extend(res["errors"])
            warnings.extend(res["warnings"])
            # 与逐样品分支同一套路由：结构块"未测"是已知空白，不是数据没到位
            for item in res["pending"]:
                (gaps if item.startswith("structure") else pending).append(item)
        elif self.sample_metadata:
            for sid in sorted(self.sample_metadata):
                res = validate(self.sample_metadata[sid])
                errors.extend(f"[{sid}] {e}" for e in res["errors"])
                warnings.extend(f"[{sid}] {w}" for w in res["warnings"])
                for item in res["pending"]:
                    # "结构块未测（有原因）"是**已知空白**，不是"数据没到位"：
                    # require_data 不该把它升级成错误，否则"确实没做 XRD"
                    # 会被报成"数据缺失"。
                    if item.startswith("structure"):
                        gaps.append(f"[{sid}] {item}")
                    else:
                        pending.append(f"[{sid}] {item}")
            missing_cells = [c for c in self.samples
                             if c not in self.sample_metadata]
            for sid in missing_cells:
                errors.append(
                    f"[{sid}] 没有 metadata —— 缺了它，这个样品的身份与几何都不可追踪"
                )
        else:
            pending.append(
                f"{self._rel(self.metadata_dir)}/ 里没有 metadata —— 从 "
                f"templates/recycled_graphite/metadata.example.yaml 复制成 "
                f"<sample_id>.yaml 再填"
            )

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
        available_blocks: Dict[str, Dict[str, Any]] = {}
        for sid, entry in sorted(self.sample_metadata.items()):
            available_blocks.update(structure_available(entry))
        available_blocks.update(structure_available(self.metadata or {}))
        for block, entry in available_blocks.items():
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
            "gaps": gaps,
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
        """metadata 里声明的电化学/结构文件（相对仓库根），跨样品汇总。"""
        out: List[tuple] = []
        sources: List[tuple] = [(sid, meta) for sid, meta
                                in sorted(self.sample_metadata.items())]
        if self.metadata is not None:
            sources.append((DATASET_ID, self.metadata))
        for sid, meta in sources:
            items = meta.get("measurements") or []
            if isinstance(items, dict):
                items = [items]
            for i, item in enumerate(items):
                if isinstance(item, dict) \
                        and str(item.get("file") or "").strip():
                    tech = str(item.get("technique") or f"#{i}")
                    out.append((f"{sid}/{tech}", str(item["file"]).strip()))
        return out

    # ------------------------------------------------------------------
    # 解析：只认本仓库约定的 CSV 格式
    #
    # 真实仪器导出几乎肯定不一样（编码/表头/相位列名/单位/符号）。
    # 这一层刻意写成**薄**的：源格式一变，只改 `_read_table` 与
    # `normalise_source_table`，其余（切窗口、积分容量、协议解析、
    # 契约校验、初值反演）都是平台自带的，不用重写。
    # ------------------------------------------------------------------
    SOURCE_COLUMNS = ("time_s", "current_A", "voltage_V", "temperature_C",
                      "phase", "window")

    #: 相位词表。相当于 DLR 那份 Basytec 里的 `Command` 列 —— 相位来自数据，
    #: 不靠电流符号猜。
    PHASE_REST = "rest"
    PHASE_DISCHARGE = "discharge"
    PHASE_PULSE = "pulse"

    #: GITT 窗口 id 前缀（窗口 id 在所有样品上同构）
    PROTOCOL_PREFIX = "GITT#w"

    def _read_table(self, rel_path: str, cell: str) -> pd.DataFrame:
        path = ROOT / rel_path
        if not path.is_file():
            raise FileNotFoundError(
                f"dataset '{self.config.dataset_id}': 缺少 '{rel_path}'"
                f"（cell={cell}）。先跑 "
                f"scripts/dev/make_synthetic_recycled_graphite.py，"
                f"或把真实导出放到约定位置。"
            )
        df = pd.read_csv(path)
        missing = [c for c in self.SOURCE_COLUMNS if c not in df.columns]
        if missing:
            raise ValueError(
                f"{rel_path}: 缺列 {missing}；本 adapter 只认 "
                f"{list(self.SOURCE_COLUMNS)}。真实仪器导出请按 "
                f"docs/adding_a_dataset.md §2 改 _read_table/normalise_source_table。"
            )
        # 相位与窗口是**标签**，不能让 pandas 把它们读成数字：
        # 该列有空值时 pandas 会把 "3" 变成 3.0，于是窗口 id 成了 "GITT#w3.0"
        # （实测踩到）。统一规整成干净字符串，数字型标签去掉小数尾巴。
        for col in ("phase", "window"):
            df[col] = df[col].map(_clean_token)
        return df

    def _declared_file(self, technique: str) -> Optional[str]:
        """metadata 里声明的文件路径（单一真源；没有就按约定派生）。"""
        meta = self.metadata or {}
        items = meta.get("measurements") or []
        if isinstance(items, dict):
            items = [items]
        for item in items:
            if isinstance(item, dict) \
                    and str(item.get("technique")) == technique:
                rel = str(item.get("file") or "").strip()
                if rel:
                    return rel
        return None

    def _gcd_rel(self, cell: str) -> str:
        return (self._declared_file("CC_charge_discharge")
                or f"{self._rel(self.root)}/raw/electrochemistry/{cell}_gcd.csv")

    def _gitt_rel(self, cell: str) -> str:
        return (self._declared_file("GITT")
                or f"{self._rel(self.root)}/raw/electrochemistry/{cell}_gitt.csv")

    @property
    def ocp_table_path(self) -> Path:
        """OCP 反演表（两列：stoichiometry, voltage_V）。

        半电池的初值只能由**实测静置 OCV 反演**得到（``initial_soc`` 那套
        电池 SOC 约定对 Li 金属半电池不适用），而反演需要这张表。
        与 DLR adapter 同一做法，用的是共享的 ``ocp_lookup``。
        """
        rel = str(self._extra.get("ocp_table_rel") or
                  f"{self._rel(self.root)}/processed/ocp_graphite.csv")
        return ROOT / rel

    # ---------------- 五个 hook ----------------
    def read_source_table(self, cell) -> pd.DataFrame:
        """读**放电记录**（GCD）的原始表。GITT 走 :meth:`read_gitt_table`。"""
        return self._read_table(self._gcd_rel(str(cell)), str(cell))

    def read_gitt_table(self, cell) -> pd.DataFrame:
        return self._read_table(self._gitt_rel(str(cell)), str(cell))

    def normalise_source_table(self, raw: pd.DataFrame, cell) -> pd.DataFrame:
        """列映射 + **在数据内验证符号**。

        符号这种事没法自动判定：源文件用「负=放电」（Basytec 那样）时，
        表里看不出任何异常。所以这里做的是**声明后核对** ——
        放电相位的电流必须为正（平台约定），否则报错而不是猜。
        """
        df = raw.copy()
        df["phase"] = df["phase"].astype(str).str.strip().str.lower()
        if "temperature_ambient_C" not in df.columns:
            df["temperature_ambient_C"] = df["temperature_C"]
        dis = df[df["phase"] == self.PHASE_DISCHARGE]
        if len(dis) and not bool((dis["current_A"] > 0).all()):
            raise CanonicalFormatError(
                f"{cell}: 标为 discharge 的采样里有非正电流 —— "
                f"源文件可能是「负=放电」（需要翻转），或者相位列标错了。"
                f"平台约定：**放电为正**。"
            )
        return df

    def select_discharge_window(self, raw, cell, rate) -> pd.DataFrame:
        """切出放电段并按平台约定重基时间、积分容量。

        仪器只给 t/I/V；``capacity_Ah`` 由平台积分得到（不是仪器另算的列，
        否则两列会悄悄指向不同的窗口 —— 模板自检专门对账过这件事）。
        """
        df = raw[raw["phase"] == self.PHASE_DISCHARGE].reset_index(drop=True)
        if df.empty:
            raise ValueError(f"{cell}: 记录里没有 discharge 段")
        t = df["time_s"].to_numpy(float)
        t = t - t[0]                      # canonical：相对窗口起点，从 0 开始
        i = df["current_A"].to_numpy(float)
        cap = np.concatenate([[0.0], np.cumsum(0.5 * (i[1:] + i[:-1])
                                              * np.diff(t))]) / 3600.0
        return pd.DataFrame({
            "time_s": t,
            "current_A": i,
            "voltage_V": df["voltage_V"].to_numpy(float),
            "capacity_Ah": cap,
            "temperature_ambient_C": df["temperature_ambient_C"].to_numpy(float),
        })

    def read_initial_state(self, cell) -> float:
        """**实测**静置 OCV（V）：取记录开头静置段的中位数。

        不要用第一条采样点的电压：那是带电流时的电压，含过电位。
        """
        raw = self.read_source_table(str(cell))
        rest = raw[raw["phase"].astype(str).str.strip().str.lower()
                   == self.PHASE_REST]
        if rest.empty:
            raise ValueError(
                f"{cell}: 记录里没有静置段 —— 无法从实测 OCV 反演初值"
                f"（半电池不能用 initial_soc 那套约定）"
            )
        head = rest["voltage_V"].iloc[: max(1, len(rest) // 3)]
        return float(head.median())

    def read_ambient_temperature(self, cell) -> float:
        raw = self.read_source_table(str(cell))
        return float(raw["temperature_C"].median())

    # ---------------- 录制型协议（GITT 窗口） ----------------
    def list_protocols(self) -> List[str]:
        """**窗口级** id（``GITT#w1``…）。只返回 ``load_protocol`` 能接受的 id。

        （这条规矩是从 dlr_gitt 的实测 wart 来的：那里 ``list_protocols``
        广告了扫程级 id，而扫程级 id 其实载入不了。）
        """
        windows: set = set()
        for cell in self.list_cells():
            try:
                raw = self.read_gitt_table(str(cell))
            except Exception:
                continue
            for value in raw["window"].dropna().astype(str):
                token = value.strip()
                if token and token.lower() != "nan":
                    windows.add(token)
        return [f"{self.PROTOCOL_PREFIX}{w}" for w in sorted(
            windows, key=lambda x: int(x) if str(x).isdigit() else 0)]

    def _window_token(self, protocol_id: str) -> str:
        raw = str(protocol_id).strip()
        if raw.startswith(self.PROTOCOL_PREFIX):
            raw = raw[len(self.PROTOCOL_PREFIX):]
        if not raw:
            raise ValueError(f"空的窗口 id：{protocol_id!r}")
        return raw

    def _protocol_rows(self, cell: str, protocol_id: str):
        token = self._window_token(protocol_id)
        raw = self.read_gitt_table(str(cell))
        sel = raw[raw["window"].astype(str).str.strip() == token]
        sel = sel.reset_index(drop=True)
        if sel.empty:
            raise ValueError(
                f"{protocol_id}: 该窗口在 {cell} 的记录里不存在；"
                f"可用 {self.list_protocols()}"
            )
        return sel

    def _segments(self, sel: pd.DataFrame):
        """按相位**连续段**切分（相位来自数据，不靠电流符号猜）。"""
        phases = sel["phase"].astype(str).str.strip().str.lower().to_numpy()
        t = sel["time_s"].to_numpy(float)
        t = t - t[0]
        i = sel["current_A"].to_numpy(float)
        v = sel["voltage_V"].to_numpy(float)
        out = []
        start = 0
        for k in range(1, len(phases) + 1):
            if k < len(phases) and phases[k] == phases[start]:
                continue
            name = phases[start]
            kind = KIND_PULSE if name == self.PHASE_PULSE else KIND_REST
            out.append(Segment(
                kind=kind,
                t_start_s=float(t[start]),
                t_stop_s=float(t[k - 1]),
                current_A=float(i[start]),
                label=f"{name}@{t[start]:.0f}s",
                voltage_start_V=float(v[start]),
                voltage_end_V=float(v[k - 1]),
                row_start=int(start),
                row_stop=int(k),
            ))
            start = k
        return tuple(out), t, i, v, phases

    def load_protocol(self, protocol_id: str):
        cells = self.list_cells()
        cell = str(cells[0]) if cells else ""
        return self._protocol_for(cell, protocol_id)

    def _protocol_for(self, cell: str, protocol_id: str):
        sel = self._protocol_rows(cell, protocol_id)
        segments, t, _, _, _ = self._segments(sel)
        return PulseRelaxProtocol(
            protocol_id=str(protocol_id),
            segments=segments,
            temperature_C=float(sel["temperature_C"].median()),
            source={
                "dataset": self.config.dataset_id,
                "cell": cell,
                "file": self._gitt_rel(cell),
                "phase_source": "CSV 'phase' 列（不靠电流符号猜相位）",
            },
        )

    def load_processed_protocol(self, cell, protocol_id) -> pd.DataFrame:
        cell = str(cell)
        sel = self._protocol_rows(cell, protocol_id)
        protocol = self._protocol_for(cell, protocol_id)
        segments, t, i, v, _ = self._segments(sel)
        cap = np.concatenate([[0.0], np.cumsum(0.5 * (i[1:] + i[:-1])
                                              * np.diff(t))]) / 3600.0
        out = pd.DataFrame({
            "time_s": t,
            "current_A": i,
            "voltage_V": v,
            "capacity_Ah": cap,
            "temperature_ambient_C": sel["temperature_C"].to_numpy(float),
        })
        out.attrs["provenance"] = {
            "dataset": self.config.dataset_id,
            "cell": cell,
            "protocol_id": str(protocol_id),
            "file": self._gitt_rel(cell),
            "phase_source": "CSV 'phase' 列",
            "sign_convention": "discharge = +A（normalise 阶段已核对）",
        }
        out.attrs["protocol"] = protocol.as_dict()
        # 初值必须来自**这个窗口自己的**脉冲前静置：用数据集级初值会让所有窗口
        # 从同一个状态出发，六个窗口的读数逐位相同（实测踩到，
        # 看起来像"协议无所谓"）。
        out.attrs["initialisation"] = self.initialisation_block(
            cell, v0=self._pre_pulse_rest(sel))
        return out

    # ---------------- 初值：反演实测静置 OCV ----------------
    def _pre_pulse_rest(self, sel: pd.DataFrame) -> float:
        """窗口内**脉冲前那段静置**的中位电压 —— 这个窗口探测的电化学状态。

        用它而不是数据集级初值：否则每个窗口都从同一状态出发，
        窗口之间的差异消失，"哪个窗口有信息"就问不出来了。
        """
        phase = sel["phase"].astype(str).str.strip().str.lower()
        rest = sel[phase == self.PHASE_REST]
        if rest.empty:
            raise ValueError("窗口里没有脉冲前静置段，无法定初值")
        # 第一个 rest 段（脉冲之前）
        v = rest["voltage_V"].to_numpy(float)
        k = 1
        ph = phase.to_numpy()
        while k < ph.size and ph[k] == self.PHASE_REST:
            k += 1
        v = sel["voltage_V"].to_numpy(float)[:k]
        return float(np.median(v))

    def initialisation_block(self, cell: str,
                             v0: Optional[float] = None) -> Dict[str, Any]:
        """平台约定的 ``initialisation`` 块（fixed_initial_concentration）。

        半电池的 ``initial_soc`` 不适用；不声明这个块会让默认初值直接撞
        "Maximum voltage [V]" 事件（实测 SolverError）。
        ``v0`` 给定时用**窗口自己的**静置 OCV（见 :meth:`_pre_pulse_rest`）。
        """
        if v0 is None:
            v0 = self.read_initial_state(cell)
        v0 = float(v0)
        sto, vv = load_ocp_curve(self.ocp_table_path)
        x0 = inverse_ocp(sto, vv, v0)
        return {
            "method": "fixed_initial_concentration",
            "concentration_parameter":
                "Initial concentration in positive electrode [mol.m-3]",
            "max_concentration_parameter":
                "Maximum concentration in positive electrode [mol.m-3]",
            "stoichiometry_from_ocp": float(x0),
            "ocp_voltage_V": float(v0),
            "mapping_reason": (
                f"measured rest OCV {v0:.4f} V -> x0 = {x0:.4f} "
                f"via {self._rel(self.ocp_table_path)}"
            ),
        }

    # ------------------------------------------------------------------
    def material_summary(self, cell: Optional[str] = None) -> str:
        """某一份样品的材料清单（默认第一份）。"""
        meta = None
        if cell is not None:
            meta = self.sample_metadata.get(str(cell))
        if meta is None and self.sample_metadata:
            meta = self.sample_metadata[sorted(self.sample_metadata)[0]]
        if meta is None:
            meta = self.metadata
        if meta is None:
            return render(None)
        return render(meta, validate(meta))


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
    for item in result.get("gaps", []):
        lines.append(f"  GAP     {item}")
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
