from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class OcrBox:
    text: str
    score: float
    points: tuple[tuple[float, float], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class OcrResult:
    text: str
    engine: str
    ok: bool
    message: str = ""
    boxes: tuple[OcrBox, ...] = field(default_factory=tuple)


class RapidOcr:
    def __init__(
        self,
        use_det: bool = True,
        use_cls: bool = True,
        use_rec: bool = True,
        cpu_threads: int = 2,
        execution_provider: str = "cpu",
    ):
        self.use_det = use_det
        self.use_cls = use_cls
        self.use_rec = use_rec
        self.cpu_threads = self._resolve_cpu_threads(cpu_threads)
        self.execution_provider = self._normalize_provider(execution_provider)
        self._engine: Any | None = None
        self._engine_provider: str | None = None
        self._disabled_providers: set[str] = set()

    @staticmethod
    def _resolve_cpu_threads(value: int) -> int:
        try:
            requested = int(value)
        except (TypeError, ValueError):
            requested = 0
        cpu_count = os.cpu_count() or 4
        if requested > 0:
            return max(1, min(requested, cpu_count))
        return max(1, cpu_count // 4)

    @staticmethod
    def _normalize_provider(value: str) -> str:
        normalized = (value or "cpu").strip().lower()
        if normalized in {"dml", "directml", "gpu-directml"}:
            return "directml"
        if normalized in {"gpu", "cuda", "gpu-cuda"}:
            return "cuda"
        if normalized == "auto":
            return "auto"
        return "cpu"

    @staticmethod
    def _provider_label(provider: str) -> str:
        labels = {
            "cpu": "CPU",
            "cuda": "GPU CUDA",
            "directml": "GPU DirectML",
        }
        return labels.get(provider, provider)

    @staticmethod
    def _safe_error_message(exc: Exception) -> str:
        try:
            return str(exc)
        except Exception:
            return exc.__class__.__name__

    @staticmethod
    def available_providers() -> tuple[str, ...]:
        try:
            import onnxruntime as ort
        except Exception:
            return tuple()
        try:
            return tuple(str(provider) for provider in ort.get_available_providers())
        except Exception:
            return tuple()

    def _provider_candidates(self) -> tuple[str, ...]:
        if self.execution_provider == "auto":
            providers = self.available_providers()
            candidates: list[str] = []
            if "CUDAExecutionProvider" in providers:
                candidates.append("cuda")
            if "DmlExecutionProvider" in providers:
                candidates.append("directml")
            candidates.append("cpu")
        elif self.execution_provider == "cpu":
            candidates = ["cpu"]
        else:
            candidates = [self.execution_provider, "cpu"]

        result: list[str] = []
        for provider in candidates:
            if provider in result:
                continue
            if provider != "cpu" and provider in self._disabled_providers:
                continue
            result.append(provider)
        return tuple(result or ("cpu",))

    def _rapidocr_params(self, provider: str | None = None) -> dict[str, Any]:
        active_provider = self._normalize_provider(provider or self.execution_provider)
        params: dict[str, Any] = {
            "Global.use_cls": self.use_cls,
            "EngineConfig.onnxruntime.intra_op_num_threads": self.cpu_threads,
            "EngineConfig.onnxruntime.inter_op_num_threads": 1,
            "EngineConfig.onnxruntime.enable_cpu_mem_arena": False,
        }
        if active_provider == "cuda":
            params["EngineConfig.onnxruntime.use_cuda"] = True
        elif active_provider == "directml":
            params["EngineConfig.onnxruntime.use_dml"] = True
        return params

    def _load_engine(self, provider: str):
        if self._engine is not None and self._engine_provider == provider:
            return self._engine
        try:
            from rapidocr import RapidOCR
        except Exception as exc:
            raise RuntimeError("未找到 RapidOCR。请安装 rapidocr 和 onnxruntime，或使用新版打包程序。") from exc
        self._engine = RapidOCR(params=self._rapidocr_params(provider))
        self._engine_provider = provider
        return self._engine

    def available(self) -> bool:
        for provider in self._provider_candidates():
            try:
                self._load_engine(provider)
                return True
            except Exception:
                if provider != "cpu":
                    self._disabled_providers.add(provider)
        return False

    @staticmethod
    def _points(box) -> tuple[tuple[float, float], ...]:
        if box is None:
            return tuple()
        try:
            return tuple((float(point[0]), float(point[1])) for point in box)
        except Exception:
            return tuple()

    @staticmethod
    def _sort_boxes(boxes: list[OcrBox]) -> list[OcrBox]:
        def key(item: OcrBox):
            if not item.points:
                return (0.0, 0.0)
            ys = [point[1] for point in item.points]
            xs = [point[0] for point in item.points]
            return (min(ys), min(xs))

        return sorted(boxes, key=key)

    def recognize(self, image_path: Path) -> OcrResult:
        errors: list[tuple[str, str]] = []
        output = None
        active_provider = ""
        for provider in self._provider_candidates():
            try:
                engine = self._load_engine(provider)
                output = engine(
                    str(image_path),
                    use_det=self.use_det,
                    use_cls=self.use_cls,
                    use_rec=self.use_rec,
                )
                active_provider = provider
                break
            except Exception as exc:
                errors.append((provider, self._safe_error_message(exc)))
                self._engine = None
                self._engine_provider = None
                if provider != "cpu":
                    self._disabled_providers.add(provider)

        if output is None:
            message = "；".join(f"{self._provider_label(provider)}：{error}" for provider, error in errors)
            return OcrResult("", "rapidocr", False, message)

        txts = tuple(getattr(output, "txts", ()) or ())
        scores = tuple(getattr(output, "scores", ()) or ())
        raw_boxes = getattr(output, "boxes", None)
        box_items: list[OcrBox] = []
        for index, text in enumerate(txts):
            score = float(scores[index]) if index < len(scores) else 0.0
            points = self._points(raw_boxes[index]) if raw_boxes is not None and index < len(raw_boxes) else tuple()
            box_items.append(OcrBox(str(text), score, points))
        sorted_items = self._sort_boxes(box_items)
        text = "\n".join(item.text for item in sorted_items).strip()
        fallback_messages = [
            f"{self._provider_label(provider)} 不可用，已回退"
            for provider, _error in errors
            if provider != active_provider
        ]
        message = "；".join(fallback_messages)
        return OcrResult(text, "rapidocr", bool(text), message, tuple(sorted_items))

    def recognize_number(self, image_path: Path) -> OcrResult:
        result = self.recognize(image_path)
        if not result.ok:
            return result
        numbers = re.findall(r"\d+(?:[.,]\d+)?", result.text)
        text = "\n".join(numbers)
        return OcrResult(text, result.engine, bool(text), result.message, result.boxes)
