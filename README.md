# ComfyUI H3 Prompt Director / ComfyUI H3 提示词导演

A ComfyUI node that turns **up to 5 reference images + 1 reference video +
a one-line goal** into a ready-to-use **H3 video prompt** by delegating to
the Hermes API. The receiving Hermes agent is told to activate the
`h3-video-prompt-director` skill (or whichever skill name you pass) and
returns the final prompt.

一个 ComfyUI 节点，把最多 5 张参考图 + 1 段参考视频 + 一句话目标，交给
Hermes API 生成可直接使用的 H3 视频提示词。Hermes 端会自动激活
`h3-video-prompt-director` 技能（技能名可在节点上自定义），返回最终提示词。

---

## Features / 功能

- **Up to 5 reference images** (ComfyUI `IMAGE` type) — characters, scenes,
  styles, key frames, anything.
- **1 reference video** (ComfyUI `IMAGE` batch — the standard ComfyUI
  convention where video loaders emit a per-frame float tensor). The
  node re-encodes the frame batch to a real mp4 on disk so the receiving
  agent can read it.
- **Configurable video FPS** — required because the IMAGE batch carries
  no timing metadata.
- **Customizable goal** describing what the user wants in plain Chinese
  or English.
- **Configurable skill name** — point the receiving agent at any
  Hermes skill; default `h3-video-prompt-director`.
- **Optional output language** — `english` (default, ComfyUI/H3-Base
  executable), `chinese`, or `both`.
- **Optional temp-file retention** for debugging.
- **Optional prompt cache** — when `enable_cache=True`, identical inputs
  return the previous `prompt` without calling Hermes.
- **Timeout up to 24 hours** for very long video-analysis jobs.

---

- **最多 5 张参考图**（ComfyUI `IMAGE` 类型）—— 人物、场景、风格、关键帧等。
- **1 段参考视频**（ComfyUI `IMAGE` batch —— ComfyUI 视频加载器输出的标准
  形态：每帧一个 float tensor）。节点自动把帧 batch 重编码成 mp4，让
  接收端 agent 直接读。
- **可配置视频帧率（FPS）** —— IMAGE batch 不带时间元信息，必须告诉节点。
- **可自定义目标** —— 中文 / 英文，自然语言描述。
- **可自定义技能名** —— 告诉 Hermes 激活哪个技能，默认 `h3-video-prompt-director`。
- **可指定输出语言** —— `english`（默认，ComfyUI / H3-Base 可执行版本）、
  `chinese`、`both`。
- **可选保留临时文件** —— 调试用。
- **可选 prompt 缓存** —— `enable_cache=True` 时，相同输入直接返回上次 `prompt`，不调 Hermes。
- **超时最大 24 小时** —— 应对超长视频分析任务。

---

## Install / 安装

Drop the `ComfyUI-H3PromptDirector/` directory into your ComfyUI
`custom_nodes/` folder and restart ComfyUI. No extra Python deps
required (both `urllib` and the stdlib are enough).

把 `ComfyUI-H3PromptDirector/` 目录放到 ComfyUI 的 `custom_nodes/` 下，
重启 ComfyUI。无需额外 Python 依赖（`urllib` + 标准库即够）。

```bash
cd /path/to/ComfyUI/custom_nodes/
git clone https://github.com/YOUR_USERNAME/ComfyUI-H3PromptDirector.git
# then restart ComfyUI (or `systemctl restart comfyui` on systemd)
```

---

## Inputs / 输入

| Slot | Type | Required | Default | Notes |
|------|------|----------|---------|-------|
| `image_1` | IMAGE | ✓ | — | 1st reference image |
| `image_2` … `image_5` | IMAGE | optional | `None` | additional references |
| `reference_video` | IMAGE | ✓ | — | the standard per-frame batch from VHS / VRGDG / etc. |
| `video_fps` | FLOAT | ✓ | 24.0 | frames per second of the reference video |
| `goal` | STRING | ✓ | (Chinese example) | what the user wants |
| `skill_name` | STRING | ✓ | `h3-video-prompt-director` | the Hermes skill to activate |
| `api_url` | STRING | optional | `http://192.168.3.78:8642` | Hermes API base URL |
| `api_key` | STRING | optional | `hermes-openwebui-secret-2025` | (you should change this) |
| `model` | STRING | optional | `MiniMax-M3` | model name passed to Hermes |
| `output_language` | enum | optional | `english` | `english` / `chinese` / `both` |
| `keep_temp_files` | BOOLEAN | optional | `False` | retain `/tmp/h3-prompt-director/<uuid>/` for debugging |
| `enable_cache` | BOOLEAN | optional | `False` | when `True`, identical inputs return the previous `prompt` without calling Hermes |
| `cache_dir` | STRING | optional | `/tmp/h3-prompt-director/cache` | where cache entries live; pick a persistent path if you want them across reboots |
| `timeout` | INT | optional | 300 | seconds, max 86400 (24h) |

| 槽 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `image_1` | IMAGE | ✓ | — | 第 1 张参考图 |
| `image_2` … `image_5` | IMAGE | optional | `None` | 额外参考图 |
| `reference_video` | IMAGE | ✓ | — | VHS / VRGDG 等加载器输出的逐帧 batch |
| `video_fps` | FLOAT | ✓ | 24.0 | 参考视频帧率 |
| `goal` | STRING | ✓ | （中文示例） | 用户目标 |
| `skill_name` | STRING | ✓ | `h3-video-prompt-director` | Hermes 端要激活的技能名 |
| `api_url` | STRING | optional | `http://192.168.3.78:8642` | Hermes API base URL |
| `api_key` | STRING | optional | `hermes-openwebui-secret-2025` | （建议改） |
| `model` | STRING | optional | `MiniMax-M3` | 传给 Hermes 的模型名 |
| `output_language` | enum | optional | `english` | `english` / `chinese` / `both` |
| `keep_temp_files` | BOOLEAN | optional | `False` | 保留 `/tmp/h3-prompt-director/<uuid>/` 调试用 |
| `enable_cache` | BOOLEAN | optional | `False` | `True` 时，相同输入直接返回上次 `prompt`，不调用 Hermes |
| `cache_dir` | STRING | optional | `/tmp/h3-prompt-director/cache` | 缓存目录；若想跨重启保留，改成持久路径（如 `~/.cache/h3-prompt-director/`） |
| `timeout` | INT | optional | 300 | 秒， 上限 86400（24h） |

---

## Outputs / 输出

| Slot | Type | Notes |
|------|------|-------|
| `prompt` | STRING | the final H3 prompt (cleaned) — pipe into your text-encode node |
| `raw` | STRING | the unmodified Hermes response, for debugging |
| `temp_dir` | STRING | absolute path of the working directory; empty string after cleanup |

| 槽 | 类型 | 说明 |
|---|---|---|
| `prompt` | STRING | 最终 H3 提示词（已清理），接到文本编码节点 |
| `raw` | STRING | Hermes 原始响应，调试用 |
| `temp_dir` | STRING | 工作目录绝对路径，清理后为空字符串 |

---

## Why does the node re-encode image/video tensors to temporary files? /
为什么要把 tensor / video 帧落盘？

ComfyUI's `IMAGE` type is a torch tensor — no path on disk. The Hermes
API 8642 only accepts `image_url` (still image) + text content parts; it
does **not** accept `video_url`. So video frames must be re-encoded into
a real mp4 file that the receiving Hermes agent can read off the same
host. Re-encoding also gives Hermes a single canonical file path it can
latch onto for frame timing / motion analysis.

ComfyUI 的 `IMAGE` 类型是 torch tensor —— 没有磁盘路径。Hermes API 8642
只接受 `image_url`（静态图）+ text 内容，不接受 `video_url`。所以视频帧
必须重编码成真 mp4 文件，让接收端 Hermes agent 直接读。重编码也让 Hermes
拿到一个统一的文件路径，方便做帧时序 / 动作分析。

### File layout / 文件结构

```
/tmp/h3-prompt-director/<uuid>/
├── img_1.png      ← image_1 tensor
├── img_2.png      ← image_2 tensor (if provided)
├── img_3.png      ← image_3 tensor (if provided)
├── img_4.png      ← image_4 tensor (if provided)
├── img_5.png      ← image_5 tensor (if provided)
└── reference.mp4  ← video batch re-encoded at the user-specified fps
```

Set `keep_temp_files=True` to retain this directory after the call
(defaults to `False`, the directory is rm-rf'd on exit).

设置 `keep_temp_files=True` 保留这个目录（默认 `False`，调用后自动删除）。

---

## Hermes Configuration / Hermes 配置

This node requires a Hermes API server reachable over HTTP. Quick setup:

本节点需要 Hermes API server（HTTP 可达）。快速配置：

### 1. 启用 API Server / Enable the API Server

In Hermes's main config (e.g. `~/.hermes/config.yaml` or via env vars),
set:

在 Hermes 主配置（如 `~/.hermes/config.yaml` 或环境变量）里设置：

```yaml
api_server:
  enabled: true
  host: 0.0.0.0
  port: 8642
```

Or via environment variables / 或通过环境变量：

```bash
export API_SERVER_ENABLED=true
export API_SERVER_HOST=0.0.0.0
export API_SERVER_PORT=8642
```

### 2. 配置 API Key / Configure an API Key

Set a strong key (≥ 16 characters). **Be sure to change the default
`hermes-openwebui-secret-2025`** in the node's `api_key` field to match:

设置一个强 key（≥ 16 字符）。**记得把节点的 `api_key` 默认值
`hermes-openwebui-secret-2025` 改成实际配置的**：

```yaml
api_server:
  enabled: true
  host: 0.0.0.0
  port: 8642
  key: "your-strong-secret-key-here-min-16-chars"
```

```bash
export API_SERVER_KEY="your-strong-secret-key-here-min-16-chars"
```

### 3. 安装 H3 提示词 Skill / Install the H3 Prompt Skill

The receiving Hermes agent must have the `h3-video-prompt-director` skill
available. The skill is bundled in this repo under
`h3-video-prompt-director-skill/`. Install it into Hermes's skills
directory:

Hermes 端必须有 `h3-video-prompt-director` 技能可用。该技能随本 repo
附带，在 `h3-video-prompt-director-skill/`。安装到 Hermes 的 skills 目录：

```bash
# default location depends on your Hermes install, e.g.:
cp -r ComfyUI-H3PromptDirector/h3-video-prompt-director-skill \
      ~/.hermes/skills/video/h3-video-prompt-director
```

Or via Hermes's CLI (if you have one):

或通过 Hermes CLI（如果可用）：

```bash
hermes skills install ./h3-video-prompt-director-skill
```

#### ⚠️ Skill source disclosure / 技能来源声明

The bundled `h3-video-prompt-director-skill/` is **not authored by the
node publisher** — it was collected from the public network / a
third-party source. We bundle it here only for convenience so users
get a working setup without a separate download step. See the upstream
project page for the canonical source and any license terms.

打包的 `h3-video-prompt-director-skill/` **不是节点作者自己写的**——
来自网络收集 / 第三方来源。本仓库附带它只是方便用户一次性拿到能跑的
环境。请到上游项目页确认原始来源和许可。

---

## Verification / 验证

After configuration, verify the node shows up in ComfyUI:

配置完成后，验证节点出现在 ComfyUI：

```bash
curl -s http://localhost:8188/object_info | python3 -c "
import json, sys
n = json.load(sys.stdin).get('H3PromptDirector')
assert n, 'node NOT registered'
print('OK:', n['input']['required'].keys())
"
```

A minimal smoke test (with a real image and video file):

最小烟雾测试（用真实图像和视频）：

```python
# POST /prompt to ComfyUI
import json, urllib.request, uuid
COMFYUI = "http://localhost:8188"
workflow = {
    "1": {"class_type": "LoadImage", "inputs": {"image": "your-image.png"}},
    "2": {"class_type": "VHS_LoadVideoPath", "inputs": {
        "video": "/abs/path/to/your-video.mp4",
        "force_rate": 0, "custom_width": 0, "custom_height": 0,
        "frame_load_cap": 0, "skip_first_frames": 0, "select_every_nth": 1,
    }},
    "3": {"class_type": "H3PromptDirector", "inputs": {
        "image_1": ["1", 0],
        "reference_video": ["2", 0],
        "video_fps": 30.0,
        "goal": "让图1的角色模仿参考视频的角色跳舞，保留图1的场景。",
        "skill_name": "h3-video-prompt-director",
    }},
    "4": {"class_type": "SaveText", "inputs": {
        "text": ["3", 0], "filename_prefix": "h3_prompt", "format": "md",
    }},
    "5": {"class_type": "SaveText", "inputs": {
        "text": ["3", 1], "filename_prefix": "h3_raw", "format": "md",
    }},
    "6": {"class_type": "SaveText", "inputs": {
        "text": ["3", 2], "filename_prefix": "h3_tempdir", "format": "txt",
    }},
}
body = {"prompt": workflow, "client_id": "test-" + uuid.uuid4().hex[:8]}
req = urllib.request.Request(
    f"{COMFYUI}/prompt", data=json.dumps(body).encode(),
    headers={"Content-Type": "application/json"}, method="POST")
print(json.loads(urllib.request.urlopen(req, timeout=30).read())["prompt_id"])
```

Then poll `/history/<prompt_id>` until `status.completed == True`. Expected
output: a non-empty `prompt` (typically 5–10 KB of English H3 prompt).

然后轮询 `/history/<prompt_id>`，直到 `status.completed == True`。
预期输出：一个非空的 `prompt`（通常 5–10 KB 英文 H3 提示词）。

---

## Components / 项目结构

```
ComfyUI-H3PromptDirector/
├── __init__.py                      ← ComfyUI registration entry
├── nodes.py                          ← the node itself
├── README.md                         ← this file (中英双语)
├── LICENSE                           ← MIT
├── h3-video-prompt-director-skill/   ← bundled Hermes skill (NOT authored by us)
│   ├── SKILL.md
│   ├── agents/
│   │   └── openai.yaml
│   └── references/
│       ├── base-context-ir.md
│       ├── model-routing-and-limits.md
│       ├── prompt-patterns.md
│       ├── ref-context-ir.md
│       └── webapp-natural-language.md
└── .gitignore
```

---

## License / 许可

- The node code (`__init__.py`, `nodes.py`, `README.md`, `LICENSE`) is
  released under **MIT**.
  节点代码（`__init__.py`、`nodes.py`、`README.md`、`LICENSE`）采用 **MIT** 许可。
- The bundled `h3-video-prompt-director-skill/` is **third-party** —
  collected from the public network. See the upstream project for its
  own license terms.
  打包的 `h3-video-prompt-director-skill/` 是**第三方内容** —— 来自网络收集。
  请到上游项目查看其许可。

---

## Caching / 缓存

When `enable_cache=True`, the node records each successful Hermes response
under a SHA-256 key derived from **all** inputs that affect the result:

- a SHA-256 of every image file's bytes
- a SHA-256 of the encoded video file's bytes
- `video_fps`, `goal`, `skill_name`, `api_url`, `api_key`, `model`, `output_language`

On subsequent runs with byte-identical inputs (and the same `api_url` /
`api_key` / `model` / `output_language`), the cached `prompt` and
`raw` are returned **without contacting Hermes**. Cache writes are atomic
(`*.json.tmp` + rename) and the directory is LRU-trimmed to the most
recent 100 entries.

> ⚠️ Defaults to `False`. Set `enable_cache=True` and (optionally) point
> `cache_dir` at a persistent location like `~/.cache/h3-prompt-director/`
> if you want the cache to survive reboots — `/tmp/...` is wiped by the
> OS on most Linux distributions.

打开 `enable_cache` 后，节点会用 SHA-256 缓存函数返回 prompt 和 raw。
缓存键覆盖所有影响结果的输入：每张图片、整个视频文件、fps、goal、
skill_name、api_url、api_key、model、output_language。下次相同输入
完全一致时直接读缓存，不发 API 请求。写入用 `tmp + rename` 原子写，
按 LRU 最多保留 100 条。

> ⚠️ 默认 `False`。如需跨重启保留，**设置 `cache_dir` 为持久路径**
> （如 `~/.cache/h3-prompt-director/`），因为默认 `/tmp/...` 会被
> 系统清理。

---

## Troubleshooting / 故障排查

| Symptom | Likely cause | Fix |
|---|---|---|
| `prompt` output is just a short preamble (e.g. "Now let me deliver the prompt.") | Underlying vLLM truncated the final assistant turn (transient) | Re-run the workflow; the node will re-execute since the call is non-deterministic |
| `401 Invalid API key` | `api_key` doesn't match `API_SERVER_KEY` on Hermes | Update the node's `api_key` input |
| `Connection refused` to `192.168.3.78:8642` | Hermes API server not enabled / wrong host | Update the node's `api_url` input; verify with `curl http://<host>:8642/health` |
| `unsupported content_type` | Hermes API rejected — should not happen, only `image_url` + text are sent | Check Hermes server logs |
| `keep_temp_files` output is empty | Cleanup ran (default `False`) | Toggle `keep_temp_files=True` to inspect `/tmp/h3-prompt-director/<uuid>/` |
| Cache HIT but `prompt` is stale | You changed some upstream node (e.g. model, sampler) but the input bytes are still the same | Disable `enable_cache` to force a fresh call, or change `goal` to bust the cache key |

| 现象 | 可能原因 | 修复 |
|---|---|---|
| `prompt` 输出只是一小段前言（如 "Now let me deliver the prompt."） | 底层 vLLM 把最后一个 assistant 回合截断了（瞬时） | 重跑工作流；调用本身非确定性 |
| `401 Invalid API key` | `api_key` 与 Hermes 端 `API_SERVER_KEY` 不匹配 | 改节点的 `api_key` 输入 |
| 连接 `192.168.3.78:8642` 拒绝 | Hermes API server 未启用 / 主机错 | 改 `api_url` 输入；用 `curl http://<host>:8642/health` 验证 |
| `unsupported content_type` | Hermes API 拒绝 —— 节点只发 `image_url` + text | 检查 Hermes 服务日志 |
| `keep_temp_files` 输出为空 | 清理已跑（默认 `False`） | 设 `keep_temp_files=True` 查看 `/tmp/h3-prompt-director/<uuid>/` |
| Cache HIT 但 `prompt` 旧 | 上游节点（如模型、采样器）换了，但输入字节相同 | 关闭 `enable_cache` 强制重发，或改 `goal` 让 cache key 失效 |
