# 人工真值与失效分析（不冒充已完成验收）

本目录是**待人工补全**的离线评测工作区。模板不含虚构答案或“自动解决”的未来工作判定。原始 PDF 在 `../../../pdf/`，PDF 页码均为**物理页码，从 1 开始**。截图坐标采用 PDF 点（左上角原点）；不要把像素坐标直接填入 `gold_bbox`。

## 可复用的开源来源与选择

| 来源 | 用处 | 必须核实的适配问题 |
|---|---|---|
| [AllenAI QASPER（GitHub）](https://github.com/allenai/qasper) | 论文问答、标注证据和不可回答问题的外部对照 | 核对论文 PDF 与问题对应版本、数据许可、证据段落与本系统物理页的映射；不能直接把该数据集的标签当作本地 20 篇论文金标准 |
| [AllenAI SciFact（GitHub）](https://github.com/allenai/scifact) | 科学主张—证据、支持/反驳/无证据的检验思路 | 这是主张验证任务，不等同一般论文问答；确认具体版本、许可和页码映射 |
| [IBM DocLayNet（GitHub）](https://github.com/DS4SD/DocLayNet) | 布局/图像/表格框评测的外部候选 | 版面标注不等于本文 Figure 完整区域、LaTeX 或扫描公式的真值；使用前核对数据文件许可和类别定义 |
| [IBM PubLayNet（GitHub）](https://github.com/ibm-aur-nlp/PubLayNet) | 学术论文版式基准候选 | 图注、表体及多栏布局真值的标注定义可能与应用截图需求不同 |
| [im2markup（GitHub）](https://github.com/harvardnlp/im2markup) | 图像到 LaTeX 转写的基线/公开资源线索 | 通常是独立公式图像，不自动覆盖 PDF 式全文抽取；核查数据来源/许可和复杂符号 |
| [Kaggle 数据集检索入口](https://www.kaggle.com/datasets?search=scientific%20document%20layout) | 搜索镜像或替代基准 | Kaggle 镜像并不自动继承权威来源或再分发许可；**未自动下载或采用任何 Kaggle 镜像** |

来源仅供逐项核查；本工作区当前使用项目自带的 PDF 与 `graph20_report.json`，**不声称已导入这些外部数据集**。使用前核对各版本的许可、训练/测试划分、题目对应 PDF 版本；涉及商业模型时保留数据发送与费用记录。

## 开始使用（项目根目录 `research_agent_mvp`）

```powershell
python tests/human_eval.py init
python tests/human_eval.py review_ui
python tests/human_eval.py layout_preview
python tests/human_eval.py collect
python tests/human_eval.py score
python tests/human_eval/graph_machine_audit.py
```

`init` **不会覆盖已有人工答案**；图谱快照的文件/边/页/摘录变化时会拒绝复用旧标签。`collect` 只在至少一条问题已填 `answerable: true/false` 时，使用操作系统临时数据库逐篇导入源 PDF 并检索每篇 Top-3；扫描件 OCR 可能耗时，**不会调用收费模型，也不会污染文献库**。`layout_preview` 输出候选截图与全文页 PNG、`layout_predictions.json`；未匹配候选也保留整页供标“漏检”。`score` 只读取人工真值和本地预测，不调用模型、不会推测票据。

`graph_machine_audit.py` 是我启动的 Agent 产生的**只读预审**：它重新从源 PDF 的 References 起始页检查目标 arXiv ID/保守标题词组，仅覆盖 64 条算法预测边，不写入 `graph_labels.json`，也不改变人工真值。当前找到 35 条机器候选、29 条需人工复核；35 条仍必须打开 PDF 确认确实是 References 条目而非正文/附录或同名误匹配。316 条未预测组合没有被证明为“不引用”，因此仍不能计算召回率。

### 您需要补全的字段

1. **问答**：在本机打开 `review_qa.html` 填写、导出 JSON 覆盖 `qa_labels.json`，也可直接编辑 JSON 增补题目（类型 `fact/negative/cross_paper/layout/ocr`）。填 `answerable`、`gold_answer`（不能回答时写“无证据，不能确定”）、`gold_pages`（单篇 PDF 物理页）、可核对的 `gold_anchors`、`reviewer`。跨篇问题必须填写 `gold_pages_by_pdf`，例如 `{"a.pdf":[4],"b.pdf":[8]}`，两篇 Top-3 **都命中**才算跨篇覆盖；如果要评证据词组覆盖，也填 `gold_anchors_by_pdf`（每篇都必须填），缺任何一篇金标准则该项不计入分母。真正试用网站模型后，**复制原始模型答复**到 `model_answer` 并按 `correct/partial/incorrect/correct_refusal` 填 `answer_review`；未做模型请求不评回答正确率。可填 `evidence_location_review`；Top-3 页码/原文词组覆盖由 `collect` 自动计算，勿用单篇证据支持跨篇推断。
2. **引文图**：运行 `review_ui` 并在本机打开 `review_graph.html`；核查**所有 380 对非自引用有向组合**的源论文 References 是否真实引用目标论文，包括 64 条模型预测和未预测组合；将 `gold_cites_target` 标为 `true/false`，不确定保留 `null`，有引用时记录 `gold_reference_page`。`predicted_evidence_valid` 要单独检查模型给的那一页与摘录是否真的支持这条边。完成后按“导出”，把文件放回 `graph_labels.json` 并运行 `score`。未全部审核时只显示**已审核子集的临时精确率**，绝不报召回率；不借 PageRank 判断学术质量。自引用及此 20 篇以外的边**不在本基准范围**。

可先运行只读机器辅助检查（不会改写 `graph_labels.json`，也不能替代人工金标准）：

```powershell
python tests/human_eval/graph_machine_audit.py
```

它仅对 64 条算法预测边，在源 PDF 的 References 区查找目标 arXiv ID 或保守标题短语，输出 `graph_machine_audit_result.json`。直接 ID 命中仍需人工打开 PDF 确认；未命中不等于没有引用，OCR、排版或作者—年份制都可能造成漏检。未预测的 316 条组合以及所有金标准页码仍必须人工核验。
3. **图表/公式**：检查 `previews/*_full_page.png` 与 `*_candidate.png`，在 `layout_labels.json` 标真图表主体的 `gold_bbox`（`[x0,y0,x1,y1]`，PDF 点）、`crop_review=complete/partial/incorrect/missed`；若无候选也要留金标准框以记录漏检。公式逐个记录原 PDF 对照的 `gold_latex`（如有源 LaTeX）及 `formula_review=correct/partial/incorrect/missed`。目前输出的是**非 LaTeX 的文本候选**；无实际解码 LaTeX 时不得报告“准确恢复率”。新增多栏、扫描、多语言 PDF 可直接向模板追加条目。
4. **译文**：`translation_labels.json` 逐块填 `source_text`/`translation_text`，在 `glossary` 填术语对；人工填 `semantic_review`。程序按原有数值词法做数字保护核对、按字串测术语命中；无法证明语义正确。仅供应商返回 Token 且填对应实际计价时填写两类 tokens 与 USD/百万费率，输出估算费用；没有 usage 时保持 `null`。
5. **公式语义**：`formula_explanations.json` 按公式贴原式及真实模型解释，分别评 `input_review`、`transform_review`、`output_review`、`citation_review`（建议 `correct/partial/incorrect`），标失败类别，例如错变量、缺上下文、虚构数值、公式识别漏项。失败请求若返回 Token 也可登记用量，**费用是估算而非账单**。

## 结果口径

`results.json` 的分母为**有效且有人工标签**的样本数；没有标注则 `value: null`。图谱全量 380 对都核对后才计算完整召回率（64 个预测边全部审完后才计算完整精确率）；如需报告正式评测，建议双人盲标、冲突复核，并保留每个 PDF 版本/许可/失败样本和裁剪图。可选 QASPER/DocLayNet 等属于独立外部评测，不能和此本地 20 篇混算。
