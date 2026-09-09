# ============================================================
# Generic user-data importer（S3 / S5）
#
# 读 dataset_info.xlsx 的显式声明 + raw/ 下的 csv/xls/xlsx，
# 输出平台 canonical schema 的 DataFrame。
#
# 硬规则：
#   * 不猜 chemistry / 电流符号 / 单位 / 全电池半电池 / 参数集
#   * 一切来自用户在 Excel 里的显式声明
#   * 声明与数据矛盾 -> 报错（不是自动改）
# ============================================================

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from .spec import (
    ALLOWED_CURRENT_SIGN,
    CANONICAL_COLUMNS,
    EXPERIMENT_FIELDS,
    NUMERIC_EXPERIMENT_FIELDS,
    REQUIRED_EXPERIMENT_FIELDS,
    REQUIRED_FIELDS,
    unit_factor_offset,
)

SUPPORTED_SUFFIXES = {".csv", ".xls", ".xlsx"}


class UserInputError(Exception):
    """用户填写/数据本身的问题，需要中文明确提示。"""


# ------------------------------------------------------------------
# dataset_info.xlsx
# ------------------------------------------------------------------
def read_dataset_info(path: Path) -> Tuple[dict, pd.DataFrame]:
    """返回 (experiment_dict, column_mapping_df)。"""
    if not path.is_file():
        raise UserInputError(
            f"找不到 dataset_info.xlsx：{path}\n"
            "请把模板文件夹完整复制一份，并确认文件名没有改动。"
        )

    xl = pd.ExcelFile(path, engine="openpyxl")

    if "experiment" not in xl.sheet_names:
        raise UserInputError(
            "dataset_info.xlsx 缺少 'experiment' 工作表。\n"
            f"当前工作表：{xl.sheet_names}"
        )
    if "column_mapping" not in xl.sheet_names:
        raise UserInputError(
            "dataset_info.xlsx 缺少 'column_mapping' 工作表。\n"
            f"当前工作表：{xl.sheet_names}"
        )

    raw_exp = pd.read_excel(path, sheet_name="experiment")
    exp: Dict[str, object] = {}
    if "field" not in raw_exp.columns or "value" not in raw_exp.columns:
        raise UserInputError(
            "'experiment' 工作表必须包含两列：field（字段名）和 value（取值）。\n"
            f"当前列：{list(raw_exp.columns)}"
        )
    for _, row in raw_exp.iterrows():
        key = str(row["field"]).strip()
        val = row["value"]
        if pd.isna(val):
            val = ""
        exp[key] = val

    # 必填校验
    missing = [
        f for f in REQUIRED_EXPERIMENT_FIELDS
        if str(exp.get(f, "")).strip() == ""
    ]
    if missing:
        names = "、".join(
            next((zh for k, zh, _, _ in EXPERIMENT_FIELDS if k == f), f)
            for f in missing
        )
        raise UserInputError(
            f"dataset_info.xlsx 的 experiment 表缺少必填项：{names}"
            f"（字段名：{', '.join(missing)}）"
        )

    # 数值字段
    for f in NUMERIC_EXPERIMENT_FIELDS:
        v = str(exp.get(f, "")).strip()
        if v == "":
            exp[f] = None
            continue
        try:
            exp[f] = float(v)
        except ValueError:
            raise UserInputError(
                f"experiment 表的 '{f}' 必须填数字，当前是：{v!r}"
            )

    sign = str(exp.get("current_sign", "")).strip()
    if sign not in ALLOWED_CURRENT_SIGN:
        raise UserInputError(
            f"current_sign 只能是 {' 或 '.join(ALLOWED_CURRENT_SIGN)}，"
            f"当前是：{sign!r}"
        )

    mapping = pd.read_excel(path, sheet_name="column_mapping")
    need = {"canonical_field", "source_column", "source_unit"}
    if not need.issubset(set(mapping.columns)):
        raise UserInputError(
            "'column_mapping' 工作表必须包含三列："
            "canonical_field、source_column、source_unit。\n"
            f"当前列：{list(mapping.columns)}"
        )
    mapping["canonical_field"] = mapping["canonical_field"].astype(str).str.strip()
    mapping["source_column"] = mapping["source_column"].astype(str).str.strip()
    mapping["source_unit"] = mapping["source_unit"].astype(str).str.strip()

    filled = {
        str(r["canonical_field"])
        for _, r in mapping.iterrows()
        if str(r["source_column"]) not in ("", "nan")
    }
    lack = [f for f in REQUIRED_FIELDS if f not in filled]
    if lack:
        raise UserInputError(
            "column_mapping 里 time / current / voltage 是必填的，"
            f"当前缺少：{', '.join(lack)}"
        )

    return exp, mapping


# ------------------------------------------------------------------
# raw 文件
# ------------------------------------------------------------------
def find_raw_files(raw_dir: Path) -> List[Path]:
    if not raw_dir.is_dir():
        raise UserInputError(f"找不到 raw 文件夹：{raw_dir}")
    files = sorted(
        p for p in raw_dir.iterdir()
        if p.is_file()
        and p.suffix.lower() in SUPPORTED_SUFFIXES
        and not p.name.startswith("~$")
    )
    if not files:
        raise UserInputError(
            f"raw 文件夹里没有找到数据文件：{raw_dir}\n"
            "请把 .csv / .xls / .xlsx 数据文件放进 raw 文件夹。"
        )
    return files


def read_any(path: Path) -> pd.DataFrame:
    suf = path.suffix.lower()
    if suf == ".csv":
        last_err = None
        for enc in ("utf-8-sig", "gbk", "utf-8", "latin-1"):
            try:
                return pd.read_csv(path, encoding=enc)
            except UnicodeDecodeError as e:
                last_err = e
        raise UserInputError(
            f"无法用常见编码读取 CSV：{path.name}（{last_err}）\n"
            "建议另存为 UTF-8 编码的 CSV 后重试。"
        )
    if suf == ".xlsx":
        return pd.read_excel(path, engine="openpyxl")
    if suf == ".xls":
        return pd.read_excel(path, engine="xlrd")
    raise UserInputError(f"不支持的文件格式：{path.name}")


def _resolve_column(df: pd.DataFrame, name: str, path: Path) -> str:
    """按名字取列；找不到时给出中文提示。"""
    if name in df.columns:
        return name
    stripped = {str(c).strip(): c for c in df.columns}
    if name in stripped:
        return stripped[name]
    raise UserInputError(
        f"数据文件 {path.name} 里找不到列 “{name}”。\n"
        f"该文件实际列名：{list(df.columns)}\n"
        "请打开 dataset_info.xlsx 的 column_mapping 表，把 source_column 改成实际列名。"
    )


# ------------------------------------------------------------------
# canonical 转换
# ------------------------------------------------------------------
def to_canonical(
    raw: pd.DataFrame,
    mapping: pd.DataFrame,
    exp: dict,
    source_name: str,
) -> Tuple[pd.DataFrame, dict]:
    """
    返回 (canonical_df, conversion_log)

    canonical 电流符号：放电 = 正。
    用户在 experiment.current_sign 里声明原始符号，这里按声明翻转。
    """
    log = {
        "source_file": source_name,
        "n_rows_raw": int(len(raw)),
        "declared_current_sign": str(exp.get("current_sign", "")),
        "columns": {},
    }

    out = pd.DataFrame(index=range(len(raw)))

    for _, row in mapping.iterrows():
        field = str(row["canonical_field"]).strip()
        src = str(row["source_column"]).strip()
        unit = str(row["source_unit"]).strip()
        if src in ("", "nan") or field in ("", "nan"):
            continue
        col = _resolve_column(raw, src, Path(source_name))
        vals = pd.to_numeric(raw[col], errors="coerce").to_numpy(dtype=float)
        factor, offset = unit_factor_offset(field, unit)
        vals = vals * factor + offset
        log["columns"][field] = {
            "source_column": src,
            "source_unit": unit,
            "factor": factor,
            "offset": offset,
            "n_nan": int(np.isnan(vals).sum()),
        }
        out[field] = vals

    # 电流符号 -> canonical（放电为正）
    sign = str(exp.get("current_sign", "")).strip()
    if sign == "discharge_negative":
        out["current"] = -out["current"]
        log["current_sign_transform"] = "乘以 -1（原始放电为负）"
    else:
        log["current_sign_transform"] = "不变（原始放电已为正）"

    # 时间：统一减到从 0 开始（平台约定 times relative to segment start）
    t = out["time"].to_numpy(dtype=float)
    finite_t = t[np.isfinite(t)]
    if finite_t.size:
        t0 = float(finite_t[0])
        out["time"] = t - t0
        log["time_offset_s"] = t0

    df = pd.DataFrame(
        {
            "time_s": out.get("time", np.nan),
            "current_A": out.get("current", np.nan),
            "voltage_V": out.get("voltage", np.nan),
            "capacity_Ah": out.get("capacity", np.nan),
            "cycle": out.get("cycle", np.nan),
            "step": out.get("step", np.nan),
            "cell_temperature_C": out.get("temperature", np.nan),
        }
    )
    df["sample_id"] = str(exp.get("sample_id", "")).strip()
    df["protocol_id"] = str(exp.get("protocol", "")).strip()
    df = df[CANONICAL_COLUMNS]

    return df, log


def drop_duplicate_timestamps(df: pd.DataFrame) -> Tuple[pd.DataFrame, int]:
    """保留每个时间戳的第一条（与平台现有 adapter 行为一致）。"""
    t = df["time_s"].to_numpy(dtype=float)
    mask = np.isfinite(t)
    if not mask.all():
        keep_idx = np.flatnonzero(mask)
    else:
        keep_idx = np.arange(len(df))
    sub_t = t[keep_idx]
    _, first = np.unique(sub_t, return_index=True)
    keep = keep_idx[first]
    keep = np.sort(keep)
    dropped = int(len(df) - len(keep))
    return df.iloc[keep].reset_index(drop=True), dropped
