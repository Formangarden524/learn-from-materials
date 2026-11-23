# 交互导读：先有主线，再展开内容

用于用户只要样板、主线导读、指定部分或一份材料的轻量阅读页。普通整本书拆解按 `author-led-book-workflow.md`，其首阶段可复用本文件的呈现方法，但最终仍需完整单书档案。此路线生成独立导读工件，不新增 schema 4.3 的 `learningDepth` 值，不经旧 `finalize.py`，也不声称完成全书或通过系统学习的完整覆盖门禁。用户明确要求 quick 或 systematic 时继续走原路线。

## 1. 复用材料，先识别结构

- 先检查用户指定目录内已有提取、来源映射、章节索引和已核内容，核对源文件指纹及适用范围。原文未变不重复提取或 OCR；已有复核只在输入与相关内容未变时复用。
- 新材料复用现有提取脚本、安全检查与真实定位。扫描全部结构，核对目录、标题、开头、收束及各主要部分的代表正文；不能只凭目录编造全书结论。结构扫描不等于逐页精读，未读、不可读和关键图表未核验范围分别保留。
- 先寻找材料本身的中心问题、论证骨架与章节作用，再决定导读结构。保留作者原目录作为对照。总模型、子机制、条件、案例与查阅资料应有层级，不把所有条目平列为核心框架。
- 结构服从材料；不强套黄金圈、固定节点数、固定步骤或特定专业模型。概念、比较和资料型材料不必伪装成行动流程。

## 2. 尽早交付主线与代表单元

先做一屏能看清的材料主线，再选择能检验实际难点的代表单元：有实质解释、重要区别或前后联系；不要只挑最容易的开头。样板同时呈现主线、代表讲解和原目录对应，不等全书条目写完才渲染。

代表讲解要让读者说清“是什么、为什么、与上下文是什么关系”，保留原书的关键条件、区别与一个合适的例子；材料没有例子时如实说明，不补造。默认层讲通推理，术语、完整案例和更多证据按需展开。内容长度随理解需要调整，不以固定字数或卡片数代替判断。

先检查结构和讲解深度，再增加内容。样板出现主次不清、解释只剩标签或细节混排时，先修结构，不先扩建整书术语、题库、方法论和多份账本。

## 3. 明确三类内容的身份

- **原书直引**：连续原句，保留实际用词，标具体章节与页码／段落；提供必要上下文。
- **原书转述**：忠实解释实际段落，保留主张、条件、反例及不确定性，不能把作者经验改成普遍结论。
- **导读归纳**：整理者新增的阅读问题、分组、标题及连接关系，明确标示；作者原有框架仍说明其出处。阅读顺序不冒充作者原流程或因果关系。

展示断言及关系应能回到来源；核对的是该段原文是否支持所写解释，而不只是引句是否存在。图表承担关键论证时实际查看；未核验的图表不转写为确定事实。材料观点、编辑理解和外部核验继续分开。

## 4. 按授权扩展，避免重复审批与重做

用户要求“先看样板”时，交付到这里并等待方向反馈。已授权整本生成，或已批准结构与详略时，沿用该结构自主扩展，不重复询问同一确认。样板是后续正式内容的一部分，保留其已核文字、来源和有效检查。

扩展时按当前范围补读原文，只处理新增或受影响内容。更改某个术语、单元或关系时核查它的依赖，不无故重读、重写所有章节。发现原主线不足以容纳重要内容时先调整主线并说明影响；不要为维持样板而隐去冲突。

单份内容源生成网页，复用轻量模板与已有交互。调用 `python3 scripts/render_guided.py content.json --output delivery/reading.html`，由 `templates/guided-reader.html` 渲染；脚本仅检查必要输入、引用 ID 和 HTML 完整性，不生成“语义已复核”结论。内容与界面分开，不每本书重造界面，也不把同一解释分别手写到多个派生文件。固定模板只复验受影响交互；每次材料交付仍检查该材料的实际布局与出处入口。

## 5. 轻量内容源

渲染器接受 `schemaVersion: learn-from-materials/guided-reading-v1`，与旧 overview 分开。沿用 JSON 单份内容，字段如下；原文引用与实际复核由执行者负责。

- `meta`：`book`（通用材料标题）、`author`、`scope`、`note`、`sourceType`、`status`（`prototype` 或 `reading-guide`）、`representativeSpineId`；本机 PDF 可另给绝对路径 `sourcePdf`。
- `presentation`：`overviewTitle/overviewIntro/representativeLabel/representativeTitle/representativeIntro/representativeScope/sectionHeading`；`sectionEvidence` 为 `material` 或 `synthesis`；`sectionRelation` 为 `sequence` 或 `independent`，只有来源支持顺序时才选前者；`sectionSourceIds` 引用真实引文 ID。`detailHeading/takeawayHeading/eyebrow` 可选。当前内置模板固定标签为中文；其他语言需另存翻译模板，不能宣称自动双语。
- `spine[]`：`id/title/kicker/question/summary/relation/chapterRefs/sourceIds`，`evidence: synthesis`。这是编辑的阅读路线，不限定节点配额；`chapterRefs` 可用真实章号或实际标题。
- `sections[]`：`id/title/short/question/explanation/distinction/details/sourceIds/evidence`；`details` 为 `{name,text}`，对应概念、要素或参与者，不固定为某专业器官。可选 `example: {title,text,sourceIds,evidence}`；材料没有例子时省略，不能为模板编造。
- `keyDistinction`、`readingNotes[]`：`title/text/sourceIds/evidence`。章节分层与归纳关系使用 `synthesis`，忠实转述使用 `material`。
- `chapters[]`：`number/title/group`（原目录到导读节点 ID 的多值对应），非章号结构可另给 `label`。
- `quotes[]`：`id/text/locator/chapter`，可带连续原文 `context`；PDF 可带真实 `page`。与已有提取映射机械核对时另给 `sourceBlockId`。
- `synthesisNote`：简述哪些结构由本页重组、已核范围和关键缺口。

可选传 `--source-map KB/source_map.json --full-text KB/full_text.txt`，检查引用是否为相应原文的连续片段及 PDF 页码。缺少这两个输入时报告 `quoteCheck: not-run`；即使通过，也不能替代模型核查解释与原文的支持关系。脚本产出 HTML 与 `.render.json`，不授予全量覆盖或语义完成状态。

## 6. 检查与交付

导读交付只需离线 HTML、其内容源，以及简要来源核查和计时记录。原文资料可保留在已有工作目录；不为样板预建完整术语表、题库、规范方法文件或系统账本。不要创建空审核文件或伪造全量阅读状态来迎合旧检查。

核查页面实际展示的主张、区别、例子、节点与关系，记录来源范围和具体缺口。检查主线的主次、默认解释能否读懂、原书／归纳标签、原目录对照、展开与出处交互，并在可用浏览器中查看桌面与窄屏；未运行的检查如实记录。

计时区分提取、结构与样板、扩展、复核和界面修订；工具等待与未知区间不冒充计算时间。报告本次实际范围与耗时，不把复用旧底库的样板速度当成新整书速度，不承诺固定分钟数或提速百分比。

独立导读只声明已读、已核与已展示的范围。继续完整单书拆解时按 `author-led-book-workflow.md`，复用主线、代表章节和来源，再补齐全书内容；用户要求升级为 systematic 时补齐其原有契约。导读完成不自动获得全书完成或全量覆盖状态。


## 首页原书封面

书籍网页默认在首页标题旁展示可靠的原书封面。先实际查看上传PDF封面页或用户提供的图片，确认是本书封面；不得仅因是PDF第1页就直接认定，也不联网找图或生成替代封面。没有可确认封面时省略，保持原布局，不中断正文生成。

从已提取图片复用，或将已确认的封面页渲染为本地PNG/JPEG/WebP。构建作者主线网页与导读时可传 `--cover-image /path/to/cover.png --cover-page 1`；页码必须是实际物理PDF页，非PDF图片省略页码。图片以data URL嵌入，不依赖远程加载，保持完整比例，窄屏缩小。`meta.cover`为可选展示字段，包含`dataUrl/sha256/alt/sourcePage/sourceLabel`，不改变书籍、章节、单元、主张及来源ID。旧内容无此字段仍正常渲染。

纯封面更新复用正文与来源，不重新拆解书籍；检查桌面/窄屏封面、主线、出处与无封面回退。封面是书籍身份展示，不是为内容新增证据或语义审核。
