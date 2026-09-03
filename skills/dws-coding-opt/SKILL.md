---
name: dws-coding-opt
description: >-
  DWS ETL 优化模式编码工作流（add_field）。被 dws-coder agent 在【优化场景】加载
  （调用方 prompt 显式声明优化模式时）。职责不变（唯一产出 SELECT）；工作流换成
  优化版：以 baseline SQL 为底稿加列，不从零写，老列投影一个字符不许动。
  编码规范与工具路径引用 dws-coding（不搬家）。
---

## ⚠️ 文件路径规则

本 skill 无 scripts 副本——工具在 dws-coding skill，按相对路径引用（本 skill 目录上三级即 skills/ 根）：
- 切片：`{skills根}/dws-coding/scripts/slice_ts.py`（优化模式加 `--baseline-sql` 参数）
- 自检：`{skills根}/dws-coding/scripts/check_sql.py`（可选习惯；闸门在 pipe 的 SQL 围栏）
- 编码规范：`{skills根}/dws-coding/references/`（与新建共用同一套）

## 一、你与新建模式的三个不同

1. **以 baseline SQL 为底稿加列**——切片的 `opt.baseline_sql` 是生产在跑的原文，
   你在它上面**追加新列**，不从零重写。
2. **老列投影一个字符不许动**（AST 级机器比对）：格式可以变（空白/换行），等价改写
   不行（`='N'` 改 `<>'Y'` 也算越界）。想改老列 → 回报调用方走变更清单扩充，别动手。
3. **FROM/JOIN/WHERE/GROUP BY/CTE 冻结**——唯一例外是切片 `opt.declared_new_joins`
   里声明的新 JOIN（按声明的别名+表+ON 写）。

## 二、单线工作流（四步）

### 1. 拿优化切片（不要直接读 ts_v2.json）
```bash
python {skills根}/dws-coding/scripts/slice_ts.py \
  --ts {opt}/ts_v2.json --rule {rule_code} \
  --baseline-sql {arc}/etl/{rule_code}.sql
```
切片含：规则上下文 + `opt.baseline_sql`（底稿）+ `opt.declared_new_fields`（要加的列）
+ `opt.declared_new_joins`（许可的新 JOIN）+ 硬约束四条。

### 2. 以底稿加列
- 复制 baseline_sql 全文为起点，**只在 SELECT 投影末尾追加声明的新列**
  （表达式按新字段的 design_logic 翻译，规范同 dws-coding：注释 `/* */`、NULL 按业务语义）
- 有 declared_new_joins 时：在底稿的 FROM/JOIN 区追加该 JOIN（ON 用声明里的条件原样）
- 除此之外什么都不动：不重排版老列、不动 WHERE/GROUP BY、不加 CTE、不"顺手优化"

### 3. 自检（可选习惯，闸门在 pipe）
```bash
python {skills根}/dws-coding/scripts/check_sql.py --sql {SQL文件} --ts {opt}/ts_v2.json --rule {rule_code}
```
调 check_sql 静态对比；通过与否都落盘——pipe 的 SQL 围栏（sql_fence）是唯一强制闸门，
越界会带着 `[SQL围栏]` 报错回来找你（恢复本会话改，限 3 轮）。

### 4. 落盘
`{opt}/etl/{rule_code}.sql`（**与档案同名**——opt 语境里一个规则一个文件，新 SQL 即该规则当前版）。
新账旧账不同目录：**{opt}/etl/ 是你的，{arc}/etl/ 是档案（只读勿改）**。

## 三、UT 失败回退时

- SQL 报错（COLUMN/TYPE/SYNTAX）→ 你改语法（恢复本会话）
- 数据质量/对比失败（老列不一致）→ **不归你**，别用 ROW_NUMBER"修"它——那是掩蔽根因
