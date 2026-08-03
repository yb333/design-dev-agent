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

### 第四步：逐案例检查产出质量

每个案例跑完后检查以下内容：

**1. 案例自检**
```bash
python3 eval-suite/check_case.py --mapping eval-suite/cases/0XX_xxx/mapping.xlsx --rs eval-suite/cases/0XX_xxx/RS.md
```

**2. ts.json 结构**
```bash
DELIVER=10_project_deliver/{资产名}/ddlc_design_dev
python3 -c "
import json
ts = json.load(open('$DELIVER/ts.json'))
# 顶层键
for k in ['version','meta','design','rules','data_flow','dq_rules']:
    assert k in ts, f'缺顶层键: {k}'
# business_key
assert ts['design'].get('business_key'), 'business_key 为空'
# load_mode（每个规则都有）
for code, rule in ts['rules'].items():
    assert 'load_mode' in rule, f'{code} 缺 load_mode'
# source_tables 补全
for code, rule in ts['rules'].items():
    for st in rule.get('source_tables', []):
        assert st.get('table'), f'{code} source_tables 有空 table'
print('✅ ts.json 结构通过')
"
```

**3. DDL 完整性**（每个DDL有回退脚本，I视图不用SELECT*）
```bash
DDL_DIR=$DELIVER/ddl
RB_DIR=$DELIVER/ddl_rollback
# DDL 数量 = 回退脚本数量
DDL_COUNT=$(ls $DDL_DIR/*.sql 2>/dev/null | wc -l)
RB_COUNT=$(ls $RB_DIR/*.sql 2>/dev/null | wc -l)
echo "DDL: $DDL_COUNT, 回退: $RB_COUNT"
# I视图不用 SELECT *
grep -l "SELECT \*" $DDL_DIR/create_view_*.sql 2>/dev/null && echo "⚠️ I视图用了SELECT*" || echo "✅ I视图OK"
```

**4. DQ 生成**（标准DQ准确，定制DQ留TODO）
```bash
DQ_DIR=$DELIVER/dq
ls $DQ_DIR/*.sql 2>/dev/null && echo "有DQ文件" || echo "⚠️ 无DQ文件"
# 检查标准DQ（主键唯一/审计非空/记录数）
grep -l "total_count" $DQ_DIR/*.sql 2>/dev/null && echo "✅ 有记录数检查"
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

本轮代码有大量改动，重点验证：
1. **目标表写_i结尾**：mapping目标表物理名称写I视图名，preprocess从_i推导_f
2. **load_mode**：每个规则有写入方式（truncate_table/no_delete/truncate_partition等）
3. **DQ分工**：标准DQ脚本生成（主键/审计/记录数），定制DQ留TODO交coder
4. **数据探索提取**：RS的L01章节（数据量级/空值率/发散说明）提取到rs_input
5. **文件命名**：ts.md带资产名前缀，ETL文件名带规则名+load_mode
6. **列名大小写不敏感**：Schema/schema都能匹配
7. **校验分级**：目标表schema/table两边都没写→阻断，一边没写→告警
8. **db-sources.json**：在~/.config/opencode/下（不在skill目录），install不覆盖
9. **designer审视意识**：主键发散/关联缺失应该在设计阶段发现
