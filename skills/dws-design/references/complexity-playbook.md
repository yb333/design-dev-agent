# 复杂度与中间表决策 Playbook

> 命中条件：第2层加工路径设计时读本文。判断要不要拆步骤、要不要建物理中间表、step_type 怎么选。
> 自包含：复杂度评估、CTE vs 物化决策、step_type 决策树都在本文内。

---

## 一、复杂度评估指标

评估加工复杂度，看这几个指标（任一命中阈值 → 考虑拆多步骤）：

| 指标 | 阈值 | 说明 |
|------|------|------|
| JOIN 表数量 | > 12 | 关联表过多，单条 INSERT 难以一次写对 |
| 多步骤加工字段数 | ≥ 5 | 多个字段需要先聚合再关联、先拆再拼 |
| 粒度变化 | 有即声明 | 输入输出粒度不一致（聚合/展开） |
| 聚合后关联 | 有 | 先 GROUP BY 再 JOIN，逻辑复杂 |
| 复杂关联链 | ≥ 3 层 | A→B→C 串联依赖 |

> 阈值命中只是"考虑拆"的信号，最终拆不拆由 §二 物化条件决定。

---

## 二、CTE vs 物化决策（核心）

**默认策略：从 CTE 开始，必要时物化成物理中间表。**
（业界共识，Brent Ozar + Microsoft Azure SQL 官方推荐）

拆物理中间表 vs 用 CTE 内联，**不是风格偏好，是有工程标准的决策**。

### 决策维度

| 判断维度 | CTE 够用 | 必须物化物理中间表 |
|---------|---------|-------------------|
| 中间结果引用次数 | 只用一次 | **多次引用**（重算浪费）|
| 行估算准确性 | 优化器估算准 | **估算偏差 >10x**（误差放大致性能崩）|
| 数据量 | 小 | **大**（需索引加速 JOIN）|
| 可调试性 | 不需检查中间数据 | **需要检查点**（排查问题）|
| 跨步骤传递 | 单条 SQL 内 | **跨步骤**（多 rule 数据流）|

满足任一"必须物化"条件 → 建物理中间表。否则用 CTE 内联。

> 真实案例：CTE 重的过程 90 分钟 → 改成索引临时表后 15 秒（差 360 倍）。
> 多步骤 ETL 天然适合物理中间表——每步产出可检查、可复用、可索引。

### 数据量因子（★ 尽力而为）

数据量大（亿级）会显著放大 JOIN 重分布成本，倾向物化。但数据量是**尽力而为的输入**：

- RS 的 data_exploration 段可能有，也可能没有
- designer 能用 explore.py 查开发环境，但和生产不一致——**只能判档位（万/百万/亿），绝对值不可信**
- 拿得到 → 填 `complexity_analysis.data_volume` 档位，作为物化决策的加权因子
- 拿不到 → 标"未知"，走复杂度阈值默认决策（不阻断）

数据量只影响"物化 vs CTE"这一个决策点，不影响分布键选择（分布键看主键/关联频率/离散度，与数据量无关）。

---

## 三、螺旋式中间表设计

中间表设计是螺旋的——先骨架后回填：

1. **先骨架**：复杂度评估后决定建几个中间表，定表名/粒度/用途
2. **字段逻辑**：确定每个字段加工逻辑时，识别哪些字段落在中间表
3. **回填字段**：从字段分配回填出每个中间表的完整字段清单（在 field_targets 里列出）

中间表的字段绝大多数与目标表字段同名同类型（透传/聚合），极少量 designer 自建字段（辅助计算中间产物）。中间表统一加审计字段（脚本自动处理）。

### 中间表的产出模式

中间表（target_role=intermediate）有两种产出方式，靠 `build_mode` 声明：
- `transform`（默认）：单一规则一次性产出
- `accumulate`：多规则累积共建（去重累积 / union 累积）

详细场景和排重策略见 **incremental-playbook §三/§四**。本 playbook 聚焦复杂度判断，累积共建的数据流细节在那里。

---

## 四、step_type 决策树

每个规则声明 step_type + target_role，多步骤间用 produces_for / reads 声明依赖。

### ★ 关键认知：中间表 ≠ 聚合

"中间表"（target_role=intermediate）按"产出供谁消费"定义，跟聚合无关：
- 聚合产出中间表 → `aggregate`（intermediate）
- **非聚合的加工步骤产出中间表** → `full`（intermediate）← 合法！为了可读性分步加工，不一定要聚合
- 增量取数到中间表 → `incremental_extract`（intermediate）
- 单步聚合直灌目标表 → `aggregate`（target）← 合法！一步聚合搞定不必拆

### 决策顺序

```
该规则是否处理增量数据？
├─ 否（全量）
│   ├─ 产出中间表（供下游消费）？
│   │   ├─ 含聚合 → aggregate（intermediate）
│   │   └─ 纯加工分步（可读性拆分）→ full（intermediate）★ 允许
│   ├─ 直灌目标表？
│   │   ├─ 含聚合 → aggregate（target）★ 允许（单步聚合直灌）
│   │   └─ 简单直取/装配 → full（target）
│   └─ 读中间表装配目标？→ full（target，reads=[中间表]）
└─ 是（增量，详见 incremental-playbook）
    ├─ 从源表取增量到临时表？→ incremental_extract（intermediate）
    └─ 合并临时表到目标？     → merge（target，reads=[临时表]）
```

### 四种 step_type

| step_type | 用途 | target_role 可选值 | 什么时候选 |
|-----------|------|-------------------|----------|
| `full` | 单规则直灌目标（CTE 内联）；读中间表装配目标；非聚合的中间加工步骤 | target / intermediate | 简单场景、最终装配、可读性分步 |
| `aggregate` | 聚合产出（中间表或目标表） | intermediate / target | 命中复杂度阈值且需物化；单步聚合直灌 |
| `incremental_extract` | 从源表取增量到临时表 | intermediate | 增量：每张驱动表一个 |
| `merge` | 合并临时表/中间表到目标 | target | 增量合并 |

> assemble_ts 只校验**结构上不可能对**的组合：intermediate+merge（中间表不会是合并步骤）、target+incremental_extract（目标表不会是取数到 tmp）。其余组合都合法。

### target_role

- `intermediate`：中间表（每次重建用完即丢）
- `target`：目标 F 表（按 load_mode 管理）

### produces_for / reads（与 data_flow.dependencies 互补）

- `produces_for`：中间表规则填，产出供哪些规则消费（rule_code 列表）
- `reads`：装配/merge 规则填，读哪些中间表（表名列表）
- **自引用例外**：reads 含自己 target_table 时（累积共建场景），不参与循环检查

### 示例

**全量复杂宽表**：
```
R0001: aggregate  → tmp1  (intermediate, produces_for=[R0003])
R0002: aggregate  → tmp2  (intermediate, produces_for=[R0003])
R0003: full       → 目标表 (target, reads=[tmp1,tmp2])
```

**非聚合的多步加工（可读性拆分）**：
```
R0001: full → tmp1  (intermediate, produces_for=[R0002])  # A类逻辑加工，不聚合
R0002: full → 目标表 (target, reads=[tmp1])               # B类逻辑加工，读tmp1
```

**多源增量**：
```
R0001: incremental_extract → tmp_a (intermediate, produces_for=[R0003], incremental={key:update_time,...})
R0002: incremental_extract → tmp_b (intermediate, produces_for=[R0003], incremental={key:dt,...})
R0003: merge → 目标表 (target, reads=[tmp_a,tmp_b], load_mode=merge_into)
```
