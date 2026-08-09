# 开源 H3-Base：Ref2VA 全能参考格式

来源：https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/docs/VIDEO_PROMPT_WRITING_GUIDE_ref_en.md

## 目录

- [六段式结构](#六段式结构)
- [参考标签](#参考标签)
- [summary](#summary)
- [retention_analysis](#retention_analysis)
- [detailed_description](#detailed_description)
- [音频和对白](#音频和对白)

## 六段式结构

以下六段严格按顺序输出，并全部使用英文；只有对白、歌词和画面可见文字保留原语言：

```text
subject_definitions:
...

summary:
...

retention_analysis:
...

detailed_description:
...

overall_soundscape:
...

non_diegetic_music:
...
```

## 参考标签

- `<Subject N>`：目标视频中实际复用或修改的可见内容，如人物、动物、物体、环境、服装、道具、界面、特效、风格、动作、表情或姿势。
- `<Picture N>`：图片本身是具体首帧、关键帧、尾帧、编辑关键帧、构图锚点或分镜规划图时使用。
- `<Video N>`：源视频编辑、视频延续、整体运镜、切镜、节奏或时序结构。
- `<Audio N>`：独立音频或明确启用的参考视频同步音轨，用于复制或参考音色、音乐、对白、歌词、节奏和音效。

重要规则：

- 标签一旦分配，在全部六段中保持同一含义。
- 一张素材可以定义多个 Subject；一个 Subject 可以综合多份素材。
- 图片只用于定义人物、场景、服装或风格时，不单独建立 `<Picture N>` 行；在 `<Subject N>` 定义中注明来源图片。
- 视频中的人物、物体、动作或场景作为可见内容复用时仍定义成 `<Subject N>`；`<Video N>` 只标记文件或整体结构关系。
- 普通带声音视频不会自动产生 `<Audio N>`；只有声音轨明确被使用时才定义。
- `<Video N>` 与 `<Audio N>` 各自独立编号，不要求索引相同。

定义示例：

```text
subject_definitions:
<Subject 1> is the woman whose appearance comes from <Picture 1> and whose walking motion comes from <Video 1>.
<Subject 2> is the red-walled living-room environment in <Picture 2>, including the tufted sofa and warm ceiling lights.
<Video 1> provides the target video's camera movement and action timing.
<Audio 1> is the voice-timbre reference for <Subject 1> (S1).
```

## summary

使用一个简短英文段落，开头放任务类型方括号。可组合：

- `keyframe completion`
- `reference generation`
- `video editing`
- `video continuation`
- `audio copy`
- `audio reuse`
- `audio reference`

不要在 summary 中引入 `subject_definitions` 未定义的新标签。视频编辑开头写：`The target video is an edited version of <Video 1>.`

## retention_analysis

每个被引用标签单独一行，说明出现位置、保留关系及具体内容。

视觉关系固定值：

- `fully_preserved`
- `partially_preserved`
- `attribute_transfer`
- `weak_reference`

音频关系固定值：

- `fully_copy`
- `partially_copy`
- `reference`
- `weak_reference`

```text
<Subject 1> (appears in [Shot 1], [Shot 2]): fully_preserved - the face, hairstyle, clothing colors, and accessories are retained.
<Video 1> (camera and action timing): weak_reference - only the temporal structure and camera path are followed.
<Audio 1>: reference - its vocal timbre guides (S1) without copying the original signal.
```

新增剧情、动作或背景不自动等于参考损失；关系标记只评价定义过的参考职责。

## detailed_description

- 先用一两句英文定义整体风格，再开始 `[Shot 1]`。
- 按目标视频播放顺序逐镜描述构图、人物位置、环境、灯光、动作、状态变化、运镜和当前声音。
- 在标签首次出现及其职责实际生效的位置插入 `<Subject N>`、`<Picture N>`、`<Video N>` 或 `<Audio N>`。
- 第一镜无时间戳；后续镜头使用 `[Shot N] At MM:SS.mmm, ...`。
- 发声参考主体写 `<Subject N> (Sx)`。
- 视频编辑写清保留什么、修改什么、何时改变；视频延续写清从源视频哪个结束状态继续。

## 音频和对白

- 对白写成 `<d>[Language] 原文</d>`，稳定复用 `(Sx)`。
- 参考音频直接复用对白、旁白或歌词时逐字保留；听不清写 `[unclear]`，不要猜。
- 只参考音色、节奏、情绪或语气时，不要把参考音频原对白带入目标视频。
- 直接复用背景音乐中的人声只是音频提示点、并非具体角色发声时，使用 `<Audio N>`，不要虚构 `(Sx)`。
- `overall_soundscape` 与 `non_diegetic_music` 遵循基础模式规则，不重复完整对白和歌词。
