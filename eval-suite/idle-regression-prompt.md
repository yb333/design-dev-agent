# 闲时回归评测提示词

> 用于空闲时段批量跑案例回归。复制下面的提示词给 agent（opencode/任意 coding agent），让它在项目目录下执行。

---

## 提示词（复制以下全部内容）

你在 design-dev-agent 项目（/Users/yuanbo/design-dev-agent）里，任务是跑本地案例回归评测。

### 背景

项目有一套本地评测脚本 `eval-suite/local_eval.py`，能一键跑通设计+编码全流程（preprocess → designer → assemble_ts → coder → assemble_ddl → check_sql），输出评测报告。

案例集在 `eval-suite/cases/` 下，每个案例有 `mapping.xlsx` + `RS.md`。

### 第一步：先跑全量脚本链路验证（快速，不调AI）

对所有案例跑 `--skip-ai` 模式（只验证输入转换和脚本链路，不调 opencode AI，每个几秒）：

```bash
cd /Users/yuanbo/design-dev-agent
for case_dir in eval-suite/cases/0*/; do
  asset=$(basename "$case_dir")
  echo "========== $asset =========="
  python3 eval-suite/local_eval.py \
    --asset "$asset" \
    --mapping "$case_dir/mapping.xlsx" \
    --rs "$case_dir/RS.md" \
    --skip-ai --clean 2>&1
done
```

记录哪些案例的脚本链路有问题（preprocess/precheck 报错），修完再往下。

### 第二步：逐个跑完整AI流程

对每个案例跑完整流程（含AI）。**从小到大跑**——小案例快，大案例慢：

```bash
# 每个案例单独跑，观察结果
cd /Users/yuanbo/design-dev-agent

# 小案例（7-30字段，约2-5分钟/个）
python3 eval-suite/local_eval.py --asset dwb_trade_order_d   --mapping eval-suite/cases/002_dwb_trade_order_d/mapping.xlsx   --rs eval-suite/cases/002_dwb_trade_order_d/RS.md   --clean
python3 eval-suite/local_eval.py --asset dwb_trade_wide_f    --mapping eval-suite/cases/003_dwb_trade_wide_f/mapping.xlsx    --rs eval-suite/cases/003_dwb_trade_wide_f/RS.md    --clean
python3 eval-suite/local_eval.py --asset dwb_shop_center_f   --mapping eval-suite/cases/004_dwb_shop_center_f/mapping.xlsx   --rs eval-suite/cases/004_dwb_shop_center_f/RS.md   --clean
python3 eval-suite/local_eval.py --asset dwb_supply_chain_f  --mapping eval-suite/cases/007_dwb_supply_chain_f/mapping.xlsx  --rs eval-suite/cases/007_dwb_supply_chain_f/RS.md  --clean
python3 eval-suite/local_eval.py --asset dwb_after_sale_center_f --mapping eval-suite/cases/008_dwb_after_sale_center_f/mapping.xlsx --rs eval-suite/cases/008_dwb_after_sale_center_f/RS.md --clean
python3 eval-suite/local_eval.py --asset dwb_marketing_center_f --mapping eval-suite/cases/011_dwb_marketing_center_f/mapping.xlsx --rs eval-suite/cases/011_dwb_marketing_center_f/RS.md --clean

# 中等案例（35-50字段，约5-10分钟/个）
python3 eval-suite/local_eval.py --asset dwb_product_center_f --mapping eval-suite/cases/009_dwb_product_center_f/mapping.xlsx --rs eval-suite/cases/009_dwb_product_center_f/RS.md --clean
python3 eval-suite/local_eval.py --asset dwb_user_center_f    --mapping eval-suite/cases/005_dwb_user_center_f/mapping.xlsx    --rs eval-suite/cases/005_dwb_user_center_f/RS.md    --clean

# 大案例（100+字段，可能15-30分钟/个，超时是正常的）
python3 eval-suite/local_eval.py --asset dwb_order_center_f   --mapping eval-suite/cases/012_dwb_order_center_f/mapping.xlsx   --rs eval-suite/cases/012_dwb_order_center_f/RS.md   --clean
python3 eval-suite/local_eval.py --asset dwb_user_profile_f   --mapping eval-suite/cases/010_dwb_user_profile_f/mapping.xlsx   --rs eval-suite/cases/010_dwb_user_profile_f/RS.md   --clean
python3 eval-suite/local_eval.py --asset dwb_user_behavior_f  --mapping eval-suite/cases/006_dwb_user_behavior_f/mapping.xlsx  --rs eval-suite/cases/006_dwb_user_behavior_f/RS.md  --clean
```

### 第三步：对每个案例的结果做以下检查

跑完后，对每个案例检查产出：

1. **ts.json 结构**：顶层键完整、rules 有字段、business_key 有值、source_tables 不为空
2. **design_decisions 质量**：规则拆分是否合理、field_logics 口径是否准确、关联安全分析是否完整
3. **SELECT 质量**：字段覆盖是否完整、COALESCE 是否到位、CTE/JOIN 结构是否正确
4. **check_sql 是否通过**：静态对比有没有报错
5. **DDL 正确性**：字段/类型/审计字段/分布键/TO GROUP 是否齐全

检查命令示例：
```bash
# 看某个案例的产出
ASSET=dwb_user_center_f
DELIVER=10_project_deliver/$ASSET/ddlc_design_dev
cat $DELIVER/ts.json | python3 -m json.tool | head -20
cat $DELIVER/_internal/design_decisions.yaml | head -30
cat $DELIVER/select/R0001_select.sql
```

### 第四步：发现问题自行修复

发现的问题分类处理：

- **格式/结构问题**（脚本bug、校验逻辑问题）：直接修复代码，改完重跑验证
- **AI产出质量问题**（design_logic 口径错、SELECT 逻辑错）：记录下来，分析是 skill 指引不够还是模型能力问题
- **业务问题**（不确定对不对的）：记录下来，不确定的不要改

### 注意事项

1. **先安装最新 skill/agent/command**：
   ```bash
   cd /Users/yuanbo/design-dev-agent
   python3 install.py
   # 如果 install.py 卡依赖检查，手动复制：
   # cp agents/dws-*.md ~/.config/opencode/agents/
   # cp -r skills/dws-design skills/dws-coding ~/.config/opencode/skills/
   # cp commands/*.md ~/.config/opencode/commands/
   ```

2. **大案例可能超时**：264字段的用户行为三场景可能需要很长时间，超时正常。可以单独跑不批量。

3. **每个案例的产出在** `10_project_deliver/{资产名}/ddlc_design_dev/` 下，跑完可以对比不同案例的设计决策差异。

4. **改了脚本后要同步到全局安装**：`cp skills/xxx/references/xxx.py ~/.config/opencode/skills/xxx/references/`

5. **最终提交**：把修复的问题和评测结果 commit + push。
