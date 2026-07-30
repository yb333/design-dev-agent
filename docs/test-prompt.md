# 测试 Prompt

> 安装后（`install.bat`），在 opencode/codeagent 里直接用 command 测试。

---

## 测试：完整流程（/new-pipe）

在 opencode 里输入：

```
/new-pipe @docs/templates/mapping模板.xlsx @docs/templates/RS模板.md
```

### 预期流程
1. 自动预处理（解析 mapping + RS → rs_input.json）
2. 自动调 dws-designer 产出 TS（ts.json + ts.md）
3. ⏸️ 闸口①暂停，展示设计摘要，等你确认
4. 确认后自动调 dws-coder 产出 SQL/DDL
5. 完成报告

### 检查点
- [ ] rs_input.json 生成在 01_input/
- [ ] ts.json + ts.md 生成在 02_design/
- [ ] ts.json 以规则为核心（R0001 + R0002），design_logic 是自然语言
- [ ] 闸口①展示了设计摘要并暂停
- [ ] SQL/DDL 生成在 04_ddl/ 和 05_etl/
- [ ] DDL 有 IF NOT EXISTS + 分布键 + 审计字段
- [ ] ETL 没有 SELECT *，NULL 有 COALESCE
