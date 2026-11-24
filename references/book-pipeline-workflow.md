# 单书生成、核验与部署

复用已确认的主线、代表讲解与规范单元。模型负责阅读、解释和语义核查；统一入口只装配这些内容、做机械检查、整理公开派生与部署，不自动拆解未读正文或授予内容批准。

## 逐章阅读路线

`author-structure.json` 的 `originalStructure[]` 可选增加：

```json
{
  "chapterNumber": 5,
  "title": "第二篇 · 第一章 原章名",
  "originalPart": "第二篇",
  "originalChapter": 1,
  "readingQuestion": "这一章具体回答什么问题？",
  "concepts": ["核心概念", "重要区别"],
  "bridge": "本章如何承接前文，又给后文准备什么？"
}
```

这些字段补充现有 `pageStart/pageEnd/unitIds`，不能取代原章名和映射。问题、概念选择和衔接解释标为编辑归纳；作者明确命名的分类仍需实际出处。`concepts` 也可用字符串，兼容既有单书。缺少路线字段的旧档案保持原布局，脚本不会替书籍凭空补写。新增时依原章节逐章补齐，以实际材料决定详略，不强加统一模型。

首页先保留简明全书主线、部分解释和代表章节入口，再展示当前分组的逐章路线；切换分组时只显示相应章节。问题默认可见，概念和承接按需展开，按钮跳到对应规范单元。原篇内章号与内部唯一 `chapterNumber` 分开，避免把第二篇第一章误标成原书第五章。

## 一个配置贯通

复制 `examples/book-pipeline/config.json` 到书籍项目，填写真实路径。相对路径相对于配置文件，不依赖当前终端目录。输入、交付、公开目录及状态目录须互不嵌套。可选 `sourcePdf`、`coverImage/coverPage`、`representativeReading` 沿用原构建器的含义。所有输入仍需先完成来源与内容核查。

```text
python3 scripts/book_pipeline.py BOOK/config.json
```

默认执行 **生成 → 机械核验 → 公开文件整理**，不会联网发布。

- 生成：调用作者主线构建器；保留稳定ID、来源、原文图像与同源Markdown。单文件HTML内嵌封面和原图，离线可读。
- 核验：生成文件所有权哈希、章节到单元的完整映射、原文切片哈希、HTML与档案一致性、Wiki单元数；可用时检查JavaScript语法。报告不等于语义审核或浏览器验收。
- 公开整理：只复制明确允许的档案和原图；去除本机路径、执行者字段、对话确认原句与内部工作记录；扫描剩余私有路径，生成 `learning-archive.zip` 和公开文件清单。保留学习解释和原文切片，不发布原PDF。失败不覆盖上一份公开成果；发现用户编辑时拒绝覆盖。

可分别执行 `--stage build`、`--stage verify`、`--stage prepare`，用同一配置续跑。生成器只覆盖它自己的、哈希未变的产物；无需重新提取或重新编写未变正文。

## 浏览器验收与发布

有部署授权时继续完成，不在本地生成后仅回复“稍后部署”。没有部署请求时止于本地交付。执行者实际检查公开目录的桌面、窄屏、主线／章节切换、搜索、详情、出处及图像，保存配置所指的 `browserReview`：

```json
{
  "htmlSha256": "public-site/index.html 的当前SHA-256",
  "desktop": true,
  "mobile": true,
  "navigation": true,
  "sources": true
}
```

没有实际运行的检查不能填true。检查后内容或模板变化导致哈希改变，重新检查受影响部分。`contentReadiness` 由执行者如实记录：仅在约定内容范围已完成时填 `status: ready`，`note` 说明实际阅读、复核与缺口；脚本不生成语义批准。已有确认不重复审批，结构或范围未确认时仍按作者主线约定处理。

在用户明确授权的项目上填写准确的 `projectId/projectName/teamId/productionUrl`。使用已安装且登录的 Vercel CLI，先通过可用连接器查询或创建明确项目，再填配置；流程不隐式创建项目、不下载环境变量、不修改其他项目。

```text
python3 scripts/book_pipeline.py BOOK/config.json --stage deploy
```

或在证据已匹配当前生成结果时使用 `--deploy` 连接本地流程与发布。部署前再次检查公开清单、结构确认、内容就绪说明和浏览器证据哈希；检查本地链接与远端项目ID，执行生产部署。仅在READY、生产域名匹配，且匿名获取主页、内容数据、Wiki导出与ZIP的哈希均相符时，生成 `publication.json` 并报告部署完成。失败的响应与日志留在状态目录，依据实际阶段续跑，不把上传成功当作上线验证。

`pipeline-state/` 含本地路径、配置状态与部署日志，不能上传。书籍PDF、私人书稿和项目内容不随通用skill提交GitHub；仅发布模板、脚本、合成测试和使用说明。
