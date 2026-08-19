# opt-playbook —— 优化模式设计决策知识（dws-design-opt 专属）

> 两个决策树：落位取舍（§一）+ 回刷判断（§二）。通用设计知识不在本文（在 dws-design/references）。

## 一、落位取舍树（新字段从源头到目标表走哪条路）

```
新字段的源表在 baseline 源表清单里吗？（change_request.new_source_table）
├─ 否（新来源）→ 需要新 JOIN。JOIN 挂哪条规则？
│    ├─ 血缘最短路径：目标规则直接 JOIN 新表（大多数场景）
│    └─ 仅当新字段的加工必须在中间环节完成（如需在聚合前关联）→ JOIN 挂上游规则，
│       新字段穿中间表（intermediate_tables 列出，上游+下游规则都落位）
└─ 是（同源直挂）→ 无新 JOIN，挂产出该字段的规则即可
     └─ 源表字段在哪条规则可见？产出它的那条规则（通常目标规则；穿中间表场景同上）
```

原则：
1. **血缘最短优先**——能直挂不穿中间表（多穿一跳 = 多一条规则改写 + 中间表加列）。
2. **中间表被共用时谨慎**（baseline_view 的依赖图可见被谁消费）——加列影响所有消费方，
   必须在 decisions 中如实落位并在回报里提示调用方。
3. **placed_rules 是围栏边界**——规则列进去了，它的 field_targets/JOIN 变更才被许可；
   漏列 = 下游漏改（围栏反向拦截）。多列 = 越界（正向拦截）。

## 二、回刷决策表

| 基线写入类型（baseline_view 规则清单的 kind） | 新列历史数据 | decisions.backfill |
|---|---|---|
| full_truncate / partition_truncate（全量类） | 下次调度自动补齐 | `none` |
| merge_upsert / append / update / delete_by_condition（增量类） | 历史行新列 NULL | `pending`（闸口①'人选拿：不回刷=接受 NULL / 回刷=给时间范围） |

- RS 优化章节写了回刷意向 → 预填（none / yes），否则 pending。
- 回刷实现不归本决策：人选拿后由调用方触发 init 管道（档案路径可复用档案 init 段）。
- `load_mode_pending`（写入类型待定）的规则 → 回刷判断挂起，回报调用方人工认定。

## 三、新 JOIN 的 join_safety 写法

- `join_key_unique`：新表按 JOIN 键是否唯一（维表=true；事实表/流水表=false 时必须收敛）
- 不唯一时的 `strategy`：聚合收敛（先 SUM/GROUP 再 JOIN）/ 取最新（ROW_NUMBER 限定窗口）
  ——注意：这属于**新字段的加工逻辑**，写进 design_logic，不许动老列。
- `reason`：一句话依据（"维表主键关联" / "explore 试算 count=distinct"）。
- 老关联**不声明**（生产在跑即证明，baseline 语义空位不需要补）。
