# 回收石墨半电池：空模板（数据到手直接填）

这一目录**不参与运行**，是给"数据到手那一刻"用的脚手架。放进 `live` 配置之前，
`configs/datasets.yaml` 里不会多出任何数据集，管线行为一行不变。

方案本身不在这里重复写：

- `docs/graphite_halfcell_phase1_test_plan.md` —— Phase 0（G0 商业石墨 3 颗平行样）→
  Phase 1（低载量识别 / 高载量验证）→ 回收石墨
- `docs/graphite_heat_treatment_test_plan.md` —— A 组处理温度，含"粒径差异会被读成
  材料改善"的红线（**D ∝ R²**）

## 文件清单

| 文件 | 用途 |
|---|---|
| `metadata.example.yaml` | 材料元数据模板：样品 / 电极几何 / 粒径 / 测了什么 / 参数来源 |
| `recycled_graphite.py` | adapter 骨架：5 个 hook 待填，构造时强制校验元数据 |
| `datasets_yaml_snippet.yaml` | 贴进 `configs/datasets.yaml` 的声明块 |

## 启用（4 步）

```bash
# 1) 放 adapter（改类名不必，registry 按 recycled_graphite -> RecycledGraphiteAdapter 解析）
cp templates/recycled_graphite/recycled_graphite.py battery_sim/datasets/

# 2) 填元数据：缺哪个字段报哪个字段，errors = 0 才能开始分析
cp templates/recycled_graphite/metadata.example.yaml data/raw/LIB/RG_500-a.yaml
python -m battery_sim.datasets.template --metadata data/raw/LIB/RG_500-a.yaml

# 3) 把 datasets_yaml_snippet.yaml 的内容贴进 configs/datasets.yaml（注意改 sample/cells）

# 4) 填 5 个 hook，然后跑契约自检
python -m battery_sim.datasets.template --check recycled_graphite
```

## 建议的样品编号

| sample_id | 含义 | 备注 |
|---|---|---|
| `G0-a/b/c` | 商业石墨参照，3 颗平行样 | 与回收料**同配方、同目标载量**；不强求同压实（回收料更难压） |
| `RG_raw` | 回收料，未处理 | |
| `RG_500` | 回收料，500 °C 处理 | |
| `RG_800` | 回收料，800 °C 处理 | |

## 三个必须先定下来、否则后面白跑的东西

1. **Fresh 侧必须是自己的数据。** 不能拿 SINTEF / DLR 的公开记录当 fresh 基准 ——
   不同批料、不同仪器、不同配方，任何差异都不可归因。
2. **粒径要处理前后都测**（D ∝ R²，粒径差 2 倍 = D_s 差 4 倍）。
3. **`dataset_role` 先声明**。回收石墨的用途大概率是 `identification`；
   公开记录才是 `benchmark`（只评估、不构成验证）。
