# docs/ppt — 演示材料索引

> **维护规则**（2026-10-15 定）：本目录主区只放「现行」演示材料；被取代/过时的移入 `archive/` 原样保留、不再维护。
> 新 deck 一律用 deck-studio 构建（单 HTML；需要 PPTX 用播放器 ⤓ 按钮自助导出，PPT=可编辑 / 图=快照）。
> 旧格式（frontend-slides 手搓翻页、无导出能力）不再新增。

## 现行

| 文件 | 说明 |
|---|---|
| `project-overview_deck-studio.html` | ★ **项目总纲**（16 页·四章骨架）：导览（主张+体系全景+抽页路线）→ 1 为什么要做[背景] → 2 做成了什么[形态/流转/编排] → 3 凭什么可信[质量总纲/校验/失败分流/人的位置] → 4 怎么用、值多少[使用方式/场景/实效边界/成果/进展]。页码章化（如 3-2），章首页标题=章问题。对外默认入口，个别场合抽页讲 |
| `project-overview_deck-studio.plan.md` | 总纲伴生规划：逐页来源映射、动画申报、数字口径（实测日期）、QA 记录 |

**扩展方式**：项目优化/新增内容 → 直接改总纲对应页（每页自包含 SVG，改动互不影响）；某主题要单独分享 → 从总纲抽页另起单主题 deck，起名 `{主题}_deck-studio.html` + 伴生 plan.md。

**数字纪律**：deck 里引用实测数字（用例数/校验数/脚本数）时在 plan.md 记实测日期与命令；发现数字过期 → 改 deck 同步改 plan.md（历史 deck 不回改，归档即定格）。

## archive/（历史归档，按定格时间排序）

| 文件 | 定格 | 内容 | 归档原因 |
|---|---|---|---|
| `agent-concept.html` | 2026-07-28 | 最早概念稿（6 页，旧格式） | **不进 git**（历来只留本地）；被 deck-studio 版两度取代 |
| `architecture-overview.html` | 2026-07-30 | 早期架构全貌（9 页，旧格式） | 早于编排重构/opt-pipe/DQ 拆分，结构与现状不符；无法导 pptx |
| `agent-concept_deck-studio.html` | 2026-09-23 | 概念稿 deck-studio 重制版（6 页） | tech-review 的底稿，角色已完成 |
| `tech-review_deck-studio.html` + `.plan.md` | 2026-09-23 | 技术评审汇报 v6（13 页） | 主体已整合进总纲（8 页为主干）；进展/数字停在 9 月 |
| `user-briefing.html` | 2026-09-11 | 面向使用者宣讲（8 页，旧格式） | 标题与使用视角已进总纲；早于 DQ 拆分；无法导 pptx |
| `quality_deck-studio.html` + `.plan.md` | 2026-10-13 | 质量分享·防线框架版（8 页） | 主线被环节实例版取代；防线三页=总纲「人的位置」页来源 |
| `quality-stages_deck-studio.html` + `.plan.md` + 两份 `.pptx` | 2026-10-14 | 质量分享·环节实例版（6 页，领导反馈落地版） | 总纲/制品开发/实效边界三页已进总纲；单独分享场合从总纲抽页新做 |

> 总纲逐页来源映射见 `project-overview_deck-studio.plan.md` 文末「历史内容映射」表。
