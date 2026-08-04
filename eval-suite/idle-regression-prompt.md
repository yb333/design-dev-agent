# 闲时回归评测提示词

> 用于空闲时段批量跑案例回归。复制下面的提示词给 agent，让它在项目目录下执行。

---

## 提示词（复制以下全部内容）

你在 design-dev-agent 项目（/Users/yuanbo/design-dev-agent）里，任务是跑本地案例回归评测。

### 第零步：安装最新代码

```bash
cd /Users/yuanbo/design-dev-agent
git pull
python3 install.py
```

如果 install.py 卡住，手动复制：
```bash
cp agents/dws-*.md ~/.config/opencode/agents/
cp -r skills/dws-design skills/dws-coding ~/.config/opencode/skills/
cp commands/*.md ~/.config/opencode/commands/
```

### 第一步：案例数据自检（快速，不调AI）

```bash
cd /Users/yuanbo/design-dev-agent
python3 eval-suite/check_case.py --cases-dir eval-suite/cases/
```

全部通过才继续。如果有问题，按报错修案例数据（mapping 表头/目标表名等）。

### 第二步：全量脚本链路验证（快速，不调AI）

```bash
cd /Users/yuanbo/design-dev-agent
for case_dir in eval-suite/cases/0*/; do
  asset=$(basename "$case_dir" | sed 's/^[0-9]*_//')
  echo "========== $asset =========="
  python3 eval-suite/local_eval.py \
    --asset "$asset" \
    --mapping "$case_dir/mapping.xlsx" \
    --rs "$case_dir/RS.md" \
    --skip-ai --clean 2>&1
done
```

记录哪些案例的脚本链路有问题，修完再往下。

### 第三步：逐个跑完整AI流程（从小到大）

```bash
cd /Users/yuanbo/design-dev-agent

# 小案例（7-30字段，约2-5分钟/个）
python3 eval-suite/local_eval.py --asset dwb_trade_order_d       --mapping eval-suite/cases/002_dwb_trade_order_d/mapping.xlsx       --rs eval-suite/cases/002_dwb_trade_order_d/RS.md       --clean
python3 eval-suite/local_eval.py --asset dwb_trade_wide_f        --mapping eval-suite/cases/003_dwb_trade_wide_f/mapping.xlsx        --rs eval-suite/cases/003_dwb_trade_wide_f/RS.md        --clean
python3 eval-suite/local_eval.py --asset dwb_shop_center_f       --mapping eval-suite/cases/004_dwb_shop_center_f/mapping.xlsx       --rs eval-suite/cases/004_dwb_shop_center_f/RS.md       --clean
python3 eval-suite/local_eval.py --asset dwb_supply_chain_f      --mapping eval-suite/cases/007_dwb_supply_chain_f/mapping.xlsx      --rs eval-suite/cases/007_dwb_supply_chain_f/RS.md      --clean
python3 eval-suite/local_eval.py --asset dwb_after_sale_center_f --mapping eval-suite/cases/008_dwb_after_sale_center_f/mapping.xlsx --rs eval-suite/cases/008_dwb_after_sale_center_f/RS.md --clean
python3 eval-suite/local_eval.py --asset dwb_marketing_center_f  --mapping eval-suite/cases/011_dwb_marketing_center_f/mapping.xlsx --rs eval-suite/cases/011_dwb_marketing_center_f/RS.md  --clean

# 中等案例（35-50字段，约5-10分钟/个）
python3 eval-suite/local_eval.py --asset dwb_product_center_f    --mapping eval-suite/cases/009_dwb_product_center_f/mapping.xlsx    --rs eval-suite/cases/009_dwb_product_center_f/RS.md    --clean
python3 eval-suite/local_eval.py --asset dwb_user_center_f       --mapping eval-suite/cases/005_dwb_user_center_f/mapping.xlsx       --rs eval-suite/cases/005_dwb_user_center_f/RS.md       --clean

# 大案例（100+字段，可能15-30分钟/个）
python3 eval-suite/local_eval.py --asset dwb_order_center_f      --mapping eval-suite/cases/012_dwb_order_center_f/mapping.xlsx      --rs eval-suite/cases/012_dwb_order_center_f/RS.md      --clean
python3 eval-suite/local_eval.py --asset dwb_user_profile_f      --mapping eval-suite/cases/010_dwb_user_profile_f/mapping.xlsx      --rs eval-suite/cases/010_dwb_user_profile_f/RS.md      --clean
python3 eval-suite/local_eval.py --asset dwb_user_behavior_f     --mapping eval-suite/cases/006_dwb_user_behavior_f/mapping.xlsx     --rs eval-suite/cases/006_dwb_user_behavior_f/RS.md     --clean
```

### 第三步补充：多规则案例全编码（时间充裕时跑）

```bash
cd /Users/yuanbo/design-dev-agent
python3 eval-suite/local_eval.py --asset dwb_user_center_f --mapping eval-suite/cases/005_dwb_user_center_f/mapping.xlsx --rs eval-suite/cases/005_dwb_user_center_f/RS.md --clean --all-rules
```

### 第四步：逐案例检查产出质量

每个案例跑完后检查以下内容：

**1. ts.json 结构（重点：tables 段 + rules 无 fields）**
```bash
DELIVER=10_project_deliver/{资产名}/ddlc_design_dev
python3 -c "
import json
ts = json.load(open('$DELIVER/ts.json'))
# 顶层键含 tables（本轮新增）
for k in ['version','meta','design','tables','rules','data_flow','dq_rules']:
    assert k in ts, f'缺顶层键: {k}'
# tables 段有字段定义 + 物理属性
tables = ts.get('tables', {})
assert tables, 'tables 段为空'
for tname, t in tables.items():
    assert 'fields' in t, f'{tname} 缺 fields'
    assert 'distribute_type' in t, f'{tname} 缺 distribute_type'
    assert t.get('distribution_key') is not None, f'{tname} 缺 distribution_key'
# rules 无 fields（搬到 tables 了），有 field_targets
for code, rule in ts['rules'].items():
    assert 'fields' not in rule, f'{code} 还有 fields（应已搬到 tables）'
    assert 'field_targets' in rule, f'{code} 缺 field_targets'
# design 无 distribution_key（搬到 tables 了）
assert 'distribution_key' not in ts.get('design', {}), 'design 还有 distribution_key'
# schedule 有 lts_params
sched = ts.get('meta', {}).get('schedule', {})
assert 'lts_params' in sched, 'schedule 缺 lts_params'
print('✅ ts.json 结构通过')
"
```

**2. ts.md 渲染质量（重点：§1 来源表去重 + §2 分布类型 + §4 无关联策略 + §5 只有图 + §6 LTS参数）**
```bash
python3 -c "
ts_md = open('$DELIVER/ts.md').read()
# §1 来源表无重复（按表去重）
assert '来源表' in ts_md
# §2 分布列显示 HASH/ROUNDROBIN/REPLICATION
assert 'HASH' in ts_md or 'ROUNDROBIN' in ts_md, '§2 缺分布类型'
# §4 无关联策略（已删除）
assert '关联策略' not in ts_md, '§4 不应有关联策略'
# §5 只有图，无血缘关系表/执行顺序表
assert '血缘关系' not in ts_md, '§5 不应有血缘关系表'
assert '执行顺序' not in ts_md, '§5 不应有执行顺序表'
# §6 有 LTS 参数
assert 'LTS 参数' in ts_md or 'lts_params' in ts_md.lower(), '§6 缺 LTS 参数'
print('✅ ts.md 渲染通过')
"
```

**3. DDL 完整性（重点：业务字段不丢 + 分布类型正确 + 无行内注释）**
```bash
DDL_DIR=$DELIVER/ddl
RB_DIR=$DELIVER/ddl_rollback
# DDL 文件存在
ls $DDL_DIR/create_table_*.sql > /dev/null 2>&1 && echo "✅ 有DDL" || echo "⚠️ 无DDL"
# 回退脚本数量 = DDL 数量
DDL_COUNT=$(ls $DDL_DIR/*.sql 2>/dev/null | wc -l)
RB_COUNT=$(ls $RB_DIR/*.sql 2>/dev/null | wc -l)
echo "DDL: $DDL_COUNT, 回退: $RB_COUNT"
# I视图不用 SELECT *
grep -l "SELECT \*" $DDL_DIR/create_view_*.sql 2>/dev/null && echo "⚠️ I视图用了SELECT*" || echo "✅ I视图OK"
```

**4. 制品包生成（重点：文件命名 shujia_/lts_ + 规则编码留空）**
```bash
EXPORT_DIR=$DELIVER/export
if [ -d "$EXPORT_DIR" ]; then
  ls $EXPORT_DIR/shujia_*.xlsx > /dev/null 2>&1 && echo "✅ 术加制品包" || echo "⚠️ 无术加制品包"
  ls $EXPORT_DIR/lts_*.xlsx > /dev/null 2>&1 && echo "✅ LTS制品包" || echo "⚠️ 无LTS制品包"
  # manifest 的 codes_filled 应为 false
  python3 -c "
import json, glob
for f in glob.glob('$EXPORT_DIR/export_manifest_*.json'):
    m = json.load(open(f))
    assert m.get('codes_filled') == False, 'codes_filled 应为 false'
    print(f'✅ {f}: codes_filled=false')
"
else
  echo "⚠️ 无 export 目录（制品包未生成）"
fi
```

**5. 数据探索提取**（如果RS有L01数据探索）
```bash
python3 -c "
import json
d = json.load(open('$DELIVER/_internal/rs_input.json'))
de = d.get('data_exploration', {})
if de:
    print(f'✅ 数据探索已提取: {list(de.keys())}')
else:
    print('⚠️ 无数据探索（RS可能没有L01章节）')
"
```

### 第五步：发现问题自行修复

- **脚本bug**（格式/结构/校验逻辑）：直接修代码，改完同步全局（`cp skills/xxx/references/xxx.py ~/.config/opencode/skills/xxx/references/`），重跑验证
- **AI产出质量**（design_logic口径错/SELECT逻辑错）：记录下来，分析是skill指引不够还是模型能力问题
- **业务问题**（不确定对不对的）：记录下来，不确定的不要改
- **案例数据问题**（mapping/RS数据有错）：修案例数据

### 第六步：提交

```bash
cd /Users/yuanbo/design-dev-agent
git add -A
git commit -m "test: 闲时回归评测结果 + 问题修复"
git push origin main
```

### 重点检查项（本轮新增）

本轮有重大结构重构和大量修复，重点验证：

**结构重构类：**
1. **tables 段**：ts.json 顶层有 tables 段（每表有 fields + distribution_key + distribute_type + partition）；rules 里**无** fields（只有 field_targets + field_logics）；design 里**无** distribution_key
2. **分布类型**：tables 每表有 distribute_type（HASH/ROUNDROBIN/REPLICATION），§2 表模型显示如 `HASH(product_id)`，DDL 生成 `DISTRIBUTE BY HASH(...)` 正确
3. **来源表去重**：§1 来源表按表去重（同表多别名合并），不应有重复行
4. **DDL 字段完整**：DDL 的 CREATE TABLE 里**业务字段和审计字段都在**（之前 bug 导致只有审计字段）。验证：DDL 里能找到业务字段名
5. **DDL 无行内注释**：字段行不再有 `/* 注释 */`，注释统一用 COMMENT ON COLUMN

**流程改进类：**
6. **DQ 改 coder 生成**：不再调 assemble_dq.py 脚本，DQ 由 coder 在编码步骤并行生成。检查 dq/ 目录下有 SQL 文件
7. **UT 拆分预检+执行**：步骤 6a（ut_precheck.py，秒级）先跑回退+DDL+SELECT预检；步骤 6b（ut_execute.py，分钟级）跑 INSERT+UT检查。预检失败的规则不跑 INSERT
8. **制品包必跑**：UT 通过后自动生成制品包（不再可选），文件名 `shujia_{表名}.xlsx` / `lts_{表名}.xlsx`
9. **platform_config 按 schema 映射**：术加/LTS 两套配置按 schema 映射，子项目编码留空

**渲染优化类：**
10. **ts.md §4 精简**：无关联策略、字段概要改为字段逻辑（只列有口径的加工字段）、关联安全仅有风险时展示、场景 default 不显示、加了写入方式
11. **ts.md §5 只有图**：血缘关系表和执行顺序表已删（被图覆盖）
12. **ts.md §6 调度完整**：F表调度 + LTS参数表 + 上游依赖表 + I视图调度（如有）
13. **mermaid 图 Typora 兼容**：用 class 语句赋类（不用 ::: 内联），无 base 主题覆盖
14. **预处理不告警**：未匹配的列静默跳过，不再报 column_unmatched

**持续验证项（之前轮次的）：**
15. **参数化机制**：exec_params 有 P_CYCLE_ID；UT 执行前替换 `${PARAM}`
16. **数据源缺口前移**：designer 发现缺口用 question 弹确认，不写进 ts.json
17. **--all-rules**：多规则案例能编出全部规则
