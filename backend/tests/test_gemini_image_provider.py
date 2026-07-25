from app.services.image_provider import (
    GEMINI_MODEL_CAPABILITIES,
    normalize_gemini_aspect_ratio,
    normalize_gemini_image_size,
)


def test_current_nano_banana_models_are_available():
    assert set(GEMINI_MODEL_CAPABILITIES) == {
        "gemini-3.1-flash-image",
        "gemini-3.1-flash-lite-image",
        "gemini-3-pro-image",
        "gemini-2.5-flash-image",
    }


def test_model_specific_image_sizes_are_enforced():
    assert normalize_gemini_image_size("gemini-3.1-flash-image", "0.5K") == "0.5K"
    assert normalize_gemini_image_size("gemini-3.1-flash-image", "4K") == "4K"
    assert normalize_gemini_image_size("gemini-3-pro-image", "2K") == "2K"
    assert normalize_gemini_image_size("gemini-3.1-flash-lite-image", "4K") == "1K"
    assert normalize_gemini_image_size("gemini-2.5-flash-image", "high") == "1K"
    assert normalize_gemini_image_size("gemini-3.1-flash-image", "invalid") == "1K"


def test_model_specific_aspect_ratios_are_enforced():
    assert normalize_gemini_aspect_ratio("gemini-3.1-flash-image", "1:8") == "1:8"
    assert normalize_gemini_aspect_ratio("gemini-3-pro-image", "1:8") == "1:1"
    assert normalize_gemini_aspect_ratio("gemini-3-pro-image", "21:9") == "21:9"


def test_interactions_request_uses_jpeg_and_selected_size(tmp_path):
    import base64
    from io import BytesIO

    from PIL import Image

    from app.services.image_provider import GeminiImageProvider

    image_buffer = BytesIO()
    Image.new("RGB", (8, 8), "white").save(image_buffer, format="JPEG")
    encoded = base64.b64encode(image_buffer.getvalue()).decode("ascii")
    calls = []

    class OutputImage:
        data = encoded

    class Interaction:
        output_image = OutputImage()
        usage_metadata = None
        usage = None

    class Interactions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return Interaction()

    class Client:
        interactions = Interactions()

    provider = object.__new__(GeminiImageProvider)
    provider.client = Client()
    provider.api_key = "test"

    source = tmp_path / "source.png"
    Image.new("RGB", (8, 8), "black").save(source)
    raw, _usage = provider._one_interaction_sync(
        "prompt",
        [source],
        "gemini-3.1-flash-image",
        "4:5",
        "4K",
    )

    assert raw == image_buffer.getvalue()
    assert calls[0]["response_format"] == {
        "type": "image",
        "mime_type": "image/jpeg",
        "aspect_ratio": "4:5",
        "image_size": "4K",
    }
    assert calls[0]["input"][1]["mime_type"] == "image/png"
