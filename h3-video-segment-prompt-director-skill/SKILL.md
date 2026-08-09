---
name: h3-video-segment-prompt-director
description: |
  Generate H3 video prompts for chunked / multi-segment video generation.
  Used when the source reference video is too long to generate in a single
  H3 call (e.g. 30s source vs H3 max 15s), so the workflow splits the
  source into multiple clips and runs each through H3 separately, then
  concatenates the outputs.

  The skill receives image_1..image_N (the first N-1 are user-provided
  character/scene/style references, image_N is reserved as the segment
  boundary lock image), ONE reference video clip (the chunk currently
  being processed), a `segment_index` (1-based, which chunk this is),
  `segment_count` (how many chunks total), `segment_duration` (target
  length of this chunk), and a `goal`.

  - segment 1: behaves like h3-video-prompt-director — normal references,
    no boundary lock.
  - segment i (i ≥ 2): MUST reference image_5 (or whichever image slot
    the segment-1 output produced as its last frame) as the
    "starting-frame lock" image so the chunk's first frame matches the
    previous chunk's last frame. The skill must also describe the
    starting frame explicitly in the prompt so H3 honors the lock.

  Outputs follow h3-video-prompt-director format: two code blocks,
  最终提示词（英文版） (the H3-executable English version) and
  最终提示词（中文对照版） (Chinese mirror for human review).
---

# h3-video-segment-prompt-director

## Purpose

This skill is the segment-aware sibling of `h3-video-prompt-director`.
It exists to support workflows where a single H3 call cannot cover the
entire reference video (H3 has a per-call length cap; with heavy
references it can be 10–15 seconds). The caller splits the reference
video into N chunks ahead of time, then asks this skill to generate a
prompt per chunk so the downstream H3 invocations can be stitched
together end-to-end.

## When to use

- The caller is `ComfyUI-H3PromptDirector`'s segment node
  (`H3SegmentPromptDirector`).
- The reference video is longer than H3's per-call cap.
- The caller pre-split the reference video into N clips and numbered
  them. The caller also computed the last frame of each clip (used as
  image_N for segment i+1).

## Inputs

- `image_1..image_4`: the user's character / scene / style / key-frame
  references. Same as `h3-video-prompt-director`.
- `image_5` (only used when `segment_index >= 2`): the last frame of
  the previous segment. Use this as the starting-frame lock for the
  current chunk so the transition between segments is seamless.
- One reference video: the current chunk's video frames (already a
  proper mp4 on disk; the caller passes the local path).
- `segment_index`: 1-based index of the current chunk.
- `segment_count`: total number of chunks.
- `segment_duration`: target length (seconds) of this chunk's H3
  generation. The first N-1 chunks will hit this exactly; the last
  chunk may be shorter if the source doesn't divide evenly.
- `goal`: the user's one-line goal describing the overall video.

## Behaviour

### Segment 1 (segment_index == 1)

Same as `h3-video-prompt-director`:
- Use `image_1..image_4` (ignore image_5 if provided).
- Generate the prompt for chunk 1's action / motion / scene.
- The prompt should be the full, self-contained first segment.

### Segment i (segment_index >= 2)

- `image_5` (or higher slot if more were provided) is the previous
  chunk's last frame. The prompt MUST explicitly describe this frame
  in the leading section, and MUST reference it in H3's reference-image
  position so H3 uses it as the first-frame lock.
- Beyond the leading starting-frame lock, the prompt describes the
  current chunk's action / motion / scene continuation from where
  segment i-1 left off.
- The boundary transition must feel seamless — pay attention to
  posture, hand position, gaze, lighting, and background layout
  already established by image_5.

## Output format

Same as `h3-video-prompt-director`:

```
最终提示词（英文版）
```text
<English prompt that H3 can execute>
```

最终提示词（中文对照版）
```text
<Chinese mirror, for human review>
```
```

The ComfyUI segment node extracts the English block (`输出 1..N` slots)
for downstream text-encoding nodes. The caller can use the Chinese
block for review / debugging.

## Hard rules

- Only return the two code blocks above. No preamble, no explanation,
  no model-selection narrative.
- segment_index >= 2 MUST include image_5 (or higher slot) description
  as the leading starting-frame lock.
- segment_index >= 2 MUST add a brief "continuation from previous
  segment" beat in the English prompt's first action block.
- Target length follows `segment_duration` for all chunks; the last
  chunk's actual generated length may be shorter if the source doesn't
  divide evenly — say so in the Chinese block if needed.

## Failure modes

- If image_5 is missing when segment_index >= 2, return an error
  block (just the English block) explaining that image_5 is required
  for continuation segments.
- If `segment_index > segment_count`, treat it as an out-of-range error.
