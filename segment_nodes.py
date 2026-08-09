"""
ComfyUI H3 Segment Prompt Director
==================================

A sibling of `H3PromptDirector` for chunked multi-segment H3 video
generation. Use when the source reference video is longer than H3's
per-call length cap (≈ 10–15 seconds, model-dependent).

How it works:
  - You pre-split the source video into N clips with another node
    (e.g. VHS frame-skip + image slice). Pass up to 12 clips into
    `reference_video_1..12`.
  - Pass `segment_duration` so the skill knows each chunk's target
    length (last chunk may be shorter if the source doesn't divide
    evenly).
  - For segment i ≥ 2, pass the previous segment's last frame as
    `image_5` so the skill can lock the boundary transition.

The skill `h3-video-segment-prompt-director` (bundled under
`h3-video-segment-prompt-director-skill/`) generates one H3 prompt per
chunk. Each segment's prompt is returned in its own output slot
(`prompt_1..12`); unused slots are empty strings.

Outputs
-------
- prompt_1 .. prompt_12 (STRING) — final H3 prompt for each segment,
  English version. Wire each into the corresponding downstream H3
  invocation.
- raw (STRING) — concatenated raw Hermes responses for all segments
  (debugging only). Format:
      ===== SEGMENT 1 =====
      <raw response 1>
      ===== SEGMENT 2 =====
      <raw response 2>
      ...
- temp_dir (STRING) — absolute path of the working directory; empty
  string after cleanup.

Inputs
------
- reference_video_1 (IMAGE, required) — the first segment's video
  frames (ComfyUI IMAGE batch).
- reference_video_2 .. reference_video_12 (IMAGE, optional) — segments
  2..12. Empty / None slots terminate the segment list.
- segment_duration (FLOAT) — target length per segment in seconds.
  Default 10.0.
- goal (STRING) — overall goal for the multi-segment video.
- skill_name (STRING, default "h3-video-segment-prompt-director") —
  Hermes skill to invoke.
- image_1 .. image_4 (IMAGE, optional) — user references (character,
  scene, style, key frames).
- image_5 (IMAGE, optional, recommended for segments 2+) — boundary
  lock image. In a typical workflow this is the previous segment's
  last frame (auto-captured by your frame-fetch node).
- api_url / api_key / model / output_language / keep_temp_files /
  enable_cache / cache_dir / timeout — same as H3PromptDirector.

Why so many output slots / 为什么要这么多输出槽位:
- ComfyUI output slots must be statically defined (no dynamic-length
  outputs). 12 covers a 30-second source split into 2-second chunks;
  in practice 3–5 segments is the common case.
- Empty `prompt_N+1 .. 12` slots are simply ignored at the workflow
  end — wire the segments you actually generated.

Why no combined prompt / 为什么不输出拼好的 prompt:
- Downstream H3 invocations need separate prompts per segment. The
  caller wires `prompt_1` to segment 1's H3, `prompt_2` to segment 2,
  etc. — concatenating would break that contract.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import uuid

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_API_URL = "http://192.168.3.78:8642"
DEFAULT_API_KEY = "hermes-openwebui-secret-2025"
DEFAULT_MODEL = "MiniMax-M3"
DEFAULT_SKILL_NAME = "h3-video-segment-prompt-director"
DEFAULT_SEGMENT_DURATION = 10.0
MAX_SEGMENTS = 12  # max reference_video slots and prompt outputs

DEFAULT_VIDEO_FPS = 24.0
MAX_TIMEOUT = 86400  # 24 hours

DEFAULT_ENABLE_CACHE = False
DEFAULT_CACHE_DIR = "/tmp/h3-prompt-director/segment-cache"
CACHE_MAX_ENTRIES = 100

TEMP_ROOT = "/tmp/h3-prompt-director/segment"

DEFAULT_GOAL = (
    "将图1的角色迁移到参考视频里，保持动作一致；"
    "切分多段生成，每段约 {duration} 秒。"
)


# ---------------------------------------------------------------------------
# Helpers (mirrored from H3PromptDirector — could be extracted to a shared
# module later, kept duplicated for now to avoid cross-import in custom_nodes)
# ---------------------------------------------------------------------------


def _save_image_tensor(image, dest_path: str) -> str:
    """Save a ComfyUI IMAGE tensor to a PNG file. Mirrors H3PromptDirector."""
    if isinstance(image, str) and os.path.isfile(image):
        return image
    if isinstance(image, dict):
        for k in ("path", "filename", "filepath"):
            v = image.get(k)
            if isinstance(v, str) and os.path.isfile(v):
                return v
        raise ValueError(f"dict image has no usable path key: {list(image)}")

    if hasattr(image, "detach"):
        try:
            arr = image.detach().cpu().numpy()
        except Exception as e:
            raise ValueError(f"failed to convert torch tensor to numpy: {e}")
    elif hasattr(image, "__array__"):
        arr = image.__array__()
    elif hasattr(image, "shape") and hasattr(image, "dtype"):
        arr = image
    else:
        raise ValueError(
            f"unsupported image type: {type(image).__name__}; "
            "expected torch.Tensor / numpy.ndarray / path / dict"
        )

    import numpy as np
    if arr.ndim == 4:
        if arr.shape[0] != 1:
            raise ValueError(
                f"image tensor batch size = {arr.shape[0]}; "
                "this slot expects a single image (batch=1)."
            )
        arr = arr[0]
    elif arr.ndim != 3:
        raise ValueError(
            f"image tensor has unexpected shape {arr.shape}; "
            "expected [H, W, C] or [1, H, W, C]"
        )

    if arr.dtype.kind == "f":
        arr = np.clip(arr * 255.0, 0, 255).astype(np.uint8)
    elif arr.dtype != np.uint8:
        arr = arr.astype(np.uint8)

    from PIL import Image
    img = Image.fromarray(arr)
    img.save(dest_path, format="PNG")
    return dest_path


def _save_video_frames(video_tensor, dest_path: str, fps: float) -> str:
    """Encode a ComfyUI video frame batch [N, H, W, C] to mp4 via ffmpeg."""
    if hasattr(video_tensor, "detach"):
        try:
            arr = video_tensor.detach().cpu().numpy()
        except Exception as e:
            raise ValueError(f"failed to convert video tensor to numpy: {e}")
    elif hasattr(video_tensor, "__array__"):
        arr = video_tensor.__array__()
    elif hasattr(video_tensor, "shape") and hasattr(video_tensor, "dtype"):
        arr = video_tensor
    else:
        raise ValueError(
            f"unsupported video type: {type(video_tensor).__name__}"
        )

    if arr.ndim != 4:
        raise ValueError(
            f"video tensor has shape {arr.shape}; expected [N, H, W, C]"
        )

    n_frames, h, w, c = arr.shape
    if n_frames < 1:
        raise ValueError("video tensor has 0 frames")

    import numpy as np
    if arr.dtype.kind == "f":
        arr = np.clip(arr * 255.0, 0, 255).astype(np.uint8)
    elif arr.dtype != np.uint8:
        arr = arr.astype(np.uint8)

    if arr.shape[-1] == 4:
        arr = arr[..., :3]
    elif arr.shape[-1] == 1:
        arr = np.repeat(arr, 3, axis=-1)
    elif arr.shape[-1] not in (3,):
        raise ValueError(f"video has {arr.shape[-1]} channels; need 3 or 4")

    arr = np.ascontiguousarray(arr)
    fps = float(fps) if fps and fps > 0 else DEFAULT_VIDEO_FPS

    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "rawvideo",
        "-vcodec", "rawvideo",
        "-pix_fmt", "rgb24",
        "-s", f"{w}x{h}",
        "-r", f"{fps}",
        "-i", "pipe:0",
        "-an",
        "-vcodec", "libx264",
        "-pix_fmt", "yuv420p",
        "-crf", "18",
        "-preset", "veryfast",
        "-movflags", "+faststart",
        dest_path,
    ]
    proc = subprocess.run(
        cmd, input=arr.tobytes(),
        capture_output=True,
        timeout=300,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed (rc={proc.returncode}) encoding video: "
            f"{proc.stderr.decode('utf-8', errors='replace')[:500]}"
        )
    return dest_path


def _make_temp_dir() -> str:
    os.makedirs(TEMP_ROOT, exist_ok=True)
    d = os.path.join(TEMP_ROOT, uuid.uuid4().hex)
    os.makedirs(d, exist_ok=True)
    return d


def _cleanup_temp_dir(d: str):
    if not d:
        return
    try:
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
    except Exception as e:
        print(f"[H3SegmentPromptDirector] cleanup warning for {d}: {e}", flush=True)


# ---------------------------------------------------------------------------
# Cache helpers (mirrors H3PromptDirector — per-segment keying)
# ---------------------------------------------------------------------------


def _file_sha256(path: str) -> str:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 16), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def _compute_segment_cache_key(
    image_paths, image_5_path,
    video_path, segment_index, segment_count,
    segment_duration, goal, skill_name,
    api_url, api_key, model, output_language, video_fps,
):
    """Cache key for ONE segment's prompt request."""
    payload = {
        "image_hashes": [_file_sha256(p) for p in image_paths],
        "image_5_hash": _file_sha256(image_5_path) if image_5_path else "",
        "video_hash": _file_sha256(video_path) if video_path else "",
        "video_fps": float(video_fps) if video_fps else DEFAULT_VIDEO_FPS,
        "segment_index": int(segment_index),
        "segment_count": int(segment_count),
        "segment_duration": float(segment_duration),
        "goal": goal.strip(),
        "skill_name": skill_name,
        "api_url": api_url,
        "api_key": api_key,
        "model": model,
        "output_language": output_language,
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _cache_get(cache_dir, key):
    path = os.path.join(cache_dir, f"{key}.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            entry = json.load(f)
        if all(k in entry for k in ("prompt", "raw", "saved_at")):
            return entry["prompt"], entry["raw"], entry["saved_at"]
    except Exception as e:
        print(f"[H3SegmentPromptDirector] cache read failed for {key}: {e}", flush=True)
    return None


def _cache_put(cache_dir, key, prompt, raw):
    try:
        os.makedirs(cache_dir, exist_ok=True)
    except Exception as e:
        print(f"[H3SegmentPromptDirector] cache mkdir failed: {e}", flush=True)
        return
    entry = {"prompt": prompt, "raw": raw, "saved_at": int(time.time())}
    tmp_path = os.path.join(cache_dir, f"{key}.json.tmp")
    final_path = os.path.join(cache_dir, f"{key}.json")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(entry, f, ensure_ascii=False)
        os.replace(tmp_path, final_path)
    except Exception as e:
        print(f"[H3SegmentPromptDirector] cache write failed for {key}: {e}", flush=True)
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        return
    _cache_lru_trim(cache_dir)


def _cache_lru_trim(cache_dir):
    try:
        files = [
            os.path.join(cache_dir, f)
            for f in os.listdir(cache_dir)
            if f.endswith(".json")
        ]
        if len(files) <= CACHE_MAX_ENTRIES:
            return
        files.sort(key=lambda p: os.path.getmtime(p))
        for old in files[: len(files) - CACHE_MAX_ENTRIES]:
            try:
                os.unlink(old)
            except Exception:
                pass
    except Exception as e:
        print(f"[H3SegmentPromptDirector] cache lru trim warning: {e}", flush=True)


# ---------------------------------------------------------------------------
# Hermes API call for ONE segment
# ---------------------------------------------------------------------------


def _call_hermes_segment(
    api_url, api_key, model,
    image_paths, image_5_path,
    video_path, segment_index, segment_count,
    segment_duration, goal, skill_name, timeout,
    video_fps=DEFAULT_VIDEO_FPS,
):
    """POST a chat completion for ONE segment and return the assistant content.

    For segment_index == 1: image_5_path is ignored; image_paths contain
    the user's normal references (image_1..image_4).

    For segment_index >= 2: image_5_path is the previous segment's last
    frame; we splice it into the prompt as the starting-frame lock.
    """
    content = []

    intro_lines = [goal.strip()]
    intro_lines.append("")
    intro_lines.append(
        f"切分信息：第 {segment_index} 段 / 共 {segment_count} 段，"
        f"目标时长 {segment_duration:g} 秒。"
    )

    if segment_index >= 2 and image_5_path:
        intro_lines.append(
            "本段为续作段，必须把起始帧锁定图（见下 image_5）作为本段首帧，"
            "并在本段动作描述的最前面先描述这张起始帧，"
            "保证与上一段的最后一帧无缝衔接。"
        )
    intro_lines.append("")
    intro_lines.append("素材（请自行读取本地文件）：")

    for i, p in enumerate(image_paths, 1):
        intro_lines.append(f"- 图{i}: {p}")
    if segment_index >= 2 and image_5_path:
        intro_lines.append(f"- 图5 (起始帧锁定): {image_5_path}")
    if video_path:
        try:
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-count_frames", "-show_entries", "stream=nb_read_frames",
                 "-of", "default=nw=1:nk=1", video_path],
                capture_output=True, text=True, timeout=10,
            )
            n_frames = probe.stdout.strip() or "?"
        except Exception:
            n_frames = "?"
        intro_lines.append(f"- 参考视频（本段）: {video_path}  (帧数={n_frames})")

    intro_lines.append("")
    intro_lines.append(
        "请基于上面的本地素材（你已经在同一台机器上，可直接读取），"
        f"使用 {skill_name} 技能生成本段（第 {segment_index} 段 / 共 {segment_count} 段）的 H3 提示词。"
        "回复中只包含最终提示词本体（中英文版按技能要求），"
        "不要包含任何解释、前言、调用日志或元信息。"
    )
    content.append({"type": "text", "text": "\n".join(intro_lines)})

    # Embed all images
    all_paths = list(image_paths)
    if segment_index >= 2 and image_5_path:
        all_paths.append(image_5_path)
    for p in all_paths:
        try:
            with open(p, "rb") as f:
                data = f.read()
            ext = os.path.splitext(p)[1].lower().lstrip(".")
            mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png",
                    "webp": "webp", "bmp": "bmp"}.get(ext, "jpeg")
            import base64
            b64 = base64.b64encode(data).decode("ascii")
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/{mime};base64,{b64}"},
            })
        except Exception as e:
            print(f"[H3SegmentPromptDirector] failed to embed {p}: {e}", flush=True)

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": 4096,
        "temperature": 0.4,
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{api_url.rstrip('/')}/v1/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        resp_body = resp.read().decode("utf-8")
    data = json.loads(resp_body)
    if "error" in data:
        raise RuntimeError(f"Hermes API error: {data['error']}")
    return data["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# Reply cleanup (segment-form)
# ---------------------------------------------------------------------------


def _clean_response(text: str, prefer: str = "english") -> str:
    """Strip whatever prose the model added; keep only the final prompt.

    The h3-video-segment-prompt-director skill returns the same shape as
    h3-video-prompt-director: two code blocks, "最终提示词（英文版）" and
    "最终提示词（中文对照版）".
    """
    if not text:
        return ""

    def _slice_block(heading_regex: str):
        h_re = re.compile(heading_regex + r"[^\n]*\n+", re.MULTILINE)
        m = h_re.search(text)
        if not m:
            return None
        rest = text[m.end():]
        cb = re.search(r"```(?:[A-Za-z0-9_+\-]*)?\s*\n(.*?)\n```",
                       rest, re.DOTALL)
        if cb:
            return cb.group(1).strip()
        next_h = re.search(
            r"\n(?:模型选择|任务模式|提示词格式|选择理由|素材角色表|最终提示词|建议设置|审查)",
            rest,
        )
        end = next_h.start() if next_h else len(rest)
        return rest[:end].strip()

    en = _slice_block(r"最终提示词[（(]英文版[）)]")
    cn = _slice_block(r"最终提示词[（(]中文(?:对照版|版)[）)]")

    if prefer == "english":
        if en:
            return en
        if cn:
            return cn
    elif prefer == "chinese":
        if cn:
            return cn
        if en:
            return en
    elif prefer == "both":
        if en and cn:
            return (en + "\n\n" + ("=" * 60) +
                    "\n# 中文对照版（仅供理解）\n" + ("=" * 60) +
                    "\n\n" + cn)
        if en:
            return en
        if cn:
            return cn

    # Fallback: largest code block
    fences = re.findall(r"```(?:[A-Za-z0-9_+\-]*)?\n(.*?)\n```", text, re.DOTALL)
    if fences:
        return max(fences, key=len).strip()
    return text.strip()


# ---------------------------------------------------------------------------
# ComfyUI node
# ---------------------------------------------------------------------------


class H3SegmentPromptDirector:
    """H3 segment-aware prompt director — multi-segment chunked video generation."""

    @classmethod
    def INPUT_TYPES(cls):
        # Build inputs programmatically to keep MAX_SEGMENTS in one place.
        video_inputs = {
            "reference_video_1": ("IMAGE",),  # required, listed first
        }
        for i in range(2, MAX_SEGMENTS + 1):
            video_inputs[f"reference_video_{i}"] = ("IMAGE",)

        image_inputs = {}
        for i in range(1, 6):
            image_inputs[f"image_{i}"] = ("IMAGE",)

        return {
            "required": {
                # Required-by-ComfyUI trick: declare the FIRST video slot here
                # but make all others optional. We add a runtime guard so a
                # missing reference_video_1 raises a clear error.
                "reference_video_1": ("IMAGE",),
                "segment_duration": ("FLOAT", {
                    "default": DEFAULT_SEGMENT_DURATION,
                    "min": 0.5,
                    "max": 60.0,
                    "step": 0.5,
                    "tooltip": "目标时长（秒）。前 N-1 段都会按这个时长生成；"
                               "最后一段按视频剩余长度生成。",
                }),
                "goal": ("STRING", {
                    "default": DEFAULT_GOAL,
                    "multiline": True,
                    "placeholder": "例：将图1的角色迁移到参考视频里，保持动作一致。",
                }),
                "skill_name": ("STRING", {
                    "default": DEFAULT_SKILL_NAME,
                    "placeholder": "Hermes 接收端要激活的 skill 名",
                }),
            },
            "optional": {
                # Reference videos 2..12 — empty/None terminates the segment list
                **{f"reference_video_{i}": ("IMAGE",)
                   for i in range(2, MAX_SEGMENTS + 1)},
                # User images
                **{f"image_{i}": ("IMAGE",) for i in range(1, 6)},
                # video_fps
                "video_fps": ("FLOAT", {
                    "default": DEFAULT_VIDEO_FPS,
                    "min": 1.0,
                    "max": 120.0,
                    "step": 0.5,
                    "tooltip": "每个 segment 参考视频的帧率（FPS）",
                }),
                # Standard config knobs
                "api_url": ("STRING", {
                    "default": DEFAULT_API_URL,
                    "placeholder": "Hermes API base URL",
                }),
                "api_key": ("STRING", {
                    "default": DEFAULT_API_KEY,
                    "placeholder": "Hermes API key",
                }),
                "model": ("STRING", {
                    "default": DEFAULT_MODEL,
                    "placeholder": "模型名",
                }),
                "output_language": (["english", "chinese", "both"], {
                    "default": "english",
                }),
                "keep_temp_files": ("BOOLEAN", {
                    "default": False,
                }),
                "enable_cache": ("BOOLEAN", {
                    "default": DEFAULT_ENABLE_CACHE,
                    "tooltip": "每个 segment 的 prompt 各自缓存（按 segment_index + 媒体 hash）",
                }),
                "cache_dir": ("STRING", {
                    "default": DEFAULT_CACHE_DIR,
                }),
                "timeout": ("INT", {
                    "default": 300,
                    "min": 30,
                    "max": MAX_TIMEOUT,
                    "step": 10,
                }),
            },
        }

    RETURN_TYPES = ("STRING",) * (MAX_SEGMENTS + 2)  # prompt_1..12 + raw + temp_dir
    RETURN_NAMES = tuple(
        [f"prompt_{i}" for i in range(1, MAX_SEGMENTS + 1)] + ["raw", "temp_dir"]
    )
    FUNCTION = "generate"
    CATEGORY = "HermesAI/Prompt"
    DESCRIPTION = (
        "分段版 H3 提示词生成器：接收最多 12 段参考视频 + 1 段切分时长，"
        "对每段分别调用 Hermes 生成 H3 提示词。"
        "第 1 段用 image_1..image_4 + 参考视频；"
        "第 N 段（N>=2）强制要求 image_5 作为起始帧锁定。"
        "12 个 prompt 输出槽独立，下游各自接 H3 节点；raw 槽拼好所有段，调试用。"
    )

    def generate(self, reference_video_1, segment_duration, goal,
                 skill_name=DEFAULT_SKILL_NAME,
                 reference_video_2=None, reference_video_3=None,
                 reference_video_4=None, reference_video_5=None,
                 reference_video_6=None, reference_video_7=None,
                 reference_video_8=None, reference_video_9=None,
                 reference_video_10=None, reference_video_11=None,
                 reference_video_12=None,
                 image_1=None, image_2=None, image_3=None, image_4=None,
                 image_5=None,
                 video_fps=DEFAULT_VIDEO_FPS,
                 api_url=DEFAULT_API_URL, api_key=DEFAULT_API_KEY,
                 model=DEFAULT_MODEL, output_language="english",
                 keep_temp_files=False,
                 enable_cache=DEFAULT_ENABLE_CACHE,
                 cache_dir=DEFAULT_CACHE_DIR,
                 timeout=300):
        t0 = time.time()
        temp_dir = _make_temp_dir()

        try:
            # ---- 1. Collect non-empty reference videos ----
            video_slots = [
                reference_video_1, reference_video_2, reference_video_3,
                reference_video_4, reference_video_5, reference_video_6,
                reference_video_7, reference_video_8, reference_video_9,
                reference_video_10, reference_video_11, reference_video_12,
            ]
            segment_count = 0
            for slot in video_slots:
                if slot is not None:
                    segment_count += 1
                else:
                    break  # first None terminates the list
            if segment_count < 1:
                raise ValueError(
                    "[H3SegmentPromptDirector] at least reference_video_1 must be connected."
                )
            if segment_count > MAX_SEGMENTS:
                segment_count = MAX_SEGMENTS

            print(f"[H3SegmentPromptDirector] segment_count={segment_count}, "
                  f"segment_duration={segment_duration}s", flush=True)

            # ---- 2. Save image tensors ----
            image_paths = []
            for i, img in enumerate([image_1, image_2, image_3, image_4], 1):
                if img is None:
                    continue
                dest = os.path.join(temp_dir, f"img_{i}.png")
                try:
                    saved = _save_image_tensor(img, dest)
                    image_paths.append(saved)
                    print(f"[H3SegmentPromptDirector] saved 图{i} -> {saved}",
                          flush=True)
                except Exception as e:
                    print(f"[H3SegmentPromptDirector] 图{i} failed: {e}",
                          flush=True)

            image_5_path = None
            if image_5 is not None:
                dest = os.path.join(temp_dir, "img_5.png")
                try:
                    image_5_path = _save_image_tensor(image_5, dest)
                    print(f"[H3SegmentPromptDirector] saved image_5 (boundary lock) "
                          f"-> {image_5_path}", flush=True)
                except Exception as e:
                    print(f"[H3SegmentPromptDirector] image_5 failed: {e}",
                          flush=True)

            # If segment_count >= 2 and no image_5, warn loudly (but proceed —
            # the skill itself should also handle this case).
            if segment_count >= 2 and image_5_path is None:
                print(f"[H3SegmentPromptDirector] WARNING: segment_count={segment_count} "
                      f"but no image_5 (boundary lock). Prompt may not stitch cleanly.",
                      flush=True)

            # ---- 3. Save reference videos as mp4s ----
            video_paths = []
            for i in range(segment_count):
                slot = video_slots[i]
                dest = os.path.join(temp_dir, f"segment_{i+1}.mp4")
                try:
                    vp = _save_video_frames(slot, dest, video_fps)
                    video_paths.append(vp)
                    print(f"[H3SegmentPromptDirector] saved segment {i+1} video "
                          f"-> {vp}", flush=True)
                except Exception as e:
                    print(f"[H3SegmentPromptDirector] segment {i+1} failed: {e}",
                          flush=True)
                    raise

            # ---- 4. Per-segment Hermes calls ----
            prompt_outputs = [""] * MAX_SEGMENTS
            raw_chunks = []
            for i in range(segment_count):
                seg_index = i + 1
                print(f"[H3SegmentPromptDirector] processing segment {seg_index}/"
                      f"{segment_count}...", flush=True)

                # Cache key check
                cache_key = None
                if enable_cache:
                    cache_key = _compute_segment_cache_key(
                        image_paths, image_5_path,
                        video_paths[i], seg_index, segment_count,
                        segment_duration, goal, skill_name,
                        api_url, api_key, model, output_language, video_fps,
                    )
                    hit = _cache_get(cache_dir, cache_key)
                    if hit is not None:
                        cached_prompt, cached_raw, saved_at = hit
                        print(f"[H3SegmentPromptDirector] segment {seg_index} "
                              f"cache HIT saved_at={saved_at}", flush=True)
                        prompt_outputs[i] = cached_prompt
                        raw_chunks.append(
                            f"===== SEGMENT {seg_index} =====\n{cached_raw}"
                        )
                        continue
                    print(f"[H3SegmentPromptDirector] segment {seg_index} "
                          f"cache MISS", flush=True)

                # Build the per-segment image set:
                #   segment 1: image_1..image_4
                #   segment i >= 2: image_1..image_4 + image_5 (boundary lock)
                seg_images = list(image_paths)
                if seg_index >= 2 and image_5_path:
                    seg_images.append(image_5_path)

                raw = _call_hermes_segment(
                    api_url=api_url, api_key=api_key, model=model,
                    image_paths=seg_images, image_5_path=image_5_path,
                    video_path=video_paths[i],
                    segment_index=seg_index, segment_count=segment_count,
                    segment_duration=segment_duration, goal=goal,
                    skill_name=skill_name, timeout=timeout,
                    video_fps=video_fps,
                )
                cleaned = _clean_response(raw, prefer=output_language)

                if enable_cache and cache_key:
                    _cache_put(cache_dir, cache_key, cleaned, raw)

                prompt_outputs[i] = cleaned
                raw_chunks.append(f"===== SEGMENT {seg_index} =====\n{raw}")

            # ---- 5. Combine raw ----
            combined_raw = "\n\n".join(raw_chunks)

            print(f"[H3SegmentPromptDirector] done in {time.time()-t0:.1f}s, "
                  f"{segment_count} segment(s) generated", flush=True)

            # Build return tuple: (prompt_1..12, raw, temp_dir)
            result = tuple(prompt_outputs) + (
                combined_raw,
                temp_dir if keep_temp_files else "",
            )
            return result
        finally:
            if not keep_temp_files:
                _cleanup_temp_dir(temp_dir)


# ---------------------------------------------------------------------------
# ComfyUI registration
# ---------------------------------------------------------------------------

NODE_CLASS_MAPPINGS = {
    "H3SegmentPromptDirector": H3SegmentPromptDirector,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "H3SegmentPromptDirector": "H3 Segment Prompt Director (Hermes)",
}