# ============================================================
# 借鉴溯源台账 BORROW_LEDGER
#
# 这个文件回答一个问题：**这套平台里，哪些机制是从外部项目学来的，
# 学的是哪一句、落在哪个文件、由哪条测试钉住。**
#
# 为什么要有它
#
#   "拆开别人的项目、按模块和研究目标分析、把抽出的模块放到另一个文件夹"
#   这件事的**产出**不只是代码，还有**可展示的溯源**：每个被借来的机制
#   必须能一条链子走到底 ——
#
#       外部项目 + 具体文件行号  →  我们这边落地在哪个文件  →  哪条测试钉住
#
#   缺了这条链子，"学了什么"就只能靠嘴说；有了它，可以用 grep 自证。
#
# 三条纪律（与 SOUL.md 一致）
#
#   1. **借来 ≠ 照搬。** `kind` 必须区分 `ported`（迁移：改了用途）、
#      `adopted`（直接采用）、`inspired`（受启发、独立实现）、
#      `rejected`（看过、决定不学 —— 这一栏和前面几栏同等重要）。
#   2. **必须写清"改了什么"。** `deviation` 字段。上游不是为了我们的问题
#      写的，迁移必然有改动；不写出来的迁移等于隐藏假设。
#   3. **测试钩子必须真实存在。** 每条 `test_hook` 都要能被 grep 到；
#      `tests/test_borrow_ledger.py` 会逐条核对，防止台账腐烂成文档。
#
# 与 `docs/architecture/` 的分工
#
#   `docs/architecture/` 讲"为什么这么设计"（给未来读代码的人）
#   本文件讲"这个设计从哪来"（给要展示的人）
# ============================================================

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

#: 借用性质。四个值都要出现在台账里 —— 只列"学了什么"是半个故事。
KIND_PORTED = "ported"        # 迁移：借了机制，但改了用途/语义
KIND_ADOPTED = "adopted"      # 直接采用：机制与用途都对口
KIND_INSPIRED = "inspired"    # 受启发：看了思路，代码是自己写的
KIND_REJECTED = "rejected"    # 看过、决定不学（含"反而要避开"的）

KIND_LABELS = {
    KIND_PORTED: "迁移（借机制、改用途）",
    KIND_ADOPTED: "直接采用",
    KIND_INSPIRED: "受启发（独立实现）",
    KIND_REJECTED: "明确不学",
}

#: 状态：机制是否已落到平台代码里。
STATUS_LANDED = "landed"        # 已落地且有测试
STATUS_PARTIAL = "partial"      # 部分落地（机制在，但没做全）
STATUS_PENDING = "pending"      # 已识别、未落地

STATUS_LABELS = {
    STATUS_LANDED: "✅ 已落地",
    STATUS_PARTIAL: "⚠️ 部分落地",
    STATUS_PENDING: "❌ 未落地",
}

#: 「明确不学」的条目不参与落地状态。
#: 把它们渲染成「❌ 未落地」是**错读**：那不是没做完，而是主动决定不做。
#: 汇报时这两栏必须能分开，否则"没学"会被读成"欠账"。
KIND_REJECTED_STATUS_LABEL = "— 不适用（主动不学）"


def status_label(entry: "BorrowEntry") -> str:
    """取一条记录的**展示用**状态标签。

    对 ``kind == "rejected"`` 的条目返回固定的"不适用"，
    而不是把它套进 ``STATUS_LABELS``（那会读成"还有活没干"）。
    """
    if entry.kind == KIND_REJECTED:
        return KIND_REJECTED_STATUS_LABEL
    return STATUS_LABELS[entry.status]


@dataclass(frozen=True)
class BorrowEntry:
    """一条借用记录。"""

    #: 短 id，用在下游引用里
    key: str
    #: 学到了什么（一句话，用平台的术语，不用上游的术语）
    lesson: str
    #: 上游项目名（与 repos_download/00_源码仓库 目录名对应）
    upstream: str
    #: 上游具体位置。**必须到文件（能到行号就到行号）** ——
    #: 只写仓库名等于没写。
    upstream_ref: str
    #: 借用性质
    kind: str
    #: 落地状态
    status: str
    #: 我们这边的落地文件（相对项目根）。未落地时为空。
    landed_in: Tuple[str, ...] = ()
    #: 钉住它的测试函数名（能 grep 到的名字）。未落地时为空。
    test_hook: Tuple[str, ...] = ()
    #: **迁移必填**：相对上游改了什么、为什么改。
    deviation: str = ""
    #: 已知局限：这个机制**不覆盖**什么（防止过度声称）。
    limits: str = ""
    #: 关联的文档
    docs: Tuple[str, ...] = ()
    #: 备注
    note: str = ""

    def is_wired(self) -> bool:
        """是否已落地（有代码落点）。"""
        return bool(self.landed_in)

    def is_pinned(self) -> bool:
        """是否有测试钉住。**没有测试的落地不算落地** —— 会腐烂。"""
        return bool(self.test_hook)


# ------------------------------------------------------------------
# 台账本体
#
# 顺序：先列**已落地**（这是要展示的部分），再列 `rejected`
# （这一栏证明分析不是"看到什么学什么"）。
# ------------------------------------------------------------------
LEDGER: Tuple[BorrowEntry, ...] = (

    # ============================================================
    # 一、已落地：三个被找出来的缺口
    # ============================================================

    BorrowEntry(
        key="settings_fingerprint",
        lesson="三层模型比对前，必须能机器判定『除参数外数值设置逐位相同』",
        upstream="PhySimAgent",
        upstream_ref=(
            "SRC/pipeline/exp_layer/battery/__init__.py:193 verify() "
            "（⚠️ 借鉴清单原写 contract.py:193 —— 路径错，已订正）"
        ),
        kind=KIND_PORTED,
        status=STATUS_LANDED,
        landed_in=("governance/settings_hash.py",),
        test_hook=(
            "test_string_vs_float_are_different",
            "test_float_literal_spelling_does_not_change_the_hash",
            "test_broken_layer_is_rejected_with_per_field_detail",
            "test_the_21_real_historical_artifacts_cannot_be_fingerprinted",
        ),
        deviation=(
            "上游做的是**自证确定性**（同参数重跑两次 + difflib 逐行 diff），"
            "是『这一次算得对不对』；我们要的是**跨层可比性**"
            "（M0/M1/M2 三次独立 solve 的非参数部分是否相同）。"
            "用途变了 ⇒ 这是迁移不是照搬。"
            "另加了上游没有的三样：① 类型标签（1e-6 ≠ \"1e-6\"），"
            "② 缺字段硬门（不许静默补默认值），③ 逐字段差异明细（只报不一致无法修）。"
        ),
        limits=(
            "不含 PyBaMM 默认空间网格、不含 PyBaMM 版本、不描述算哪颗电芯"
            "（写进 KNOWN_LIMITS，须与结论一起引用）"
        ),
        docs=("docs/three_gaps_implementation_2026-09-28.md",),
        note=(
            "2026-09-29 修复：缺字段从静默套默认值改为默认抛 MissingSettingsError。"
            "实测 21 份历史产物无一带 solver 块，原实现会让 13 份异构 run 共用同一指纹。"
        ),
    ),

    BorrowEntry(
        key="failure_isomorphism",
        lesson="失败返回必须与成功**结构同构**，不许用哨兵值（如 capacity=0）",
        upstream="PhySimAgent",
        upstream_ref="SRC/pipeline/exp_layer/battery/contract.py:95 failed_result()",
        kind=KIND_ADOPTED,
        status=STATUS_LANDED,
        landed_in=(
            "governance/geometry_channel.py",
            "governance/noise_floor.py",
        ),
        test_hook=(
            "test_missing_any_measurement_blocks_the_whole_channel",
            "test_missing_blocks_even_with_require_complete_false_by_default",
            "test_too_few_points_raises",
            "test_length_mismatch_raises",
        ),
        deviation=(
            "直接采用。落点不是新类，而是两个模块的返回约定："
            "几何通路缺项时返回 ``incomplete=True + reason``（不返回一个假的 0），"
            "噪声底点数不足时**抛错**（不返回一个看着小的 sigma）。"
        ),
        limits="只覆盖新写的两个模块；冻结内核基线里仍有 0 哨兵的遗留。",
        docs=("docs/architecture/agent_audit.md",),
        note="这一条同时是我们拒绝 `Battery-Sim-Agent` 上游的理由（其 capacity=0 是哨兵）。",
    ),

    BorrowEntry(
        key="noise_floor_before_threshold",
        lesson="判据里的『精确/平坦』必须有量纲：先标定噪声底，再设阈值",
        upstream="BatteryKG",
        upstream_ref="src/models/quantile_gate.py:87 threshold_at_q()（分位数门只用训练 bank 推导）",
        kind=KIND_INSPIRED,
        status=STATUS_LANDED,
        landed_in=("governance/noise_floor.py",),
        test_hook=(
            "test_recovers_known_sigma",
            "test_without_detrend_drift_inflates_sigma",
            "test_mad_resists_a_single_spike",
            "test_resolution_floor_is_reported_when_sigma_is_tiny",
            "test_k_has_no_silent_default_in_the_threshold",
            "test_shipped_template_has_no_decided_k",
        ),
        deviation=(
            "上游是『阈值只用训练集推、不许碰测试集』；"
            "我们的问题不同：N1 判据 max|ΔV| ≤ k·σ_noise 里的 σ 从哪来。"
            "借的是**纪律**（阈值不能拍脑袋、要有独立来源），实现是独立写的。"
            "自立的三条：去线性趋势、MAD×1.4826 稳健估计、分辨率下限 q/√12。"
            "2026-09-29 又加了第四条：**k 本身也必须有独立来源** —— "
            "k 是预注册量，不许有默认值；缺它时报「未预注册」而不是按示例值渲染。"
        ),
        limits="只标定**电芯内时间噪声**；覆盖不到炉内电芯间 / 炉间离散度（分层未做）。",
        docs=("docs/three_gaps_implementation_2026-09-28.md",),
        note=(
            "清单第五条原本要求『分两层报告』，目前只做了单层 —— 已记为 partial 的另一半。"
            "2026-09-29 补：`k` 从『脚本默认 3.0』改为预注册量"
            "（`configs/noise_floor_prereg.yaml`，出厂 `k: null`），"
            "并修掉一处报告与 JSON 自相矛盾（报告按 3×σ 渲染、JSON 写 `k: null`）。"
        ),
    ),

    BorrowEntry(
        key="verdict_closed_set",
        lesson="报告里的判定词必须是**闭集**，多一个都算越界；只有『可辨识』能报数值",
        upstream="BatteryKG",
        upstream_ref="src/models/quantile_gate.py gate_decisions() + abstention.py 显式弃权",
        kind=KIND_PORTED,
        status=STATUS_LANDED,
        landed_in=("governance/analysis_mode.py",),
        test_hook=(
            "test_verdict_vocabulary_is_exactly_five_words",
            "test_render_verdict_glosses_every_allowed_word",
            "test_both_sides_truncated_is_unconstrained",
            "test_absent_band_is_not_measured",
        ),
        deviation=(
            "上游是**二值**（过门 / 弃权）；我们扩成**五词**"
            "（可辨识 / 有界 / 无约束 / 不可辨识 / 未测量）——"
            "因为电池参数辨识里『有影响但定不住』与『数据里没这个激励』是两类，"
            "上游的二元结构装不下。"
        ),
        limits=(
            "判定发生在**报告阶段**，不在数据结构阶段："
            "不可辨识的参数**仍会被算出来、仍进中间产物**，只在写报告时被拦。"
            "清单原意是要它**在数据层就不可引用**（拿不到 .value）—— 这一半未做。"
        ),
        note="已记：需查有没有哪条路径绕过 render_verdict 直接打印数值。",
    ),

    # ============================================================
    # 二、已识别但**未落地** —— 必须与已落地的一起展示，
    #     否则"学了什么"会变成只报喜的清单。
    # ============================================================

    BorrowEntry(
        key="layer_contract",
        lesson="三层『只允许增加信息』要用集合运算守，不能靠人自觉",
        upstream="PhySimAgent",
        upstream_ref="SRC/pipeline/agentloop/environment.py:55 TaskSpec（@dataclass(frozen=True)）",
        kind=KIND_ADOPTED,
        status=STATUS_PENDING,
        landed_in=(),
        test_hook=(),
        deviation="",
        limits="",
        note=(
            "**和 `settings_fingerprint` 是一对**：指纹管『数值设置别动』，"
            "层契约管『参数集只在长』。目前只做了前半句。"
            "风险：M2 参数量若比 M1 少（某实测值没读到、静默退回默认），"
            "平台不报错，反而会算出一个『看起来更准』的 M2。"
        ),
    ),

    BorrowEntry(
        key="random_control",
        lesson="门的收益要减去**随机筛选**的基线，否则『筛得好』与『筛得多』分不开",
        upstream="BatteryKG",
        upstream_ref=(
            "src/models/abstention.py —— 对同一保留比例抽 20 次随机子集（seeded），"
            "算 rmse_random 作为对照"
        ),
        kind=KIND_ADOPTED,
        status=STATUS_PENDING,
        landed_in=(),
        test_hook=(),
        note=(
            "上游注释：*If coverage-gating tracks the random curve, coverage carries "
            "no information.*  ⇒ 这是我们主张的**防线**而非审计："
            "『方向不对称随退化放大』会被质疑成『你筛掉了噪声大的点』，"
            "随机负对照是唯一能把它挡回去的实验。零实验成本（用现有 GITT 数据）。"
            "⚠️ 写进方案时用『防线』语言，不用『审计』语言。"
        ),
    ),

    BorrowEntry(
        key="independent_batch_gate",
        lesson="『独立处理重复』要从 warning 升级为 error，不能靠人在报告里写一句话",
        upstream="PhySimAgent",
        upstream_ref=(
            "CONFIGs/batch2/e3_battery/freeze/e3-battery.json:121 gate_rule"
            "（其余同名 freeze 见 e1-stw.json:208 / e2-ifw.json:173；"
            "不满足就不许进入下一阶段）"
        ),
        kind=KIND_PORTED,
        status=STATUS_PENDING,
        landed_in=(),
        test_hook=(),
        deviation=(
            "上游是独立的 freeze JSON；我们这里已有 `batch` 字段"
            "（battery_sim/datasets/material_metadata.py:287）"
            "与逐样品校验（validate_series, :656），"
            "所以落点是**加一个参数**把 warning 升级为 error，不是新建机制。"
        ),
        note=(
            "⚠️ 借鉴清单原写函数名 `check_gradient` —— **该函数不存在**，"
            "真名 `validate_series`（已订正清单）。"
        ),
    ),

    BorrowEntry(
        key="input_hash_on_ingest",
        lesson="数据接入要留输入文件哈希，否则『这份数据没换过』无法自证",
        upstream="BatteryCopilot",
        upstream_ref="backend/src/battery_copilot/manufacturing_ingest.py:78 归档 MD5 校验",
        kind=KIND_ADOPTED,
        status=STATUS_PENDING,
        landed_in=(),
        test_hook=(),
        note="已核实平台 `user_tools/import_dataset.py` 与 `importer.py` 均无 hashlib/sha256。",
    ),

    # ============================================================
    # 三、明确**不学**的 —— 这一栏和前面同等重要。
    #     它证明分析是按"对我的问题有没有用"筛的，不是看到什么抄什么。
    # ============================================================

    BorrowEntry(
        key="no_llm_in_the_loop",
        lesson="不要把 LLM 引进这个项目",
        upstream="（针对 #1/#3/#4/#5/#6 全部 LLM 项目）",
        upstream_ref="六个仓库的 Agent 编排层",
        kind=KIND_REJECTED,
        status=STATUS_PENDING,
        note=(
            "流程是『实验数据 → 参数辨识 → 三层预测比对 → 留出集验证』，"
            "**全程不需要自然语言决策**。引入 LLM 只会带来：不可复现、"
            "违反导师『不要发数据』红线、多余失败模式。"
            "**连 BatteryAgent 的确定性 Verifier 都不需要 —— "
            "本项目没有『Agent 输出』，只有求解器输出。**"
        ),
    ),

    BorrowEntry(
        key="no_rag_or_kg",
        lesson="不引入 RAG / 知识图谱",
        upstream="BatteryKG / BatteryCopilot / BatteryLLM / SciAssist",
        upstream_ref="src/ 全部检索层",
        kind=KIND_REJECTED,
        status=STATUS_PENDING,
        note=(
            "瓶颈是**参数辨识的可信度**，不是文献检索。"
            "BatteryKG 的覆盖门是给『10 万分子』规模设计的，我们只有十几颗电芯。"
        ),
    ),

    BorrowEntry(
        key="no_structural_only_repos",
        lesson="不学『结构真、数据假』的仓库",
        upstream="battery-parameter-agent / Batterytwin-mcp / battery-research-agent-demo",
        upstream_ref=(
            "battery-parameter-agent：RF 训练在手写解析函数上 + RAG 语料是 4 条硬编码字符串；"
            "batterytwin-mcp：全仓 22 KB；battery-research-agent-demo：0 个 .py 文件"
        ),
        kind=KIND_REJECTED,
        status=STATUS_PENDING,
        note=(
            "把 v7 对『合成夹具 3.27 mV』的态度扩展到别人的代码上："
            "结构完整不等于结果可信。"
        ),
    ),

    BorrowEntry(
        key="no_expansion_to_fit_platform",
        lesson="不为了『用上平台』而扩大实验",
        upstream="（多智能体研究 workflow 类）",
        upstream_ref="—",
        kind=KIND_REJECTED,
        status=STATUS_PENDING,
        note="呼应导师诊断：『商业石墨从校准参照变成了主研究对象』。",
    ),
)


# ------------------------------------------------------------------
# 查询
# ------------------------------------------------------------------
def entries_by_status(status: str) -> List[BorrowEntry]:
    """按落地状态筛。"""
    if status not in STATUS_LABELS:
        raise ValueError(f"未知状态 {status!r}，允许：{sorted(STATUS_LABELS)}")
    return [e for e in LEDGER if e.status == status]


def entries_by_kind(kind: str) -> List[BorrowEntry]:
    if kind not in KIND_LABELS:
        raise ValueError(f"未知性质 {kind!r}，允许：{sorted(KIND_LABELS)}")
    return [e for e in LEDGER if e.kind == kind]


def entries_by_upstream(upstream: str) -> List[BorrowEntry]:
    return [e for e in LEDGER if e.upstream == upstream]


def summary() -> Dict[str, object]:
    """一页数字，给汇报用。

    ⚠️ ``pending`` **不含「明确不学」** —— 那 4 条是主动决定，
    混进来会把"没学"读成"欠账"。两栏分开报。
    """
    landed = entries_by_status(STATUS_LANDED)
    partial = entries_by_status(STATUS_PARTIAL)
    # rejected 条目的 status 字段恒为 pending，但它们不是待办。
    pending = [
        e for e in entries_by_status(STATUS_PENDING)
        if e.kind != KIND_REJECTED
    ]
    rejected = entries_by_kind(KIND_REJECTED)
    return {
        "total": len(LEDGER),
        "landed": len(landed),
        "partial": len(partial),
        "pending": len(pending),
        "rejected": len(rejected),
        "ported": len(entries_by_kind(KIND_PORTED)),
        "adopted": len(entries_by_kind(KIND_ADOPTED)),
        "inspired": len(entries_by_kind(KIND_INSPIRED)),
        "unpinned_landed": [
            e.key for e in landed if not e.is_pinned()
        ],
    }


def render_ledger(*, only_landed: bool = False) -> str:
    """渲染成一张可贴进汇报的 markdown 表。"""
    rows = [e for e in LEDGER if e.is_wired()] if only_landed else list(LEDGER)
    lines = [
        "| 学到什么 | 上游 | 性质 | 状态 | 落在哪 | 测试 |",
        "|---|---|---|---|---|---|",
    ]
    for e in rows:
        landed = "<br>".join(f"`{p}`" for p in e.landed_in) or "—"
        tests = "<br>".join(f"`{t}`" for t in e.test_hook) or "—"
        lines.append(
            f"| {e.lesson} | {e.upstream} | {KIND_LABELS[e.kind]} "
            f"| {status_label(e)} | {landed} | {tests} |"
        )
    return "\n".join(lines)


def render_entry(e: BorrowEntry) -> str:
    """单条的完整说明（含改动与局限）—— 展示用。"""
    out = [f"### {e.lesson}", ""]
    out.append(f"- **上游**：{e.upstream} — `{e.upstream_ref}`")
    out.append(f"- **性质**：{KIND_LABELS[e.kind]}｜**状态**：{status_label(e)}")
    if e.landed_in:
        out.append(f"- **落在哪**：{'、'.join('`' + p + '`' for p in e.landed_in)}")
    if e.test_hook:
        out.append(f"- **测试**：{'、'.join('`' + t + '`' for t in e.test_hook)}")
    if e.deviation:
        out.append(f"- **相对上游改了什么**：{e.deviation}")
    if e.limits:
        out.append(f"- **不覆盖**：{e.limits}")
    if e.note:
        out.append(f"- **备注**：{e.note}")
    return "\n".join(out)


def main(argv: Optional[List[str]] = None) -> int:
    """``python -m governance.borrow_ledger [--landed] [--summary] [--key <k>]``"""
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog="governance.borrow_ledger",
        description="展示『从外部项目学了什么』的溯源台账",
    )
    parser.add_argument("--landed", action="store_true", help="只列已落地的")
    parser.add_argument("--summary", action="store_true", help="只打印统计")
    parser.add_argument("--key", help="打印单条完整说明")
    args = parser.parse_args(argv)

    if args.summary:
        import json

        print(json.dumps(summary(), ensure_ascii=False, indent=2))
        return 0

    if args.key:
        hits = [e for e in LEDGER if e.key == args.key]
        if not hits:
            print(f"没有这条：{args.key}", file=sys.stderr)
            print(f"可用的 key：{sorted(e.key for e in LEDGER)}", file=sys.stderr)
            return 2
        print(render_entry(hits[0]))
        return 0

    if args.landed:
        for e in entries_by_status(STATUS_LANDED):
            print(render_entry(e))
            print()
        return 0

    print(render_ledger())
    return 0


__all__ = [
    "KIND_ADOPTED",
    "KIND_INSPIRED",
    "KIND_LABELS",
    "KIND_PORTED",
    "KIND_REJECTED",
    "KIND_REJECTED_STATUS_LABEL",
    "LEDGER",
    "STATUS_LABELS",
    "STATUS_LANDED",
    "STATUS_PARTIAL",
    "STATUS_PENDING",
    "BorrowEntry",
    "entries_by_kind",
    "entries_by_status",
    "entries_by_upstream",
    "render_entry",
    "render_ledger",
    "status_label",
    "summary",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
