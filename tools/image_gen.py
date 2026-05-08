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


def _find_mflux_python() -> str | None:
    """mflux 를 import 가능한 Python 절대 경로를 찾는다.

    1) sys.executable — 데몬을 띄운 인터프리터. 보통 가장 정확.
       단 PyInstaller bootloader 일 경우 -c 인자를 못 받아 실패하므로 제외.
    2) 흔한 venv 경로들(현재 cwd, 사용자 홈 등) 의 python3.

    각 후보에 대해 `python -c "import mflux"` 로 검증한다 (timeout 5s).
    """
    import os
    import subprocess
    import sys

    candidates: list[str] = []

    # (1) sys.executable — PyInstaller frozen 환경이면 _MEIPASS 가 set 됨
    if not getattr(sys, "frozen", False) and "_MEIPASS" not in dir(sys):
        candidates.append(sys.executable)

    # (2) 흔한 venv 위치 — onboarding 모달이 만든 ~/.raphael/tools/venv 가 최우선.
    home = Path.home()
    cwd = Path(os.getcwd())
    for p in [
        home / ".raphael" / "tools" / "venv" / "bin" / "python3",
        cwd / ".venv" / "bin" / "python3",
        home / "Raphael" / ".venv" / "bin" / "python3",
        Path("/Volumes/TechD/claude_projects/Raphael/.venv/bin/python3"),
        Path("/opt/homebrew/bin/python3"),
        Path("/usr/local/bin/python3"),
    ]:
        if p.exists() and str(p) not in candidates:
            candidates.append(str(p))

    for cand in candidates:
        try:
            r = subprocess.run(
                [cand, "-c", "import mflux"],
                capture_output=True,
                timeout=5,
            )
            if r.returncode == 0:
                return cand
        except Exception:
            continue
    return None


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
        """mflux-generate entry-point 을 Python -c 로 직접 호출.

        wrapper script(.venv/bin/mflux-generate) 의 shebang 이 옛 venv 경로를 가리켜
        깨진 케이스(예: 프로젝트 디렉토리 이동 후)와 PyInstaller 환경 모두를 우회하기
        위해, mflux 를 import 가능한 Python 인터프리터를 찾아 entry-point 의 main()
        을 -c 로 호출한다.
        """
        import asyncio
        import subprocess
        import sys

        py = _find_mflux_python()
        if not py:
            return {
                "ok": False,
                "error": (
                    "mflux 를 import 가능한 Python 인터프리터를 찾지 못했습니다.\n"
                    "원인 후보:\n"
                    "  1) mflux 미설치 — pip install mflux\n"
                    "  2) venv 이동 후 wrapper 의 shebang 이 옛 경로를 가리킴 — \n"
                    "     pip install --force-reinstall mflux 로 shebang 재생성\n"
                    "  3) 데스크톱 .app 의 PyInstaller raphaeld 안에는 mflux 가 번들되지 않음 — \n"
                    "     dev 모드(raphael web / CLI) 에서 사용하거나 시스템 venv 에 설치\n"
                    "추가로 huggingface.co 에서 FLUX.1-schnell 접근 승인 + HUGGINGFACE_TOKEN 등록 필요."
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

        # python -c "..." 로 wrapper shebang 우회. sys.argv[0] 만 mflux-generate 로
        # 위장해서 mflux 의 argparse usage 메시지가 깔끔하게 나오도록.
        launcher = (
            "import sys; sys.argv[0] = 'mflux-generate'; "
            "from mflux.models.flux.cli.flux_generate import main; "
            "main()"
        )
        cmd = [
            py, "-c", launcher,
            "--model", "black-forest-labs/FLUX.1-schnell",
            "--quantize", "4",
            "--prompt", prompt,
            "--width", str(w),
            "--height", str(h),
            "--steps", "2",
            "--seed", str(seed),
            "--output", str(out_path),
        ]
        logger.info(f"mflux-generate (via {py}): {prompt[:60]}... ({w}x{h})")

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

        # 실제 호출 가능 여부는 _find_mflux_python() 으로 검증 — 깨진 wrapper
        # 가 PATH 에 있어도 가짜 True 가 나오지 않도록.
        has_mflux = _find_mflux_python() is not None
        has_mlx_image = False
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
