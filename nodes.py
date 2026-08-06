"""
ComfyUI H3 Prompt Director
==========================

A ComfyUI node that takes up to 5 reference images (IMAGE) and 1 reference
video (IMAGE batch, i.e. the standard ComfyUI convention where video
loaders emit a `[N, H, W, C]` float tensor of frames), encodes everything
to a fresh temp directory, sends the local paths plus a one-line goal to
the Hermes API (default http://192.168.3.78:8642), and returns the final
H3 prompt produced by the `h3-video-prompt-director` skill.

Why recompose to temp files:
  - ComfyUI's IMAGE type is a torch tensor — no path on disk.
  - The Hermes API 8642 only accepts `image_url` (still image) + text
    content parts; it does NOT accept `video_url`. So video frames must
    be re-encoded into a real mp4 file that the receiving Hermes agent
    can read off the same host.
  - Re-encoding gives Hermes a single canonical file path it can latch
    onto for frame timing, motion analysis, etc.

Cleanup:
  - All temp files live in a unique per-call subdir under
    `/tmp/h3-prompt-director/<uuid>/`. The directory is rm-rf'd after the
    Hermes call returns (or fails) so we don't leak. Failure during
    cleanup is logged but does not mask the original error.

Outputs
-------
- prompt  (STRING) — the final H3 prompt (cleaned).
- raw     (STRING) — the unmodified Hermes response, for debugging.
- temp_dir (STRING) — absolute path of the temp directory used (for
                    inspection / debugging). Empty string after cleanup.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
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
DEFAULT_SKILL_NAME = "h3-video-prompt-director"
DEFAULT_GOAL = "让图1的角色模仿参考视频的角色跳舞，保留图1的场景。"
DEFAULT_TIMEOUT = 300
DEFAULT_VIDEO_FPS = 24.0
MAX_TIMEOUT = 86400  # 24 hours

DEFAULT_ENABLE_CACHE = False
DEFAULT_CACHE_DIR = "/tmp/h3-prompt-director/cache"
CACHE_MAX_ENTRIES = 100  # LRU cap

TEMP_ROOT = "/tmp/h3-prompt-director"

# ---------------------------------------------------------------------------
# Tensor -> image file
# ---------------------------------------------------------------------------


def _save_image_tensor(image, dest_path: str) -> str:
    """Save a ComfyUI IMAGE tensor to a PNG file.

    Accepts:
        - torch.Tensor of shape [H, W, C] or [B, H, W, C], float in [0, 1]
        - numpy.ndarray of the same shape
        - a string path (passed through unchanged)
        - a dict with `path` / `filename` / `filepath` (passed through)

    Returns the absolute path of the saved file. Raises ValueError on
    unrecognized shape.
    """
    # Pass-through for already-on-disk inputs.
    if isinstance(image, str) and os.path.isfile(image):
        return image
    if isinstance(image, dict):
        for k in ("path", "filename", "filepath"):
            v = image.get(k)
            if isinstance(v, str) and os.path.isfile(v):
                return v
        raise ValueError(f"dict image has no usable path key: {list(image)}")

    # Tensor / ndarray path.
    if hasattr(image, "detach"):  # torch.Tensor
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

    # ComfyUI: shape [B, H, W, C], float in [0, 1]
    if arr.ndim == 4:
        if arr.shape[0] != 1:
            raise ValueError(
                f"image tensor batch size = {arr.shape[0]}; "
                "this slot expects a single image (batch=1). "
                "Use VHS / VRGDG_LoadVideos to load videos, not images."
            )
        arr = arr[0]
    elif arr.ndim != 3:
        raise ValueError(
            f"image tensor has unexpected shape {arr.shape}; "
            "expected [H, W, C] or [1, H, W, C]"
        )

    # Convert to uint8: 255 * clip(arr, 0, 1)
    import numpy as np
    if arr.dtype.kind == "f":
        arr = np.clip(arr * 255.0, 0, 255).astype(np.uint8)
    elif arr.dtype != np.uint8:
        arr = arr.astype(np.uint8)

    from PIL import Image
    img = Image.fromarray(arr)
    img.save(dest_path, format="PNG")
    return dest_path


def _save_video_frames(video_tensor, dest_path: str, fps: float) -> str:
    """Encode a ComfyUI video frame batch `[N, H, W, C]` to mp4 via ffmpeg.

    Returns the absolute path of the written mp4.
    """
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

    # ---- Encode to mp4 via ffmpeg rawvideo pipe ----
    import numpy as np
    if arr.dtype.kind == "f":
        arr = np.clip(arr * 255.0, 0, 255).astype(np.uint8)
    elif arr.dtype != np.uint8:
        arr = arr.astype(np.uint8)

    # Ensure 3 channels (drop alpha if present — H3 doesn't need it).
    if arr.shape[-1] == 4:
        arr = arr[..., :3]
    elif arr.shape[-1] == 1:
        arr = np.repeat(arr, 3, axis=-1)
    elif arr.shape[-1] not in (3,):
        raise ValueError(f"video has {arr.shape[-1]} channels; need 3 or 4")

    # ffmpeg needs contiguous, planar-ish uint8
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


# ---------------------------------------------------------------------------
# Temp directory management
# ---------------------------------------------------------------------------


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
        print(f"[H3PromptDirector] cleanup warning for {d}: {e}", flush=True)


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------


def _file_sha256(path: str) -> str:
    """SHA-256 of a file's content. Returns empty string on failure."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 16), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def _compute_cache_key(image_paths, video_path, goal, skill_name,
                       api_url, api_key, model, output_language, video_fps):
    """Stable SHA-256 over a canonical JSON of all inputs that affect Hermes output.

    `api_key` is part of the key — different keys may run against different
    Hermes configurations / users / sessions, so we partition cache by it.

    `video_fps` is only included when a video is provided; otherwise it
    doesn't affect the output and would create spurious cache misses.
    """
    payload = {
        "image_hashes": [_file_sha256(p) for p in image_paths],
        "video_hash": _file_sha256(video_path) if video_path else "",
        "goal": goal.strip(),
        "skill_name": skill_name,
        "api_url": api_url,
        "api_key": api_key,
        "model": model,
        "output_language": output_language,
    }
    if video_path:
        payload["video_fps"] = float(video_fps) if video_fps else DEFAULT_VIDEO_FPS
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _cache_get(cache_dir: str, key: str):
    """Return (prompt, raw, saved_at) if cache hit, else None."""
    path = os.path.join(cache_dir, f"{key}.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            entry = json.load(f)
        if all(k in entry for k in ("prompt", "raw", "saved_at")):
            return entry["prompt"], entry["raw"], entry["saved_at"]
    except Exception as e:
        print(f"[H3PromptDirector] cache read failed for {key}: {e}", flush=True)
    return None


def _cache_put(cache_dir: str, key: str, prompt: str, raw: str):
    """Write cache entry atomically (tmp + rename). LRU-trim afterwards."""
    try:
        os.makedirs(cache_dir, exist_ok=True)
    except Exception as e:
        print(f"[H3PromptDirector] cache mkdir failed: {e}", flush=True)
        return
    entry = {"prompt": prompt, "raw": raw, "saved_at": int(time.time())}
    tmp_path = os.path.join(cache_dir, f"{key}.json.tmp")
    final_path = os.path.join(cache_dir, f"{key}.json")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(entry, f, ensure_ascii=False)
        os.replace(tmp_path, final_path)
    except Exception as e:
        print(f"[H3PromptDirector] cache write failed for {key}: {e}", flush=True)
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        return
    _cache_lru_trim(cache_dir)


def _cache_lru_trim(cache_dir: str):
    """Keep the most recent CACHE_MAX_ENTRIES entries by mtime."""
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
        print(f"[H3PromptDirector] cache lru trim warning: {e}", flush=True)


# ---------------------------------------------------------------------------
# Hermes API call
# ---------------------------------------------------------------------------


def _call_hermes(api_url: str, api_key: str, model: str,
                 image_paths, video_path, goal: str,
                 skill_name: str, timeout: int) -> str:
    """POST a chat completion to Hermes and return the assistant content.

    `skill_name` (default: h3-video-prompt-director) tells the receiving
    Hermes agent which skill to activate for the response.
    """
    content = []

    intro_lines = [goal.strip(), "", "素材（请自行读取本地文件）："]
    for i, p in enumerate(image_paths, 1):
        intro_lines.append(f"- 图{i}: {p}")
    if video_path:
        # Include the frame count so Hermes knows the video's duration
        # without having to probe the file again.
        try:
            import subprocess as _sp
            probe = _sp.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-count_frames", "-show_entries", "stream=nb_read_frames",
                 "-of", "default=nw=1:nk=1", video_path],
                capture_output=True, text=True, timeout=10,
            )
            n_frames = probe.stdout.strip() or "?"
        except Exception:
            n_frames = "?"
        intro_lines.append(f"- 参考视频: {video_path}  (帧数={n_frames})")

    intro_lines.append("")
    intro_lines.append(
        "请基于上面的本地素材（你已经在同一台机器上，可直接读取），"
        f"使用 {skill_name} 技能生成最终的 H3 提示词。"
        "回复中只包含最终提示词本体（中英文版按技能要求），"
        "不要包含任何解释、前言、调用日志或元信息。"
    )
    content.append({"type": "text", "text": "\n".join(intro_lines)})

    for p in image_paths:
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
            print(f"[H3PromptDirector] failed to embed {p}: {e}", flush=True)

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
# Reply cleanup
# ---------------------------------------------------------------------------


def _clean_response(text: str, prefer: str = "english") -> str:
    """Strip whatever prose the model added; keep only the final prompt.

    The h3-video-prompt-director skill always returns two code blocks:
      - "最终提示词（英文版）" — the ComfyUI / local H3-Base executable
      - "最终提示词（中文对照版）" — for human review only

    `prefer` selects which one to return:
      - "english" (default) — the English version
      - "chinese" — the Chinese version
      - "both"    — both, English first, joined with a divider
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
        next_h = re.search(r"\n(?:模型选择|任务模式|提示词格式|选择理由|素材角色表|最终提示词|建议设置|审查)", rest)
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

    # Fallback: largest code block in the response.
    fences = re.findall(r"```(?:[A-Za-z0-9_+\-]*)?\n(.*?)\n```",
                        text, re.DOTALL)
    if fences:
        body = max(fences, key=len).strip()
        for stop in ("\n建议设置", "\n审查", "\n4. ", "\n- 时长:"):
            idx = body.find(stop)
            if idx > 0:
                body = body[:idx].rstrip()
        return body

    body = text.strip()
    body = re.sub(
        r"^[\s\S]*?(?:最终提示词|prompt\s*[:：])\s*\n",
        "", body, count=1, flags=re.IGNORECASE,
    )
    return body.strip()


# ---------------------------------------------------------------------------
# ComfyUI node
# ---------------------------------------------------------------------------


class H3PromptDirector:
    """H3 video prompt director — calls Hermes API with refs + goal."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image_1": ("IMAGE",),
                "goal": ("STRING", {
                    "default": DEFAULT_GOAL,
                    "multiline": True,
                    "placeholder": "例：让图1的角色模仿参考视频的角色跳舞，保留图1的场景。",
                }),
                "skill_name": ("STRING", {
                    "default": DEFAULT_SKILL_NAME,
                    "placeholder": "Hermes 接收端要激活的 skill 名",
                }),
            },
            "optional": {
                "reference_video": ("IMAGE",),
                "video_fps": ("FLOAT", {
                    "default": DEFAULT_VIDEO_FPS,
                    "min": 1.0,
                    "max": 120.0,
                    "step": 0.5,
                    "tooltip": "参考视频帧率（FPS），仅当 reference_video 已连接时使用",
                }),
                "image_2": ("IMAGE",),
                "image_3": ("IMAGE",),
                "image_4": ("IMAGE",),
                "image_5": ("IMAGE",),
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
                    "tooltip": "选哪个版本作为最终提示词（英文版是 ComfyUI / H3-Base 可执行版本）",
                }),
                "keep_temp_files": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "保留临时文件（用于 debug / 复现）。默认 False，调用后清理。",
                }),
                "enable_cache": ("BOOLEAN", {
                    "default": DEFAULT_ENABLE_CACHE,
                    "tooltip": "启用 prompt 缓存：相同输入直接返回上次 prompt，不重发 API。",
                }),
                "cache_dir": ("STRING", {
                    "default": DEFAULT_CACHE_DIR,
                    "placeholder": "缓存目录（建议用非 /tmp 路径以持久化）",
                }),
                "timeout": ("INT", {
                    "default": DEFAULT_TIMEOUT,
                    "min": 30,
                    "max": MAX_TIMEOUT,
                    "step": 10,
                    "tooltip": "Hermes 调用超时（秒），最大 86400（24 小时）",
                }),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("prompt", "raw", "temp_dir")
    FUNCTION = "generate"
    CATEGORY = "HermesAI/Prompt"
    DESCRIPTION = ("调用 Hermes API，由 h3-video-prompt-director 技能生成 H3 视频提示词。"
                   "输入：image_1 (必填) + 最多 4 张额外图 + 可选 1 个视频帧 batch + 视频帧率 + 目标要求 + skill 名。"
                   "所有媒体先落盘到 /tmp/h3-prompt-director/<uuid>/ 再传 Hermes。"
                   "输出：最终提示词（给下游文本编码节点用）。"
                   "reference_video 是可选的：只输入图 + 一句话目标也能生成 H3 提示词。")

    def generate(self, image_1, goal,
                 skill_name=DEFAULT_SKILL_NAME,
                 reference_video=None,
                 video_fps=DEFAULT_VIDEO_FPS,
                 image_2=None, image_3=None, image_4=None, image_5=None,
                 api_url=DEFAULT_API_URL, api_key=DEFAULT_API_KEY,
                 model=DEFAULT_MODEL, output_language="english",
                 keep_temp_files=False,
                 enable_cache=DEFAULT_ENABLE_CACHE,
                 cache_dir=DEFAULT_CACHE_DIR,
                 timeout=DEFAULT_TIMEOUT):
        t0 = time.time()
        temp_dir = _make_temp_dir()

        try:
            # ---- 1. Save image tensors to temp PNGs ----
            image_paths = []
            for i, img in enumerate([image_1, image_2, image_3, image_4, image_5], 1):
                if img is None:
                    continue
                dest = os.path.join(temp_dir, f"img_{i}.png")
                try:
                    saved = _save_image_tensor(img, dest)
                    image_paths.append(saved)
                    print(f"[H3PromptDirector] saved 图{i} -> {saved}", flush=True)
                except Exception as e:
                    print(f"[H3PromptDirector] 图{i} failed: {e}", flush=True)

            # ---- 2. Encode video frame batch to mp4 ----
            video_path = None
            if reference_video is not None:
                dest = os.path.join(temp_dir, "reference.mp4")
                try:
                    video_path = _save_video_frames(reference_video, dest, video_fps)
                    print(f"[H3PromptDirector] saved reference video -> {video_path} "
                          f"(fps={video_fps})", flush=True)
                except Exception as e:
                    print(f"[H3PromptDirector] reference video failed: {e}", flush=True)

            if not image_paths:
                raise ValueError(
                    "[H3PromptDirector] image_1 is required; at least one image "
                    "must connect successfully. (reference_video is optional.)"
                )

            print(f"[H3PromptDirector] {len(image_paths)} image(s), "
                  f"video={'yes' if video_path else 'no'}, "
                  f"goal={goal[:60]!r}...", flush=True)

            # ---- 3. Cache check (only when enabled) ----
            cache_key = None
            if enable_cache:
                cache_key = _compute_cache_key(
                    image_paths, video_path, goal, skill_name,
                    api_url, api_key, model, output_language, video_fps,
                )
                hit = _cache_get(cache_dir, cache_key)
                if hit is not None:
                    prompt, raw, saved_at = hit
                    print(f"[H3PromptDirector] cache HIT key={cache_key[:12]}... "
                          f"saved_at={saved_at}, prompt={len(prompt)} chars, "
                          f"raw={len(raw)} chars "
                          f"(total {time.time()-t0:.2f}s)", flush=True)
                    return (prompt, raw, temp_dir if keep_temp_files else "")
                print(f"[H3PromptDirector] cache MISS key={cache_key[:12]}...", flush=True)

            # ---- 4. Call Hermes ----
            raw = _call_hermes(
                api_url=api_url, api_key=api_key, model=model,
                image_paths=image_paths, video_path=video_path, goal=goal,
                skill_name=skill_name, timeout=timeout,
            )
            prompt = _clean_response(raw, prefer=output_language)

            # ---- 5. Cache write (only when enabled) ----
            if enable_cache and cache_key:
                _cache_put(cache_dir, cache_key, prompt, raw)

            print(f"[H3PromptDirector] done in {time.time()-t0:.1f}s, "
                  f"prompt={len(prompt)} chars, raw={len(raw)} chars", flush=True)
            return (prompt, raw, temp_dir if keep_temp_files else "")
        finally:
            if not keep_temp_files:
                _cleanup_temp_dir(temp_dir)


# ---------------------------------------------------------------------------
# ComfyUI registration
# ---------------------------------------------------------------------------

NODE_CLASS_MAPPINGS = {
    "H3PromptDirector": H3PromptDirector,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "H3PromptDirector": "H3 Prompt Director (Hermes)",
}
