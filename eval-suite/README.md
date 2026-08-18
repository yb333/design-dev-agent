# eval-suite 评测系统使用约定

> 入口：双击 `eval.bat`（Windows）/ `./eval.sh`（mac/linux），或直接调 CLI（见下）。
> 设计原则：**评测调真实流程 + 只对产出做断言**；golden 只能人手工沉淀；
> 评测零交互（批量跑不问任何问题，需要人判断的一律落报告）。

---

## 一、目录约定（★ 东西放哪，看这张表）

| 角色 | 位置 | 说明 |
|---|---|---|
| 虚拟案例输入 | `eval-suite/cases/{资产}/` | mapping.xlsx + RS.md + checks.yaml（可选），001~012 + T 系列陷阱 |
| **真实案例输入/要点** | `eval-suite/cases_real/{分类}/{资产}/` | 分类目录你自由命名（如 `增量合并/`）；内网放真实业务数据，gitignore 不入库 |
| deliver_only 临时落点 | `eval-suite/cases_real/未分类/{资产}/` | 只有产出没输入的案例 seed 时自动建，后续 mv 到合适分类 |
| **golden（标准答案）** | `eval-suite/cases_real/{分类}/{资产}/golden/{方案名}/` | 一份完整认可产出（ts.json+etl/+ddl/...），**只能人手工沉淀** |
| 真实案例产出 | `10_project_deliver/{appid}/{schema}/{资产}/ddlc_design_dev/` | new-pipe 跑出来的；老平铺 `{资产}/` 也兼容，自动定位 |
| 评测存档 | `eval-suite/results/{case}/{时间戳}/result.json` | 每轮快照（断言结果+git sha），baseline 对比和稳定性报告的数据源 |
| 异常轮留档 | `eval-suite/results/{case}/{时间戳}/artifacts/` | 仅失败/越界轮拷完整产出，稳定轮不占磁盘 |
| 失败诊断全文 | `10_project_deliver/.../ddlc_design_dev/_internal/diagnose/pipeline_{阶段}.log` | 流水线某阶段挂了，输出全文在这 |

## 二、命令

```bash
# 交互式菜单（推荐，引导选择）
./eval.sh                                    # 或双击 eval.bat

# CLI 直调
python3 eval-suite/v2/run.py --case 002                     # 单案例：真实入口全流程+评测（默认）
python3 eval-suite/v2/run.py --case 002 --eval-only          # 只评测已有产出
python3 eval-suite/v2/run.py --case 002 --replay             # 分阶段重放（诊断：定位哪个阶段挂/慢）
python3 eval-suite/v2/run.py --all --cases-dir=eval-suite/cases_real   # 全部真实案例
python3 eval-suite/v2/run.py --case X --repeat 10            # 稳定性：真实入口连跑10次出报告
python3 eval-suite/v2/run.py --case X --timeout-pipe 7200    # 真实流程整条超时（默认3600s）
python3 eval-suite/v2/run.py --case X --replay --skip-ai     # 重放+跳AI（脚本链路快查）

python3 eval-suite/v2/seed.py --case X --cases-dir=eval-suite/cases_real --review
#    ↑ 从产出抽事实生成 checks.yaml 草稿（[AUTO-SEEDED] 需人工 review 固化）

python3 eval-suite/v2/promote.py --case X [--name 方案A] [--from <deliver路径>]
#    ↑ 手工沉淀 golden：把你实际调测中认可的产出拷进案例 golden/（纯拷贝，认可决定在人）
```

## 三、评测分层（报告从上到下）

| 层 | 判什么 | 失败归因 |
|---|---|---|
| 流程层 | preprocess/precheck/designer/coder/DDL/export 各阶段 | 脚本/契约/案例数据 |
| 产物层 | ts.json 结构/文件齐全/DDL回退成对 | assemble_* 脚本 |
| design 质量 | business_key/field_targets/load_mode/join_safety | designer 角色 |
| code 质量 | 字段完整/JOIN 覆盖/GROUP BY 粒度/CASE ELSE | coder 角色 |
| **golden 命中** | 产出指纹 vs 人审 golden 集合 | **待人工裁决**（新方案→promote；回归→修） |

## 四、golden 纪律（红线：语义判断不自主）

1. **只能人手工沉淀**：`promote.py` 是纯拷贝工具，"这个产出认不认可"永远人定；
   评测系统绝不自动把某轮产出推成 golden。
2. **比指纹不比文本**：business_key/规则集/load_mode/field_targets/每规则 SELECT 的
   字段·JOIN·GROUP BY——同一 golden 允许多种 SQL 写法。
3. **多解兼容**：golden 集合可存多个方案（方案A/B/C），命中任一即 PASS；
   全不中 = 越界 → FAIL 标出与最接近方案的差异，待人工裁决。
4. 典型循环：实际调测出认可产出 → promote 沉淀 → `--repeat N` 批量测 →
   报告里出现"未命中"轮 → 人裁决（新方案再 promote 一个 / 视为回归去修）。

## 五、稳定性报告怎么读

- **每轮结果**：N 轮各自通过/失败 + golden 命中状态；异常轮产出已留档
- **断言稳定性**：`稳定过`（N/N 全过）/ `稳定挂`（0/N 全挂，系统性问题）/
  `摇摆`（时过时挂——agent 非确定性的直接信号，看失败那几轮差在哪）
- **golden 命中分布**：方案A 6/10 + 方案B 3/10 = 正常波动（都审过）；
  `未命中 1/10` = 越界轮，待裁决
- **流程阶段稳定性**：某阶段偶发挂（如 precheck 9/10）也是摇摆信号

## 六、其他约定

- **执行方式**：默认**真实入口**（`<启动器> run --command new-pipe` + 显式非交互声明，
  编排 100% 走 commands/new-pipe.md，评测零编排拷贝）；`--replay` 为分阶段重放诊断模式。
  真实入口下流程层是单步（不拆阶段计时），要分阶段定位用 `--replay`。
- **agent 启动器**：自动解析顺序 `--opencode`/EVAL_OPENCODE → `nga`（内网包壳）→
  `opencode`（本地/标准）。包壳不支持 `--command` 旗标时用 `--opencode` 指到
  支持的入口并反馈，评测侧可切换为消息内 `/new-pipe` 前缀方式。
- **UT 连库属于真实流程**：真实入口跑的是完整 new-pipe（含 check_db 探活 + UT），
  评测不干预——测的就是真实行为；`--replay` 重放模式不含 UT。
- **输入文件发现**：案例目录的业务文件就两类——唯一的 *.xlsx/xls 即 mapping，
  唯一的 *.md/txt 即 RS（可选，无则无RS模式）；评测自己的 yaml/json 不占这两个
  后缀不干扰。多个时名字含 mapping/rs/需求 的优先。真实入口提示词、重放预处理、
  案例发现全部走同一套发现。
- **产出定位（三层唯一约定）**：`10_project_deliver/{appid}/{schema}/{资产}/ddlc_design_dev/`。
  真实入口跑完自动重新定位；重放模式无既有产出时按 schema（mapping 目标表）+
  appid（schema_apps.json）推导三层路径；平铺老结构不再识别。
- **超时**：真实流程默认 3600s（`--timeout-pipe`）；重放模式 AI 1800s/脚本 120s
  （`--timeout-ai`/`--timeout-script`）。超时 kill 该阶段标记失败，**不拖垮整轮**。
- **失败排查**：报告失败详情带输出尾部（traceback 崩溃行）+ 全文 log 路径。
- **WinError 2（Windows 找不到启动器）**：npm 全局装的 opencode 是 opencode.cmd，
  Python Popen 不按 PATHEXT 解析 → 已内置 `shutil.which` 解析（nga/opencode 同理）；
  仍找不到就用 `--opencode` 传完整路径。
- **版本提示**：快照存 git sha；repo 与全局安装技能有版本差时，结果解读要留意
  （建议跑评测前重跑 `install.py` 同步，或确认评测走 repo 源——默认 repo 优先）。
