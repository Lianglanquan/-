# Master Implementation Prompt

你是一名资深产品设计师和 React 工程师。请在 `/data/心理_厚璨杯` 中改造现有心理评估前端。

## 先读这些材料

- `prompts/framesbase/design-reference-library.md`
- `prompts/framesbase/references.json`
- `docs/PRODUCT.md`
- `docs/PSYCHOLOGY_MODEL.md`
- `docs/SAFETY.md`

## 产品目标

这是一个半结构化自杀意念语句智能评估研究工具。参与者看到 20 道固定开放题，自由作答；系统用专家 Rubric 进行 0/1/2 初步评分，同时独立判断证据是否充分。信息不足时，系统只能针对明确的语义缺口提出一个中性澄清问题。安全状态必须独立于普通评分，并在命中安全规则后停止自由生成追问。

## 视觉方向

把多个 Framesbase 参考组合成一个温和、可信、非后台感的作答体验：

- 首屏借鉴 `Mindful Companion`：雾紫和淡蓝的安静氛围、中心化大标题、宽松留白、柔和白色内容卡。
- 回答区借鉴 `Inner Quest`：一次只突出一道题，让被试的原话成为画面中心。
- 澄清区借鉴 `Routine Coach`：像一张轻量的下一步卡片，明确显示缺失信息，但不提供暗示性选项。
- Evidence Map 借鉴 `Breathstone`：米白画布、编辑式分段、证据引用和 Rubric 规则清楚可重放。
- 完成页借鉴 `Celestial Renewal` 与 `Nature Ritual`：使用地平线或自然意象表达继续向前，但不要把任何分数渲染成戏剧化结论。

## 必须保留

- 真实 API 评分、`CONFIRMED / PROVISIONAL`、`SUFFICIENT / INSUFFICIENT`、证据片段、理由、置信度和安全转交状态。
- 20 道题的切换和进度；移动端不能出现横向溢出或遮挡。
- Evidence Map、Research Dashboard、Expert Review、Case Replay 入口。
- 研究入口可以低调，但不能删除。
- 所有文本、按钮和安全提示符合可读性和可访问性要求。

## 实现约束

- 使用现有 React/Vite 结构，不重写后端，不把 API key 放进前端。
- 优先复用 `public/framesbase/` 中的本地预览图，不依赖 Framesbase 登录状态或远程热链。
- 不复制 Framesbase 的品牌、Logo、原站文案或完整页面结构。
- 不使用负的 `letter-spacing`，不让大标题压住回答输入框。
- 安全状态使用稳定、高对比的固定提示；命中后不继续生成开放式追问。
- 修改后运行 `npm run build`，并在桌面和窄屏各检查一次。

## 交付标准

完成后，默认第一屏应该像一个温和的自我探索空间，而不是研究后台；研究人员仍能通过次级入口查看完整证据链和实验数据。说明你使用了哪些参考、哪些只作为灵感没有照搬，并列出验证命令结果。
