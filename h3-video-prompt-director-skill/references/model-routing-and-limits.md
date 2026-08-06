# H3 模型路由与约束

核对日期：2026-08-04。

主要来源：

- https://huggingface.co/MiniMaxAI/MiniMax-H3
- https://huggingface.co/MiniMaxAI/MiniMax-H3/tree/main/docs
- 海螺官方使用手册：https://vrfi1sk8a0.feishu.cn/wiki/FIWjwgL33ipnkekzk30crmKUnIh

## 权重与任务

| 输入用途 | 权重 | 任务模式 |
|---|---|---|
| 纯文字 | FL2VA | T2VA |
| 一张首帧图 | FL2VA | I2VA |
| 一张尾帧图 | FL2VA | L2VA |
| 两张首尾帧图 | FL2VA | FL2VA |
| 图片、视频、音频承担参考职责 | Ref2VA | Ref2VA |
| 编辑或延续源视频 | Ref2VA | Ref2VA |

`T2VA`、`I2VA`、`L2VA`、`FL2VA` 是任务模式；本地开源检查点仍只有 H3-Base-FL2VA 与 H3-Base-Ref2VA 两类。ComfyUI 中的 T2V/R2V 是模板或工作流简称。

## 官方输入输出规格

- 输出时长：4–15 秒。
- 帧率：24 FPS。
- 音频：32 kHz 立体声。
- 画幅：支持 21:9、16:9、4:3、1:1、3:4、9:16 等。
- 本地 H3-Base：默认短边 768 像素。
- 2K：由 H3-Regenerate-2K 完成；该模块当前未随开源权重发布，可通过官方 API 验证完整工作流。
- Ref2VA 图片：最多 9 张。
- Ref2VA 视频：最多 3 段；每段 2–15 秒，总时长不超过 15 秒。
- Ref2VA 音频：最多 3 段；每段 2–15 秒，总时长不超过 15 秒；必须伴随图片或视频，不能单独输入。
- 混合素材：最多 12 个文件。

旧版网页手册中的文件大小、格式与提示词字符限制可能属于在线产品/API，而不一定等同于本地推理框架。只有用户询问上传限制时才引用，并标注适用场景。

## 部署格式选择

- 本地 H3-Base／ComfyUI／Hugging Face：使用官方英文 Context-IR。
- 海螺网页／App：使用中文自然语言三段式，并采用界面实际显示的 `@图片1` 等标签。
- 不确认部署场景时：若用户关注权重或工作流，默认本地；否则简短标注假设。
