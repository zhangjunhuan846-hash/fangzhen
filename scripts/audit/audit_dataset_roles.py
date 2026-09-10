#!/usr/bin/env python3
# ============================================================
# 只读审计：每个数据集/倍率的 dataset_role 声明情况
#
# 平台的 zero-fit 红线要求"用于标定的数据必须被声明为识别集"。
# 这个脚本不改任何东西，只把**还没声明**的条目列出来，让缺口可见。
#
#   python scripts/audit/audit_dataset_roles.py [--config configs/datasets.yaml]
# ============================================================

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from governance.dataset_roles import audit_config  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None,
                    help="数据集配置（默认 configs/datasets.yaml）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args(argv)

    report = audit_config(args.config)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    print(f"已声明：{len(report['declared'])} 条")
    for it in report["declared"]:
        note = f"   # {it['note']}" if it.get("note") else ""
        print(f"  {it['dataset']:<22} {it['rate']:<12} -> {it['role']}{note}")
    print()
    print(f"未声明：{len(report['unspecified'])} 条")
    for it in report["unspecified"]:
        print(f"  {it['dataset']:<22} {it['rate']:<12} -> （缺 dataset_role）")
    if report["unspecified"]:
        print()
        print("未声明的条目按 'identification' 处理，但每次调用都会返回警告，")
        print("并写进 provenance。补齐声明只是加一行 config，不改代码。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
