# 开源 H3-Base：T2VA／I2VA／FL2VA／L2VA 格式

来源：https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/docs/VIDEO_PROMPT_WRITING_GUIDE_base_en.md

## 目录

- [固定结构](#固定结构)
- [关键帧对齐首行](#关键帧对齐首行)
- [时间线与运镜](#时间线与运镜)
- [说话人和对白](#说话人和对白)
- [声音字段](#声音字段)
- [检查表](#检查表)

## 固定结构

T2VA 没有关键帧指令，直接输出三个字段：

```text
integrated_multimodal_description: [Shot 1] ...

overall_soundscape: ...

non_diegetic_music: ...
```

I2VA、FL2VA、L2VA 先写固定关键帧对齐指令，空一行，再写相同三个字段。

`integrated_multimodal_description` 按播放顺序描述视觉风格、构图、主体、动作、镜头、对白、演唱和同步画内声音。

## 关键帧对齐首行

### I2VA：一张首帧

```text
For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.
```

正文先锚定图片中的风格、主体、构图、服装、色彩、物体和空间关系，再写动作启动、连续发展与结果。不要把图片重新描述成另一个场景。

### FL2VA：两张首尾帧

```text
How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot N) aligns with the S.SS-second mark of the target video.
```

将 `N` 替换为实际最后一个 Shot 编号，将 `S.SS` 替换为有效视频时长并严格保留两位小数，例如 `15.00`。优先用单镜头连续插值；只有用户明确要求多镜头时才切镜。正文重点描述两帧之间可观察的动作、姿态、物体、构图、场景与光线变化。

### L2VA：一张尾帧

```text
How the reference pictures align with the target video — <Picture 1> (from [Shot N]) aligns with the S.SS-second mark of the target video.
```

推断与用户意图兼容的较早状态，让人物、物体、镜头和场景逐步收敛到参考尾帧。不要默认尾帧属于 Shot 1。

## 时间线与运镜

- 第一镜只写 `[Shot 1]`，不写时间戳。
- 后续切镜写 `[Shot 2] At 00:03.500, the camera cuts to...`，时间严格递增且小于总时长。
- 切镜必须带来主体、空间、状态、视角或时间上的新信息；只改变距离或小角度时使用连续运镜。
- 常用运镜：`Zoom In/Out`、`Push In/Pull Out`、`Pan Left/Right`、`Truck Left/Right`、`Tilt Up/Down`、`Pedestal Up/Down`、`Arc Shot`、`Tracking Shot`、`Static Shot`、`Shake Slightly/Strongly`、`POV`、`Roll Clockwise/Counterclockwise`。
- 必要时补充 `with small/large amplitude` 与 `at slow/fast speed`，作为自然句子写进当前 Shot。

## 说话人和对白

- 只有发声主体分配 `(S1)`、`(S2)`；同一主体跨镜保持编号。
- 首次出现时写清年龄层、性别、音高、音色、语速、口音等有用特征。
- 识别短语、ID、动作和语气写在 `<d>` 外；`<d>` 内只放语言标签与用户原话。

```text
The young woman with a quiet, breathy voice (S1) says: <d>[Chinese] 我在下一站下车。</d>
```

- 画外音使用固定表达 `says in an off-screen voiceover`，并在对白后说明对应画面人物嘴唇保持完全闭合。
- 对白跨切镜时在两部分连接点使用 `<scenetrans>`，说明声音跨切点连续。
- 视频结尾截断发言时使用 `<cutoff>`。
- 画面可见文字用英文双引号包住原文，不翻译、不改写。

## 声音字段

`overall_soundscape` 使用 1–4 句英文连续段落，总结环境声、物理动作声和非语言人声。不要重复正文里的对白、演唱与画内音乐。只有用户明确要求全片完全静音时才写 `N/A`。

`non_diegetic_music` 使用 1–3 句英文描述观众专属背景音乐，重点写乐器、速度、节奏与动态变化。角色能听见的手机、广播、电视、演唱或乐器属于画内事件，写进正文。没有观众专属配乐时写 `N/A`。

## 检查表

- 结构正文为英文；仅对白、歌词和画面文字保留原语言。
- 关键帧指令位于第一行，后有一个空行。
- 结束时间保留两位小数；切镜时间使用三位毫秒。
- 第一镜无时间戳，后续镜头编号和时间严格递增。
- I2VA 从图片向后发展；L2VA 向图片收敛；FL2VA 描述中间路径。
- 声音没有重复放错字段。
