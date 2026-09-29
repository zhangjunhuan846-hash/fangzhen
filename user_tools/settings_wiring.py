#!/usr/bin/env python
# ============================================================
# settings_hash 接线器 —— 把指纹填进 run_record 的四个槽位
#
# 为什么需要这个文件（缺口 3 的**下半截**）
#
#   `governance/settings_hash.py` 本身是对的，而且有测试。问题是：
#   **没有任何代码去填 run_record 里的四个槽位。** 实测证据：
#
#       grep -rn "settings_hash_per_level" --include=*.py . | grep -v tests/
#       -> 0 命中
#
#   而模板里槽位是齐的（run_record.yaml:58-61）。这正是本仓库反复出现的
#   "机制有了、没人用" —— 模板里挖了坑，没人往里放东西。坑的存在感
#   让人以为缺口已填。
#
# 这个工具只做一件事：读若干份 run_metadata.json → 复算指纹 → 比对 →
# 输出可直接粘进 run_record 的四个槽位。
#
# ⚠️ 一个必须说清的现实（不要让它被"自动填充"掩盖）
#
#   实测 2026-09-29：`outputs/` 下 **61 份 run_metadata.json，0 份**
#   带 `solver` / `model_options` 块（它们是 2026-09-28 才写进产物的）。
#   也就是说**现有的 run 一份都不能复算指纹**。
#
#   这不是本工具的缺陷，是**数据的历史事实**。所以本工具：
#     · 默认 on_missing="mark" —— 把不可复算的 run 显式排除，并在输出里
#       逐条列出"为什么排除了"。**绝不静默套默认值**（那会造出
#       "13 份不同数据集的 run 共用同一指纹 f4ddab..." 那种虚假的相同）。
#     · 比对时只要**有任何一层不可复算**，`settings_identical_across_levels`
#       就写 `"unknown"` 而**不是** `true`。
#       —— 三层比对的结论依赖这个门；门没关上时给 true 是**说假话**。
#
# 用法
#   # 三层的 run_metadata 各给一份（层级名=路径）
#   python -m user_tools.settings_wiring \
#       --level M0=outputs/.../M0/run_metadata.json \
#       --level M1=outputs/.../M1/run_metadata.json \
#       --level M2=outputs/.../M2/run_metadata.json
#
#   # 只想看看某一份能不能复算（--check）
#   python -m user_tools.settings_wiring --level M0=<path> --check
#
#   # 机器可读
#   python -m user_tools.settings_wiring --level M0=<path> ... --json
#
#   # 把结果写回 run_record（**默认只打印，不写盘**）
#   python -m user_tools.settings_wiring ... --write templates/commercial_graphite_ht/run_record.yaml
#
# 退出码
#   0  正常（含"不可复算"这种正常结论 —— 它是事实，不是错误）
#   1  输入问题（路径不存在 / JSON 坏 / 层级名重复）
#   2  设置确实不一致（三层比对的前置门失败 —— 这是一条**结论级**红线）
# ============================================================

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from governance.settings_hash import (  # noqa: E402
    KNOWN_LIMITS,
    MissingSettingsError,
    assert_same_settings,
    missing_fingerprint_fields,
    payload_from_run_metadata,
)

#: 槽位名 —— 与 templates/.../run_record.yaml:58-61 一字不差。
#: 写死在这里是为了让"填错名字"在测试里就红，而不是等粘进模板才发现。
SLOT_PER_LEVEL = "settings_hash_per_level"
SLOT_IDENTICAL = "settings_identical_across_levels"
SLOT_DIFF_DETAIL = "settings_diff_detail"
SLOT_KNOWN_LIMITS = "settings_hash_known_limits"

#: 「三层设置是否相同」的第三态。
#: **必须有第三态**：只要有一层不可复算，就既不能写 true 也不能写 false。
#: 二值化的结果是"没查也说一样"。
UNKNOWN = "unknown"


def _parse_levels(pairs: List[str]) -> Tuple[List[str], Dict[str, Path]]:
    """把 ``["M0=a.json", "M1=b.json"]`` 解析成有序的名字→路径。"""
    names: List[str] = []
    paths: Dict[str, Path] = {}
    for raw in pairs:
        if "=" not in raw:
            raise SystemExit(
                f"--level 需要 NAME=PATH 形式，收到 {raw!r}（缺 '='）"
            )
        name, _, p = raw.partition("=")
        name = name.strip()
        if not name:
            raise SystemExit(f"--level 的层级名不能为空：{raw!r}")
        if name in paths:
            raise SystemExit(
                f"层级名重复：{name!r} —— 名字是比对表的主键，重复会让两层互相覆盖"
            )
        path = Path(p)
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        if not path.exists():
            raise SystemExit(f"找不到 run_metadata.json：{path}")
        names.append(name)
        paths[name] = path
    if not names:
        raise SystemExit("至少要给一个 --level")
    return names, paths


def _read_meta(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SystemExit(f"{path} 不是合法 JSON：{e}") from e


def collect(
    names: List[str],
    paths: Mapping[str, Path],
    *,
    t_eval_by_level: Optional[Mapping[str, List[float]]] = None,
) -> Dict[str, Any]:
    """读 → 复算指纹 → 比对，返回四个槽位的值。

    分工明确：
      · ``payload_from_run_metadata`` 负责"缺字段就不许算"（它自己会抛/标）
      · 本函数负责"把不可复算的一层**显式排除**，并让结果落进第三态"
    """
    payloads: Dict[str, Any] = {}
    unfingerprintable: Dict[str, Any] = {}
    missing_fields: Dict[str, List[str]] = {}

    for name in names:
        meta = _read_meta(paths[name])
        # on_missing="mark"：不可复算时返回 {"__unfingerprintable__": {...}}
        # 而不是抛错，也不是套默认值。后面统一处理。
        p = payload_from_run_metadata(
            meta,
            t_eval=(t_eval_by_level or {}).get(name),
            on_missing="mark",
        )
        if "__unfingerprintable__" in p:
            unfingerprintable[name] = p["__unfingerprintable__"]
        else:
            payloads[name] = p
        miss = missing_fingerprint_fields(meta)
        if miss:
            missing_fields[name] = miss

    result: Dict[str, Any] = {
        SLOT_PER_LEVEL: {n: None for n in names},
        SLOT_IDENTICAL: UNKNOWN,
        SLOT_DIFF_DETAIL: "",
        SLOT_KNOWN_LIMITS: list(KNOWN_LIMITS),
        "_unfingerprintable": unfingerprintable,
        "_missing_fields": missing_fields,
    }

    # 只有**可复算的层**参与比对。这是关键的一步：
    # 拿不可复算层去做比对，等于用默认值比对，会得出"相同"这种假结论。
    comparable = [n for n in names if n in payloads]

    # 先算可复算层的指纹并**无条件写进槽位** —— 哪怕只有一层、不足以比对。
    # （这一条是测试逼出来的：早先版本在"可比层<2"时提前 return，
    #   把已经算出来的那一层指纹也丢了，于是"哪些层可复算"这个信息
    #   在产物里完全消失。不可复算要可见，可复算**也要可见**。）
    for n in comparable:
        result[SLOT_PER_LEVEL][n] = _hash_of(payloads[n])

    if len(comparable) < 2:
        result[SLOT_IDENTICAL] = UNKNOWN
        result[SLOT_DIFF_DETAIL] = (
            f"可复算的层只有 {len(comparable)} 层（{comparable}），"
            f"不足以比对；不可复算：{sorted(unfingerprintable)}"
        )
        return result

    try:
        res = assert_same_settings({n: payloads[n] for n in comparable})
    except ValueError as e:
        # 设置真的不一致 —— 这是要传给调用方的一条**结论级**红线，
        # 但本函数不抛，而是把它写进槽位（退出码由 main 决定）。
        result[SLOT_IDENTICAL] = False
        result[SLOT_DIFF_DETAIL] = str(e)
        result["_inconsistent"] = True
        return result

    result[SLOT_IDENTICAL] = True if len(comparable) == len(names) else UNKNOWN
    if result[SLOT_IDENTICAL] == UNKNOWN:
        result[SLOT_DIFF_DETAIL] = (
            f"可比层 {comparable} 之间设置相同；但 {sorted(unfingerprintable)} "
            f"不可复算（缺 solver/model_options），故整体判定为 '{UNKNOWN}' "
            f"—— **不许**据此宣称三层设置一致。"
        )
    return result


def _hash_of(payload: Mapping[str, Any]) -> str:
    """与 settings_hash._hash_payload 同源（此处只用于不一致时的展示）。"""
    import hashlib

    from governance.settings_hash import _canon  # type: ignore

    blob = json.dumps(_canon(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def render(result: Mapping[str, Any]) -> str:
    """人类可读输出。**先说清哪些层不能用**，再报结论。"""
    lines: List[str] = []
    lines.append("=" * 76)
    lines.append("settings_hash 接线 —— 三层数值设置指纹")
    lines.append("=" * 76)

    unfp = result.get("_unfingerprintable") or {}
    miss = result.get("_missing_fields") or {}

    if unfp:
        lines.append("")
        lines.append(f"⚠ {len(unfp)} 层**不可复算指纹**（不是错误，是历史事实）：")
        for n, info in unfp.items():
            lines.append(f"    [{n}] 缺字段：{miss.get(n)}")
        lines.append("    原因：solver / model_options 是 2026-09-28 才写进产物的；")
        lines.append("    更早的 run 没记录它们 ⇒ 当时设置不可知。")
        lines.append("    处理：只对**新跑**的 run 用指纹；旧 run 请重跑，或明确接受'不可比'。")

    lines.append("")
    lines.append(f"{SLOT_PER_LEVEL}:")
    for n, h in result[SLOT_PER_LEVEL].items():
        lines.append(f"    {n}: {h if h else 'null  <- 不可复算'}")
    lines.append("")
    lines.append(f"{SLOT_IDENTICAL}: {result[SLOT_IDENTICAL]!r}")
    if result[SLOT_DIFF_DETAIL]:
        lines.append(f"{SLOT_DIFF_DETAIL}:")
        for ln in str(result[SLOT_DIFF_DETAIL]).splitlines():
            lines.append(f"    {ln}")
    lines.append("")
    lines.append(f"{SLOT_KNOWN_LIMITS}: {len(result[SLOT_KNOWN_LIMITS])} 条（随结论一起引用）")
    return "\n".join(lines)


def _emit_yaml_block(result: Mapping[str, Any]) -> str:
    import yaml

    body = {
        SLOT_PER_LEVEL: {k: (v if v else None) for k, v in result[SLOT_PER_LEVEL].items()},
        SLOT_IDENTICAL: result[SLOT_IDENTICAL],
        SLOT_DIFF_DETAIL: result[SLOT_DIFF_DETAIL],
        SLOT_KNOWN_LIMITS: result[SLOT_KNOWN_LIMITS],
    }
    return yaml.safe_dump(body, allow_unicode=True, sort_keys=False, default_flow_style=False)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m user_tools.settings_wiring",
        description="把 settings_hash 的指纹填进 run_record 的四个槽位",
    )
    ap.add_argument("--level", action="append", default=[],
                    metavar="NAME=PATH", help="层级名=run_metadata.json 路径（可重复）")
    ap.add_argument("--check", action="store_true",
                    help="只回答'能不能复算'，不做比对")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    ap.add_argument("--write", metavar="RUN_RECORD_YAML", default=None,
                    help="把四个槽位写回 run_record（默认只打印）")
    args = ap.parse_args(argv)

    names, paths = _parse_levels(args.level)

    if args.check:
        rc = 0
        for n in names:
            meta = _read_meta(paths[n])
            m = missing_fingerprint_fields(meta)
            state = "可复算" if not m else f"不可复算（缺 {m}）"
            print(f"[{n}] {state}  <- {paths[n]}")
            if m:
                rc = rc  # 不可复算本身不是失败；保持 0
        return rc

    result = collect(names, paths)

    if args.json:
        pub = {k: v for k, v in result.items() if not k.startswith("_")}
        pub["_unfingerprintable"] = result.get("_unfingerprintable", {})
        print(json.dumps(pub, ensure_ascii=False, indent=2, default=str))
    else:
        print(render(result))

    if args.write:
        target = Path(args.write)
        if not target.is_absolute():
            target = (Path.cwd() / target).resolve()
        if not target.exists():
            print(f"\n--write 目标不存在：{target}", file=sys.stderr)
            return 1
        import yaml

        doc = yaml.safe_load(target.read_text(encoding="utf-8"))
        new = {
            SLOT_PER_LEVEL: {k: (v if v else None) for k, v in result[SLOT_PER_LEVEL].items()},
            SLOT_IDENTICAL: result[SLOT_IDENTICAL],
            SLOT_DIFF_DETAIL: result[SLOT_DIFF_DETAIL],
            SLOT_KNOWN_LIMITS: result[SLOT_KNOWN_LIMITS],
        }
        for k, v in new.items():
            if k not in doc:
                print(f"⚠ run_record 缺槽位 {k} —— 不写（模板该先补齐）", file=sys.stderr)
                return 1
            doc[k] = v
        target.write_text(
            yaml.safe_dump(doc, allow_unicode=True, sort_keys=False,
                           default_flow_style=False, width=1000),
            encoding="utf-8",
        )
        print(f"\n已写入四个槽位 -> {target}")

    # 结论级红线：设置确实不一致 ⇒ 退出码 2（与"输入错"区分开）。
    if result.get("_inconsistent"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
