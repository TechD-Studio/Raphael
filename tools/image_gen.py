"""이미지 생성 도구 — MLX Stable Diffusion (로컬) + OpenAI DALL-E 3 (API).

설정:
  tools.image_gen.backend: "local" | "openai" | "auto"
  tools.image_gen.local_model: "stabilityai/stable-diffusion-2-1" (기본)
  tools.image_gen.openai_model: "dall-e-3"
  tools.image_gen.output_dir: "~/.raphael/generated"
  tools.image_gen.default_size: "1024x1024"

auto 모드: OpenAI 키 있으면 openai, 없으면 local.
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger


def _output_dir() -> Path:
    from config.settings import get_settings
    cfg = (get_settings().get("tools") or {}).get("image_gen") or {}
    d = Path(cfg.get("output_dir", "~/.raphael/generated")).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _get_config() -> dict:
    from config.settings import get_settings
    return (get_settings().get("tools") or {}).get("image_gen") or {}


def _resolve_backend(cfg: dict) -> str:
    backend = cfg.get("backend", "auto")
    if backend == "auto":
        from core.secrets import get_secret
        if get_secret("OPENAI_API_KEY"):
            return "openai"
        return "local"
    return backend


@dataclass
class ImageGenTool:
    """이미지 생성 도구."""

    async def generate(
        self,
        prompt: str,
        negative_prompt: str = "",
        size: str = "",
        backend: str | None = None,
    ) -> dict:
        cfg = _get_config()
        be = backend or _resolve_backend(cfg)
        size = size or cfg.get("default_size", "1024x1024")

        if be == "openai":
            return await self._generate_openai(prompt, size, cfg)
        else:
            return await self._generate_local(prompt, negative_prompt, size, cfg)

    async def _generate_openai(self, prompt: str, size: str, cfg: dict) -> dict:
        """OpenAI DALL-E 3 API."""
        import httpx
        from core.secrets import get_secret

        api_key = get_secret("OPENAI_API_KEY")
        if not api_key:
            return {"ok": False, "error": "OPENAI_API_KEY 미설정. 설정 > 서버 > 시크릿에서 등록하세요."}

        model = cfg.get("openai_model", "dall-e-3")
        valid_sizes = {"1024x1024", "1024x1792", "1792x1024"}
        if size not in valid_sizes:
            size = "1024x1024"

        try:
            async with httpx.AsyncClient(timeout=60) as c:
                resp = await c.post(
                    "https://api.openai.com/v1/images/generations",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "prompt": prompt,
                        "n": 1,
                        "size": size,
                        "response_format": "b64_json",
                    },
                )
                resp.raise_for_status()
                data = resp.json()

            b64 = data["data"][0]["b64_json"]
            revised = data["data"][0].get("revised_prompt", "")
            ts = int(time.time())
            out_path = _output_dir() / f"dalle_{ts}.png"
            out_path.write_bytes(base64.b64decode(b64))

            return {
                "ok": True,
                "backend": "openai",
                "model": model,
                "path": str(out_path),
                "data_url": f"data:image/png;base64,{b64[:100]}...",
                "revised_prompt": revised,
                "size": size,
            }
        except httpx.HTTPStatusError as e:
            return {"ok": False, "error": f"OpenAI API 오류: {e.response.status_code} {e.response.text[:200]}"}
        except Exception as e:
            return {"ok": False, "error": f"DALL-E 생성 실패: {e}"}

    async def _generate_local(self, prompt: str, negative_prompt: str, size: str, cfg: dict) -> dict:
        """mflux-generate CLI로 FLUX.1 이미지 생성."""
        import asyncio
        import shutil
        import subprocess

        mflux_bin = shutil.which("mflux-generate")
        if not mflux_bin:
            import sys
            venv_bin = Path(sys.executable).parent / "mflux-generate"
            if venv_bin.exists():
                mflux_bin = str(venv_bin)
        if not mflux_bin:
            return {
                "ok": False,
                "error": (
                    "mflux 미설치. pip install mflux 로 설치하세요.\n"
                    "설치 후 HuggingFace 인증도 필요합니다:\n"
                    "  1. huggingface.co에서 FLUX.1-schnell 접근 승인\n"
                    "  2. 설정 > 서버 > 이미지 생성에서 HUGGINGFACE_TOKEN 입력"
                ),
            }

        try:
            w, h = (int(x) for x in size.split("x"))
        except Exception:
            w, h = 512, 512
        w = min(w, 1024)
        h = min(h, 1024)

        ts = int(time.time())
        out_path = _output_dir() / f"flux_{ts}.png"
        seed = ts % 100000

        cmd = [
            mflux_bin,
            "--model", "black-forest-labs/FLUX.1-schnell",
            "--quantize", "4",
            "--prompt", prompt,
            "--width", str(w),
            "--height", str(h),
            "--steps", "2",
            "--seed", str(seed),
            "--output", str(out_path),
        ]
        logger.info(f"mflux-generate: {prompt[:60]}... ({w}x{h})")

        def _run():
            try:
                import os as _os
                env = _os.environ.copy()
                try:
                    from core.secrets import get_secret
                    hf = get_secret("HUGGINGFACE_TOKEN")
                    if hf:
                        env["HF_TOKEN"] = hf
                        env["HUGGING_FACE_HUB_TOKEN"] = hf
                except Exception:
                    pass
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=300, env=env)
                if r.returncode != 0:
                    return {"ok": False, "error": f"mflux 실패 (rc={r.returncode}): {r.stderr[:300]}"}
                if out_path.exists():
                    return {
                        "ok": True,
                        "backend": "local",
                        "model": "flux.1-schnell-4bit",
                        "path": str(out_path),
                    }
                return {"ok": False, "error": f"이미지 파일 미생성. stdout: {r.stdout[:200]}"}
            except subprocess.TimeoutExpired:
                return {"ok": False, "error": "mflux 타임아웃 (300초)"}
            except Exception as e:
                return {"ok": False, "error": f"mflux 실행 실패: {e}"}

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _run)
        if result.get("ok") and result.get("path"):
            p = Path(result["path"])
            if p.exists():
                b64 = base64.b64encode(p.read_bytes()).decode("ascii")
                result["data_url"] = f"data:image/png;base64,{b64[:100]}..."
        return result

    def list_backends(self) -> list[dict]:
        """사용 가능한 백엔드 목록."""
        from core.secrets import get_secret
        backends = []

        has_mflux = False
        has_mlx_image = False
        if shutil.which("mflux-generate"):
            has_mflux = True
        else:
            import sys
            if (Path(sys.executable).parent / "mflux-generate").exists():
                has_mflux = True
            else:
                try:
                    import mflux  # noqa
                    has_mflux = True
                except ImportError:
                    pass
        try:
            import mlx_image  # noqa
            has_mlx_image = True
        except ImportError:
            pass

        backends.append({
            "id": "local",
            "name": "로컬 (MLX)",
            "available": has_mflux or has_mlx_image,
            "model": "flux.1-schnell" if has_mflux else ("stable-diffusion" if has_mlx_image else "미설치"),
            "cost": "무료",
        })
        backends.append({
            "id": "openai",
            "name": "OpenAI DALL-E 3",
            "available": bool(get_secret("OPENAI_API_KEY")),
            "model": "dall-e-3",
            "cost": "~$0.04/장",
        })
        return backends
