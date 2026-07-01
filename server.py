import os
import urllib.request
import tempfile
import uvicorn
from typing import Optional
from fastmcp import FastMCP
from starlette.responses import JSONResponse
import higgsfield_client

# ── Auth ──────────────────────────────────────────────────────────────────────
MCP_TOKEN = os.environ.get("MCP_TOKEN", "")

class BearerAuth:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if MCP_TOKEN and scope["type"] == "http":
            headers = {k: v for k, v in scope.get("headers", [])}
            auth = headers.get(b"authorization", b"").decode()
            if auth != f"Bearer {MCP_TOKEN}":
                resp = JSONResponse({"error": "Unauthorized"}, status_code=401)
                await resp(scope, receive, send)
                return
        await self.app(scope, receive, send)

# ── MCP сервер ────────────────────────────────────────────────────────────────
mcp = FastMCP("higgsfield-mcp")


@mcp.tool
def list_models() -> dict:
    """Список доступных моделей Higgsfield для генерации изображений и видео."""
    return {
        "image": [
            "bytedance/seedream/v4/text-to-image",
            "flux-pro/kontext/max/text-to-image",
            "soul-v2/text-to-image",
            "nano-banana-pro/text-to-image",
        ],
        "video": [
            "/v1/image2video/dop        (быстрый image→video, model=dop-turbo)",
            "kling/v3/text-to-video     (рекомендуется по умолчанию)",
            "seedance/v2/text-to-video  (плавное движение)",
            "veo3/text-to-video         (кинематографика)",
            "sora/v2/text-to-video      (OpenAI Sora 2)",
        ]
    }


@mcp.tool
def generate_image(
    model: str,
    prompt: str,
    resolution: str = "2K",
    aspect_ratio: str = "16:9",
) -> dict:
    """
    Генерирует изображение через Higgsfield AI.
    Блокирует до завершения генерации, возвращает URL результата.
    
    model: строка из list_models()[image]
    prompt: описание на английском
    resolution: 2K | 4K | 1K
    aspect_ratio: 16:9 | 9:16 | 1:1 | 4:3
    """
    result = higgsfield_client.subscribe(
        model,
        arguments={
            "prompt": prompt,
            "resolution": resolution,
            "aspect_ratio": aspect_ratio,
        }
    )
    url = _extract_url(result, "image")
    return {"url": url, "model": model, "prompt": prompt}


@mcp.tool
def generate_video(
    model: str,
    prompt: str,
    input_image_url: Optional[str] = None,
    aspect_ratio: str = "16:9",
    duration: int = 5,
) -> dict:
    """
    Генерирует видео через Higgsfield AI.
    Блокирует до завершения (1-5 минут), возвращает URL видео.
    
    model: строка из list_models()[video]
    prompt: описание на английском
    input_image_url: URL референсного изображения (для image→video)
    duration: длительность в секундах (4-15)
    """
    args = {
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "duration": duration,
    }
    if input_image_url:
        args["input_images"] = [
            {"type": "image_url", "image_url": input_image_url}
        ]

    result = higgsfield_client.subscribe(model, arguments=args)
    url = _extract_url(result, "video")
    return {"url": url, "model": model, "prompt": prompt}


@mcp.tool
def upload_image(image_url: str) -> dict:
    """
    Скачивает изображение по URL (например Telegram) и загружает на хостинг Higgsfield.
    Возвращает постоянный URL, который можно передать в generate_video(input_image_url=...).
    
    Используй перед generate_video, когда есть URL из Telegram.
    """
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        urllib.request.urlretrieve(image_url, tmp_path)
        result = higgsfield_client.upload(tmp_path)
        hosted = result.get("url") or result.get("file_url") or str(result)
        return {"url": hosted}
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


# ── Helpers ───────────────────────────────────────────────────────────────────
def _extract_url(result: dict, kind: str) -> Optional[str]:
    if not isinstance(result, dict):
        return None
    plural = kind + "s"
    return (
        (result.get(plural) or [{}])[0].get("url")
        or result.get("url")
        or (result.get("output") or {}).get("url")
    )


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    asgi_app = mcp.http_app()          # FastMCP → Starlette/ASGI
    protected  = BearerAuth(asgi_app)  # обёртка с проверкой токена
    uvicorn.run(protected, host="0.0.0.0", port=port)