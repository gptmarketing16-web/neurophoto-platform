from __future__ import annotations

import asyncio
import base64
import shutil
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from PIL import Image

from ..settings import settings


class ImageProviderError(RuntimeError):
    pass


@dataclass
class GenerationOutput:
    paths: list[Path]
    usage: dict[str, int] = field(default_factory=dict)


ASPECT_VALUES = {
    "1:1": 1.0,
    "2:3": 2 / 3,
    "3:2": 3 / 2,
    "3:4": 3 / 4,
    "4:3": 4 / 3,
    "4:5": 4 / 5,
    "5:4": 5 / 4,
    "9:16": 9 / 16,
    "16:9": 16 / 9,
}


def closest_aspect_ratio(width: int, height: int) -> str:
    if not width or not height:
        return "1:1"
    value = width / height
    return min(ASPECT_VALUES, key=lambda key: abs(ASPECT_VALUES[key] - value))


def openai_size_for_ratio(aspect_ratio: str) -> str:
    value = ASPECT_VALUES.get(aspect_ratio, 1.0)
    if value < 0.9:
        return "1024x1536"
    if value > 1.1:
        return "1536x1024"
    return "1024x1024"


def crop_to_aspect(path: Path, aspect_ratio: str) -> None:
    target_ratio = ASPECT_VALUES.get(aspect_ratio)
    if not target_ratio:
        return
    with Image.open(path) as image:
        width, height = image.size
        current = width / height
        if abs(current - target_ratio) < 0.005:
            return
        if current > target_ratio:
            new_width = max(1, round(height * target_ratio))
            left = (width - new_width) // 2
            box = (left, 0, left + new_width, height)
        else:
            new_height = max(1, round(width / target_ratio))
            top = (height - new_height) // 2
            box = (0, top, width, top + new_height)
        cropped = image.crop(box)
        if path.suffix.lower() in {".jpg", ".jpeg"}:
            cropped.convert("RGB").save(path, quality=95)
        else:
            cropped.save(path)


class ImageProvider:
    provider_name = "unknown"

    async def generate_from_references(
        self,
        *,
        prompt: str,
        image_paths: list[Path],
        output_count: int,
        output_dir: Path,
        model: str,
        aspect_ratio: str,
        quality: str,
    ) -> GenerationOutput:
        raise NotImplementedError


class MockImageProvider(ImageProvider):
    provider_name = "mock"

    async def generate_from_references(self, *, prompt: str, image_paths: list[Path], output_count: int,
                                       output_dir: Path, model: str, aspect_ratio: str,
                                       quality: str) -> GenerationOutput:
        if not image_paths:
            raise ImageProviderError("Mock provider needs at least one image")
        output_dir.mkdir(parents=True, exist_ok=True)
        source = image_paths[-1]
        suffix = source.suffix.lower() or ".png"
        result: list[Path] = []
        for index in range(output_count):
            target = output_dir / f"output_{index + 1:03d}{suffix}"
            shutil.copy2(source, target)
            crop_to_aspect(target, aspect_ratio)
            result.append(target)
        return GenerationOutput(paths=result)


class OpenAIImageProvider(ImageProvider):
    provider_name = "openai"

    def __init__(self, api_key: str, base_url: str = "") -> None:
        if not api_key:
            raise ImageProviderError("API-ключ OpenAI не настроен")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ImageProviderError("The openai Python SDK is not installed") from exc
        kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url.rstrip("/")
        self.client = OpenAI(**kwargs)
        self.semaphore = asyncio.Semaphore(settings.openai_max_concurrency)

    async def _one_batch(self, *, prompt: str, image_paths: list[Path], count: int,
                         model: str, aspect_ratio: str, quality: str) -> tuple[list[bytes], dict[str, int]]:
        async with self.semaphore:
            return await asyncio.to_thread(
                self._one_batch_sync, prompt, image_paths, count, model, aspect_ratio, quality
            )

    def _one_batch_sync(self, prompt: str, image_paths: list[Path], count: int,
                        model: str, aspect_ratio: str, quality: str) -> tuple[list[bytes], dict[str, int]]:
        with ExitStack() as stack:
            images = [stack.enter_context(path.open("rb")) for path in image_paths]
            kwargs: dict[str, Any] = {
                "model": model,
                "image": images,
                "prompt": prompt,
                "n": count,
                "size": openai_size_for_ratio(aspect_ratio),
                "quality": quality,
                "output_format": "png",
            }
            if not model.startswith("gpt-image-2"):
                kwargs["input_fidelity"] = "high"
            response = self.client.images.edit(**kwargs)
        images_bytes: list[bytes] = []
        for item in response.data or []:
            if getattr(item, "b64_json", None):
                images_bytes.append(base64.b64decode(item.b64_json))
            elif getattr(item, "url", None):
                images_bytes.append(httpx.get(item.url, timeout=120).content)
            else:
                raise ImageProviderError("Провайдер вернул изображение без данных")
        if len(images_bytes) != count:
            raise ImageProviderError(f"Ожидалось {count} изображений, получено {len(images_bytes)}")
        usage_obj = getattr(response, "usage", None)
        usage = {
            "input_tokens": int(getattr(usage_obj, "input_tokens", 0) or 0),
            "output_tokens": int(getattr(usage_obj, "output_tokens", 0) or 0),
            "total_tokens": int(getattr(usage_obj, "total_tokens", 0) or 0),
        }
        return images_bytes, usage

    async def generate_from_references(self, *, prompt: str, image_paths: list[Path], output_count: int,
                                       output_dir: Path, model: str, aspect_ratio: str,
                                       quality: str) -> GenerationOutput:
        if not image_paths or output_count < 1:
            raise ImageProviderError("Нужны входные изображения и положительное количество результатов")
        batch_sizes: list[int] = []
        remaining = output_count
        while remaining:
            batch = min(10, remaining)
            batch_sizes.append(batch)
            remaining -= batch
        batches = await asyncio.gather(*[
            self._one_batch(prompt=prompt, image_paths=image_paths, count=batch,
                            model=model, aspect_ratio=aspect_ratio, quality=quality)
            for batch in batch_sizes
        ])
        output_dir.mkdir(parents=True, exist_ok=True)
        result: list[Path] = []
        total_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        index = 1
        for image_batch, usage in batches:
            for key in total_usage:
                total_usage[key] += int(usage.get(key, 0) or 0)
            for image_bytes in image_batch:
                target = output_dir / f"output_{index:03d}.png"
                target.write_bytes(image_bytes)
                crop_to_aspect(target, aspect_ratio)
                result.append(target)
                index += 1
        return GenerationOutput(paths=result, usage=total_usage)


class GeminiImageProvider(ImageProvider):
    provider_name = "gemini"

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ImageProviderError("API-ключ Gemini не настроен")
        try:
            from google import genai
        except ImportError as exc:
            raise ImageProviderError("The google-genai Python SDK is not installed") from exc
        self.client = genai.Client(api_key=api_key)
        self.semaphore = asyncio.Semaphore(settings.gemini_max_concurrency)

    def _one_sync(self, prompt: str, image_paths: list[Path], model: str,
                  aspect_ratio: str, quality: str) -> tuple[bytes, dict[str, int]]:
        input_blocks: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for path in image_paths:
            suffix = path.suffix.lower()
            mime_type = "image/png" if suffix == ".png" else "image/webp" if suffix == ".webp" else "image/jpeg"
            input_blocks.append({
                "type": "image",
                "data": base64.b64encode(path.read_bytes()).decode("ascii"),
                "mime_type": mime_type,
            })
        interaction = self.client.interactions.create(
            model=model,
            input=input_blocks,
            response_format={
                "type": "image",
                "mime_type": "image/png",
                "aspect_ratio": aspect_ratio,
                "image_size": "2K" if quality == "high" else "1K",
            },
            store=False,
        )
        output_image = getattr(interaction, "output_image", None)
        data = getattr(output_image, "data", None)
        if not data:
            raise ImageProviderError("Gemini не вернул изображение")
        usage_obj = getattr(interaction, "usage_metadata", None) or getattr(interaction, "usage", None)
        input_tokens = int(getattr(usage_obj, "prompt_token_count", 0) or getattr(usage_obj, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage_obj, "candidates_token_count", 0) or getattr(usage_obj, "output_tokens", 0) or 0)
        total_tokens = int(getattr(usage_obj, "total_token_count", 0) or getattr(usage_obj, "total_tokens", 0) or input_tokens + output_tokens)
        return base64.b64decode(data), {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
        }

    async def _one(self, *, prompt: str, image_paths: list[Path], model: str,
                   aspect_ratio: str, quality: str) -> tuple[bytes, dict[str, int]]:
        async with self.semaphore:
            return await asyncio.to_thread(self._one_sync, prompt, image_paths, model, aspect_ratio, quality)

    async def generate_from_references(self, *, prompt: str, image_paths: list[Path], output_count: int,
                                       output_dir: Path, model: str, aspect_ratio: str,
                                       quality: str) -> GenerationOutput:
        results = await asyncio.gather(*[
            self._one(prompt=prompt, image_paths=image_paths, model=model,
                      aspect_ratio=aspect_ratio, quality=quality)
            for _ in range(output_count)
        ])
        output_dir.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        for index, (image_bytes, item_usage) in enumerate(results, start=1):
            target = output_dir / f"output_{index:03d}.png"
            target.write_bytes(image_bytes)
            crop_to_aspect(target, aspect_ratio)
            paths.append(target)
            for key in usage:
                usage[key] += int(item_usage.get(key, 0) or 0)
        return GenerationOutput(paths=paths, usage=usage)


class IntegratorImageProvider(ImageProvider):
    """Universal multipart bridge for an external integration platform.

    Request fields: prompt, model, output_count, aspect_ratio, quality and repeated images files.
    Accepted JSON response: {"images": [...]} or {"data": [...]}; items may contain
    b64_json/base64/url or be plain base64 strings.
    """

    provider_name = "integrator"

    def __init__(self, *, api_key: str, endpoint: str, auth_header: str, auth_prefix: str) -> None:
        if not endpoint:
            raise ImageProviderError("Не указан URL интегратора")
        self.api_key = api_key
        self.endpoint = endpoint
        self.auth_header = auth_header or "Authorization"
        self.auth_prefix = auth_prefix

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            return {}
        value = f"{self.auth_prefix} {self.api_key}".strip()
        return {self.auth_header: value}

    async def generate_from_references(self, *, prompt: str, image_paths: list[Path], output_count: int,
                                       output_dir: Path, model: str, aspect_ratio: str,
                                       quality: str) -> GenerationOutput:
        files = []
        for path in image_paths:
            suffix = path.suffix.lower()
            mime = "image/png" if suffix == ".png" else "image/webp" if suffix == ".webp" else "image/jpeg"
            files.append(("images", (path.name, path.read_bytes(), mime)))
        data = {
            "prompt": prompt,
            "model": model,
            "output_count": str(output_count),
            "aspect_ratio": aspect_ratio,
            "quality": quality,
        }
        async with httpx.AsyncClient(timeout=600) as client:
            response = await client.post(self.endpoint, data=data, files=files, headers=self._headers())
        if response.status_code >= 400:
            raise ImageProviderError(f"Интегратор вернул {response.status_code}: {response.text[:500]}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ImageProviderError("Интегратор должен вернуть JSON") from exc
        items = payload.get("images") or payload.get("data") or []
        if not isinstance(items, list):
            raise ImageProviderError("В ответе интегратора нет массива images/data")
        output_dir.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        async with httpx.AsyncClient(timeout=180) as client:
            for index, item in enumerate(items[:output_count], start=1):
                raw: bytes | None = None
                if isinstance(item, str):
                    try:
                        raw = base64.b64decode(item)
                    except Exception:
                        raw = (await client.get(item)).content if item.startswith("http") else None
                elif isinstance(item, dict):
                    encoded = item.get("b64_json") or item.get("base64") or item.get("data")
                    if encoded:
                        raw = base64.b64decode(encoded)
                    elif item.get("url"):
                        raw = (await client.get(item["url"])).content
                if not raw:
                    continue
                target = output_dir / f"output_{index:03d}.png"
                target.write_bytes(raw)
                crop_to_aspect(target, aspect_ratio)
                paths.append(target)
        if not paths:
            raise ImageProviderError("Интегратор не вернул пригодных изображений")
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        return GenerationOutput(paths=paths, usage={
            "input_tokens": int(usage.get("input_tokens", 0) or 0),
            "output_tokens": int(usage.get("output_tokens", 0) or 0),
            "total_tokens": int(usage.get("total_tokens", 0) or 0),
        })


def get_image_provider(config: dict[str, Any]) -> ImageProvider:
    provider = str(config.get("provider") or "mock").lower()
    api_key = str(config.get("api_key") or "")
    mode = str(config.get("connection_mode") or "direct").lower()
    base_url = str(config.get("base_url") or "")
    if mode == "integrator":
        return IntegratorImageProvider(
            api_key=api_key,
            endpoint=base_url,
            auth_header=str(config.get("auth_header") or "Authorization"),
            auth_prefix=str(config.get("auth_prefix") or "Bearer"),
        )
    if provider == "openai":
        return OpenAIImageProvider(api_key, base_url)
    if provider == "gemini":
        return GeminiImageProvider(api_key)
    return MockImageProvider()
