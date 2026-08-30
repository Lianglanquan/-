# Framesbase 设计参考素材库

本目录把已在 Framesbase 中看到的多组设计，整理成可复用的视觉方向。它不是把心理评估做成 Framesbase 的复制品，而是把不同页面中适合本项目的设计语言拆出来组合。

## 参考来源

- 站点：<https://app.framesbase.app/>
- 访问日期：2026-08-30
- 访问方式：用户已登录的 Chrome 会话
- 本地预览图：`public/framesbase/`
- 结构化索引：`prompts/framesbase/references.json`

## 组合方案

| 产品区域 | 主要参考 | 搭配参考 | 要拿走的创意 |
| --- | --- | --- | --- |
| 首屏 / 第一题 | Mindful Companion | Inner Quest | 雾紫氛围、中心化大标题、留白、单一行动 |
| 20 题进度 | Inner Quest | Routine Coach | 简化导航、轻量步骤卡、不要像问卷后台 |
| 回答输入 | Mindful Companion | Breathstone | 柔和白卡、慢节奏、文字优先、温暖米白 |
| 澄清追问 | Routine Coach | Mindful Companion | 一次只问一个缺口，使用支持性卡片，不给暗示答案 |
| Evidence Map | Breathstone | Inner Quest | 低刺激的编辑式分段，证据与规则清楚可查 |
| 完成 / 未来 | Celestial Renewal | Nature Ritual | 地平线、夜空、自然意象，但不把分数戏剧化 |
| 安全状态 | 无直接照搬 | Nature Ritual 的对比度 | 使用明确的安全色和人工转交说明，停止自由生成追问 |

## 不应该照搬的内容

- 不复制 Framesbase 的品牌名、Logo、原站文案或第三方站点名称。
- 不把自然图用作风险评分的装饰背景，避免削弱可读性和严肃性。
- 不用巨大动效、自动播放视频或视觉隐喻遮住题目、原文证据和安全提示。
- 不把 `0 / 1 / 2` 表现成临床风险等级；严重度与证据充分性仍然分开。
- 不把澄清问题做成聊天式无限滚动；每次只显示一个 `target_gap` 和一个最小必要问题。

## 交给 AI 的文件顺序

1. 先读本文件，理解各参考的职责。
2. 再读 `references.json`，取得素材路径和适配约束。
3. 最后执行 `master-implementation-prompt.md`，只修改本项目需要修改的前端文件。
