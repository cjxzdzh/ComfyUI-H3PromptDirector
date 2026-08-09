"""ComfyUI-H3PromptDirector — H3 video prompt director via Hermes API."""
from .nodes import NODE_CLASS_MAPPINGS as _N1, NODE_DISPLAY_NAME_MAPPINGS as _D1
from .segment_nodes import NODE_CLASS_MAPPINGS as _N2, NODE_DISPLAY_NAME_MAPPINGS as _D2

NODE_CLASS_MAPPINGS = {**_N1, **_N2}
NODE_DISPLAY_NAME_MAPPINGS = {**_D1, **_D2}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]