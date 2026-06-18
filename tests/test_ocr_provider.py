from pathlib import Path
from types import SimpleNamespace

from poe2_price_tracker.ocr import RapidOcr


class FakeRapidOCR:
    created_params: list[dict] = []

    def __init__(self, params):
        self.params = dict(params)
        self.created_params.append(self.params)

    def __call__(self, *_args, **_kwargs):
        if self.params.get("EngineConfig.onnxruntime.use_dml"):
            raise UnicodeDecodeError("utf-8", b"\xb2", 0, 1, "invalid start byte")
        return SimpleNamespace(txts=("神圣石",), scores=(0.98,), boxes=None)


def _install_fake_rapidocr(monkeypatch):
    FakeRapidOCR.created_params = []
    monkeypatch.setitem(
        __import__("sys").modules,
        "rapidocr",
        SimpleNamespace(RapidOCR=FakeRapidOCR),
    )


def test_auto_provider_prefers_cuda_before_directml(monkeypatch):
    _install_fake_rapidocr(monkeypatch)
    monkeypatch.setattr(
        RapidOcr,
        "available_providers",
        staticmethod(lambda: ("CUDAExecutionProvider", "DmlExecutionProvider", "CPUExecutionProvider")),
    )

    result = RapidOcr(execution_provider="auto").recognize(Path("dummy.png"))

    assert result.ok
    assert FakeRapidOCR.created_params[0]["EngineConfig.onnxruntime.use_cuda"] is True
    assert "EngineConfig.onnxruntime.use_dml" not in FakeRapidOCR.created_params[0]


def test_auto_provider_falls_back_to_cpu_when_directml_fails(monkeypatch):
    _install_fake_rapidocr(monkeypatch)
    monkeypatch.setattr(
        RapidOcr,
        "available_providers",
        staticmethod(lambda: ("DmlExecutionProvider", "CPUExecutionProvider")),
    )

    result = RapidOcr(execution_provider="auto").recognize(Path("dummy.png"))

    assert result.ok
    assert result.text == "神圣石"
    assert "GPU DirectML 不可用" in result.message
    assert FakeRapidOCR.created_params[0]["EngineConfig.onnxruntime.use_dml"] is True
    assert "EngineConfig.onnxruntime.use_dml" not in FakeRapidOCR.created_params[1]
