import os
import re
from typing import Dict, List

def _pretty_label(model_id: str) -> str:
    # Examples: "openai/gpt-5.2" -> "gpt-5.2 (openai)"
    #          "google/veo-3.1-fast/image-to-video" -> "veo-3.1-fast • image-to-video (google)"
    parts = model_id.split("/")
    if len(parts) >= 2:
        vendor = parts[0]
        rest = "/".join(parts[1:])
        rest = rest.replace("-", " ")
        rest = rest.replace("/", " • ")
        return f"{rest} ({vendor})"
    return model_id.replace("-", " ")

def models_from_env() -> List[Dict]:
    """
    Collects models from Render env vars like:
      APIFREE_CHAT_MODEL, APIFREE_CHAT2_MODEL, ...
      APIFREE_IMAGE_MODEL, APIFREE_IMAGE2_MODEL, ...
      APIFREE_SONG_MODEL, APIFREE_MUSIC_MODEL, ...
      APIFREE_VIDEO_MODEL, APIFREE_VIDEO2_MODEL, ...
    Any *_MODEL variable is accepted.
    """
    env = os.environ

    # map env var prefixes to UI kinds
    kind_map = {
        "APIFREE_CHAT": "llm",
        "APIFREE_LLM": "llm",
        "DEFAULT_CHAT": "llm",
        "APIFREE_IMAGE": "t2i",
        "DEFAULT_IMAGE": "t2i",
        "APIFREE_SONG": "music",
        "APIFREE_MUSIC": "music",
        "DEFAULT_SONG": "music",
        "DEFAULT_MUSIC": "music",
        "APIFREE_VIDEO": "i2v",
        "DEFAULT_VIDEO": "i2v",
        "APIFREE_T2V": "t2v",
        "APIFREE_A2V": "a2v",
        "APIFREE_I2I": "i2i",
    }

    # collect all *_MODEL
    out: List[Dict] = []
    for k, v in env.items():
        if not k.endswith("_MODEL") or not v.strip():
            continue
        # find best matching prefix
        kind = None
        for pref, km_kind in kind_map.items():
            if k.startswith(pref):
                kind = km_kind
                break
        if not kind:
            continue
        model_id = v.strip()
        out.append({
            "id": model_id,
            "label": _pretty_label(model_id),
            "kind": kind,
        })

    # stable sort & dedupe by (kind,id)
    seen=set()
    dedup=[]
    for m in sorted(out, key=lambda x: (x["kind"], x["label"])):
        key=(m["kind"], m["id"])
        if key in seen:
            continue
        seen.add(key)
        dedup.append(m)
    return dedup
