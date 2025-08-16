# syncstage/translate.py
from __future__ import annotations
import json
import os
import time
from pathlib import Path
from typing import Optional, Tuple

class TranslatorBase:
    def translate(self, text: str, src: str, dest: str) -> str:
        raise NotImplementedError

class GoogleTransTranslator(TranslatorBase):
    def __init__(self):
        try:
            from googletrans import Translator  # type: ignore
        except Exception as e:
            raise RuntimeError("googletrans is not installed. pip install '.[translate]'") from e
        self._tr = Translator()

    def translate(self, text: str, src: str, dest: str) -> str:
        if not text.strip():
            return text
        # googletrans sometimes throws occasional errors; retry a little
        for i in range(3):
            try:
                return self._tr.translate(text, src=src, dest=dest).text
            except Exception:
                time.sleep(0.5 * (i + 1))
        # last attempt raises
        return self._tr.translate(text, src=src, dest=dest).text

class GCloudTranslator(TranslatorBase):
    def __init__(self, project_id: Optional[str] = None):
        # Requires GOOGLE_APPLICATION_CREDENTIALS env var (or default creds)
        try:
            from google.cloud import translate_v2 as translate  # type: ignore
        except Exception as e:
            raise RuntimeError("google-cloud-translate is not installed. pip install '.[gcloud]'") from e
        self._translate = translate.Client(project=project_id)

    def translate(self, text: str, src: str, dest: str) -> str:
        if not text.strip():
            return text
        # v2 client detects language if not provided, but we pass src for determinism
        result = self._translate.translate(text, source_language=src, target_language=dest, format_="text")
        return result["translatedText"]

def load_cache(path: Optional[Path]) -> dict:
    if not path:
        return {}
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

def save_cache(path: Optional[Path], cache: dict) -> None:
    if not path:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

def get_translator(provider: str) -> TranslatorBase:
    if provider == "gcloud":
        return GCloudTranslator()
    # default
    return GoogleTransTranslator()

def translate_cached(text: str, src: str, dest: str, provider: str, cache_path: Optional[Path]) -> str:
    cache = load_cache(cache_path)
    key = f"{provider}:{src}->{dest}:{text}"
    if key in cache:
        return cache[key]
    tr = get_translator(provider)
    out = tr.translate(text, src=src, dest=dest)
    cache[key] = out
    save_cache(cache_path, cache)
    return out
