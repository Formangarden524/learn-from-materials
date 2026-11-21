# 参考：wiki 集成式学习站点（wiki-llm 前端化 + antd 离线打包）

> 本文件记录 2026-11「中医基础思维十讲」项目中的实践反馈。起因是用户反馈：
> learn-from-materials 的学习页"界面非常难看，且只体现了书，没有体现 wiki 从书中
> 挖掘的内容部分"。本文档沉淀由此提炼的可复用模式，供后续项目参考。
> 本文档是增量参考，不改变 SKILL.md 的任何工作流门禁。

## 1. 问题诊断：为什么"只体现书"

learn-from-materials 的数据主线是**书**（书页→章节→摘录→卡片），知识挖掘产物
（概念、关系、题库、场景）即使存在，也没有一等公民的 UI 入口。结果：站点是
"书的复读机"，挖掘层不可见。

## 2. 核心模式：站点 = wiki 的纯函数

```
wiki/（唯一内容源：词条 md + frontmatter + wikilinks + 原文层索引）
  │  scripts/build_site.py（构建期派生，<10s，幂等）
  ▼
site/（静态产物，data.js 全量内嵌 → file:// 双击可开）
```

- **三个派生源全部自动**：关系边表（解析全站 `[[slug|名]]` wikilinks）、检索索引
  （词条层 + 原文层 chunks，行号由字符偏移换算）、题库（人工 seed + 概念定义
  自动挖空，按 id 合并覆盖）。
- **单向依赖**：站点只读 wiki；wiki 变更 → 重跑构建 → 站点自动一致。
  不存在"改了 wiki 忘了改站点"的一致性问题。
- **构建期断言**：死链（wikilinks 指向不存在的 slug）构建即失败，响亮失败。

## 3. 挖掘层的一等公民 UI

| 挖掘产物 | UI 入口 | 派生方式 |
|---|---|---|
| 概念页（type: concept） | 概念图谱页（卡片栅格 + map 着色 + depth 徽章） | frontmatter 直读 |
| wikilinks 关系 | 力导向/分层关系图（节点点击跳转） | 构建期解析 |
| 原文层证据 | 词条内"原文行 N–M"自动变 chip → Drawer 下钻原文段落 | 行号正则 + 原文索引 |
| 案例（type: case） | 案例 Tab（按 category 分组） | 原生页面类型归位 |
| **场景**（时间·环境·人·条件） | 场景 Tab（四要素卡片） | case 页 frontmatter `scene_*` 字段 + 概念页「应用场景」节 |
| 题库 | 自测（一次一题、错题集、localStorage、JSON 导入导出） | seed + 自动 |

**"场景"的定义**（用户提出，值得固化为通用概念）：案例是发生过的事；场景是
"什么时间、什么环境、什么样的人、在什么条件下"会用到这条知识或这个案例——
它是普通人→知识之间的桥，比案例更接近读者的入口。实现上零新增页面类型：
用 frontmatter 私有字段承载，构建期聚合。

## 4. 双主线信息架构

不要替用户决定"从书读"还是"从知识查"——两条主线都保留，默认书的主线：
- 主线 A 读书：章节顺序 + 阅读进度（Steps/Cards）
- 主线 B 知识：概念/图谱/检索
- 主线 C 案例场景：普通人最爱的入口

## 5. 技术形态：antd 离线打包（无框架工程）

- `npm i react@18 antd@5 @ant-design/icons dayjs markdown-it esbuild`（一次性）
- esbuild 单命令打包 TSX：无 vite/无 HMR/无配置；`--jsx=automatic --minify`
- antd v5 的 cssinjs 运行时打包即用，无需额外 CSS 产物（reset.css 由 esbuild 一并
  输出为 app.css）
- 全部数据内嵌 `data.js`（`<script src>` 加载），**不 fetch**，天然兼容 file://
- 视觉走 ConfigProvider token（宣纸底 #f5f0e6、朱红 #b03a2e、宋体标题），
  亮暗双主题一个 Switch

## 6. 质量清单（构建期自动题干的教训）

- 从 markdown 自动挖空生成选择题时，必须**清洗文本**（去 wikilink/加粗/【】标记），
  并过滤含 `=` 开头、超长、带残留标记的定义——否则选项里会出现 `[[slug|名]]`
  这类杂质，非常难看（本项目实踩）。
- esbuild 是转译不做名检查：TSX 里漏 import 要到运行时才炸（React onClick 处
  ReferenceError），构建脚本应 grep 一轮 `page(` 等高频符号，或靠 Playwright
  交互测试兜底。
- 验证用 Playwright 时浏览器缓存会拿到旧 bundle：用 CDP
  `Network.setCacheDisabled` + reload，否则"修了但没生效"的假象会浪费排查时间。
