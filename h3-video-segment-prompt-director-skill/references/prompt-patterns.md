# H3 成品模板

所有方括号内容必须替换或删除。默认使用开源 H3-Base 英文格式。

每次交付最终提示词时必须输出两份语义完全对应的成品：先给英文版，再给中文对照版。保持素材标签、Shot 编号、时间点、对白原文和声音结构一致；中文版不得成为另一个创意变体。本地 H3-Base／ComfyUI 只复制英文版，中文版仅供理解；海螺网页端使用中文版，英文版仅供对照。

## T2VA

```text
integrated_multimodal_description: [Shot 1] [Style], [initial shot size and composition]. [Subject appearance, position, environment, action, camera movement, dialogue and synchronized diegetic sound]. [Shot 2] At 00:SS.mmm, the camera cuts to [new information, continuing subject/action, camera and sound].

overall_soundscape: [1–4 English sentences covering ambience, physical action sounds and non-verbal human sounds].

non_diegetic_music: [1–3 English sentences covering instruments, tempo, rhythm and dynamics, or N/A].
```

## I2VA

```text
For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.

integrated_multimodal_description: [Shot 1] [Style]. The subject, clothing, colors, key objects, composition and spatial relationships established in <Picture 1> remain consistent. [Action begins, develops continuously, and reaches a result; camera and synchronized sound].

overall_soundscape: [Soundscape].

non_diegetic_music: [Music or N/A].
```

## L2VA

```text
How the reference pictures align with the target video — <Picture 1> (from [Shot N]) aligns with the S.SS-second mark of the target video.

integrated_multimodal_description: [Shot 1] [Plausible earlier state compatible with the intended final frame]. [Observable action, object, camera, lighting and composition changes]. [Final Shot] At MM:SS.mmm, [the remaining differences narrow until the exact subject state, camera angle, lighting and composition established by <Picture 1> are reached at the end].

overall_soundscape: [Soundscape].

non_diegetic_music: [Music or N/A].
```

## FL2VA

```text
How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot N) aligns with the S.SS-second mark of the target video.

integrated_multimodal_description: [Shot 1] [Style]. The video begins in the subject state and composition established by Picture 1. [Describe the continuous motion path, pose changes, object manipulation, camera, lighting and sound]. [If multiple shots were explicitly requested, add later shots with exact cut times.] By the end, the subject settles into the final state, spacing, camera angle, lighting and composition established by Picture 2.

overall_soundscape: [Soundscape].

non_diegetic_music: [Music or N/A].
```

## Ref2VA

```text
subject_definitions:
<Subject 1> is [reusable visible content and source assets].
<Video 1> is [source-video or temporal-structure role, only if applicable].
<Audio 1> is [copy/reference role, only if applicable].

summary:
[task type] [One short paragraph using only defined labels].

retention_analysis:
<Subject 1> (appears in [Shot ...]): [fully_preserved/partially_preserved/attribute_transfer/weak_reference] - [specific retained relationship].
<Video 1> ([role]): [relationship] - [specific relationship].
<Audio 1>: [fully_copy/partially_copy/reference/weak_reference] - [specific relationship].

detailed_description:
[One or two English sentences defining the overall style.]
[Shot 1] [Composition, subject appearance and position, environment, lighting, action, state change, camera, sound and reference labels where they apply].
[Shot 2] At 00:SS.mmm, [new information and continuity].

overall_soundscape: [Soundscape].

non_diegetic_music: [Music or N/A].
```

## 中文网页端

```text
参考素材说明：
@图片1用于[人物/场景/风格/首帧/尾帧]，保留[特征]；@视频1仅参考[动作/运镜/时序]；@音频1用于[音色/对白/音乐/节奏]。

核心创意：
[主体]在[地点]经历[事件]，整体呈现[视觉和类型风格]。

画面过程说明：
[沿时间线写景别、构图、动作、运镜、对白、环境声、音效和音乐变化]。
```

## 快速检查

- 开头元信息已告知模型权重、任务模式和提示词格式。
- 素材映射没有把 Subject 与关键帧 Picture 混淆。
- 结构正文为英文；对白、歌词与画面文字保留原语言。
- 关键帧首行、空行、时间精度与 Shot 语法正确。
- 对白使用稳定 `(Sx)` 和 `<d>[Language] ...</d>`。
- 画内声、整体声景和非叙事配乐没有混放。
- 已分别输出完整英文版与完整中文对照版，两版语义和时间线逐项一致。
- 已明确标注实际应复制的版本，避免把中英文两版同时输入本地 H3-Base。
