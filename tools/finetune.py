"""파인튜닝 도구 — 옵시디언 → JSONL → QLoRA 학습 → GGUF → Ollama 등록.

사용 흐름:
  1. prepare(): 옵시디언 볼트 → train.jsonl + valid.jsonl
  2. train(): mlx_lm.lora CLI 실행 (SSE 진행률)
  3. build(): mlx_lm.fuse → llama.cpp GGUF → ollama create
"""

from __future__ import annotations

import json
import random
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from loguru import logger


def _ft_dir() -> Path:
    d = Path.home() / ".raphael" / "finetune"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _adapters_dir() -> Path:
    d = _ft_dir() / "adapters"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _data_dir() -> Path:
    d = _ft_dir() / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class FineTuneTool:

    def check_deps(self) -> dict:
        """필수 의존성 확인."""
        return {
            "mlx_lm": shutil.which("mlx_lm.lora") is not None or self._can_import("mlx_lm"),
            "llama_cpp": (Path.home() / "llama.cpp" / "build" / "bin" / "llama-quantize").exists()
                         or shutil.which("llama-quantize") is not None,
            "ollama": shutil.which("ollama") is not None,
        }

    @staticmethod
    def _can_import(name: str) -> bool:
        try:
            __import__(name)
            return True
        except ImportError:
            return False

    def prepare(self, vault_path: str, method: str = "section_qa") -> dict:
        """옵시디언 볼트를 학습 데이터로 변환."""
        vault = Path(vault_path).expanduser()
        if not vault.exists():
            return {"ok": False, "error": f"볼트 경로 없음: {vault}"}

        pairs = []
        md_files = list(vault.rglob("*.md"))
        if not md_files:
            return {"ok": False, "error": "마크다운 파일 없음"}

        for md in md_files:
            try:
                content = md.read_text(encoding="utf-8")
                content = re.sub(r"^---\n.*?\n---\n", "", content, flags=re.DOTALL)
                title = md.stem
                sections = re.split(r"\n(#{1,3} .+)\n", content)

                for i in range(1, len(sections), 2):
                    header = sections[i].strip("# ").strip()
                    body = sections[i + 1].strip() if i + 1 < len(sections) else ""
                    if len(body) > 50:
                        pairs.append({
                            "messages": [
                                {"role": "user", "content": f"{header} ({title})에 대해 설명해줘"},
                                {"role": "assistant", "content": body[:2000]},
                            ]
                        })
            except Exception as e:
                logger.debug(f"파일 처리 실패 {md.name}: {e}")

        if not pairs:
            return {"ok": False, "error": "변환된 Q&A 쌍 없음"}

        random.shuffle(pairs)
        split = max(1, int(len(pairs) * 0.9))
        data_dir = _data_dir()
        train_path = data_dir / "train.jsonl"
        valid_path = data_dir / "valid.jsonl"

        with open(train_path, "w", encoding="utf-8") as f:
            for p in pairs[:split]:
                f.write(json.dumps(p, ensure_ascii=False) + "\n")
        with open(valid_path, "w", encoding="utf-8") as f:
            for p in pairs[split:]:
                f.write(json.dumps(p, ensure_ascii=False) + "\n")

        return {
            "ok": True,
            "total_pairs": len(pairs),
            "train": split,
            "valid": len(pairs) - split,
            "data_dir": str(data_dir),
        }

    def train(
        self,
        base_model: str = "mlx-community/gemma-4-E2B-it-4bit",
        iters: int = 600,
        batch_size: int = 2,
        lora_layers: int = 16,
        learning_rate: float = 1e-4,
    ) -> dict:
        """QLoRA 학습 실행."""
        data_dir = _data_dir()
        if not (data_dir / "train.jsonl").exists():
            return {"ok": False, "error": "학습 데이터 없음. 먼저 '데이터 변환'을 실행하세요."}

        ts = int(time.time())
        adapter_name = f"ft-{ts}"
        adapter_path = _adapters_dir() / adapter_name

        cmd = [
            "python3", "-m", "mlx_lm.lora",
            "--model", base_model,
            "--data", str(data_dir),
            "--train",
            "--batch-size", str(batch_size),
            "--lora-layers", str(lora_layers),
            "--iters", str(iters),
            "--learning-rate", str(learning_rate),
            "--adapter-path", str(adapter_path),
        ]

        logger.info(f"파인튜닝 시작: {' '.join(cmd[:6])}...")
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
            if r.returncode != 0:
                return {"ok": False, "error": f"학습 실패 (rc={r.returncode}): {r.stderr[:500]}"}

            meta = {
                "adapter_name": adapter_name,
                "base_model": base_model,
                "iters": iters,
                "created": time.strftime("%Y-%m-%d %H:%M"),
            }
            (adapter_path / "meta.json").write_text(json.dumps(meta, ensure_ascii=False))

            return {
                "ok": True,
                "adapter_name": adapter_name,
                "adapter_path": str(adapter_path),
                "base_model": base_model,
                "output": r.stdout[-500:] if r.stdout else "",
            }
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "학습 타임아웃 (1시간 초과)"}
        except Exception as e:
            return {"ok": False, "error": f"학습 실행 실패: {e}"}

    def build(self, adapter_name: str, model_name: str = "") -> dict:
        """어댑터 → Ollama 모델 등록."""
        adapter_path = _adapters_dir() / adapter_name
        if not adapter_path.exists():
            return {"ok": False, "error": f"어댑터 없음: {adapter_name}"}

        meta = {}
        meta_path = adapter_path / "meta.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())

        base_model = meta.get("base_model", "")
        if not model_name:
            model_name = f"gemma4-ft-{adapter_name[-6:]}"

        fused_path = _ft_dir() / "fused" / adapter_name
        fused_path.mkdir(parents=True, exist_ok=True)

        # Step 1: fuse
        fuse_cmd = [
            "python3", "-m", "mlx_lm.fuse",
            "--model", base_model,
            "--adapter-path", str(adapter_path),
            "--save-path", str(fused_path),
            "--de-quantize",
        ]
        logger.info(f"fuse: {adapter_name}")
        r = subprocess.run(fuse_cmd, capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            return {"ok": False, "stage": "fuse", "error": r.stderr[:300]}

        # Step 2: GGUF convert
        gguf_path = _ft_dir() / f"{model_name}.gguf"
        convert_script = None
        for p in [
            Path.home() / "llama.cpp" / "convert_hf_to_gguf.py",
            Path("/usr/local/bin/convert_hf_to_gguf.py"),
        ]:
            if p.exists():
                convert_script = str(p)
                break

        if not convert_script:
            return {
                "ok": False,
                "stage": "gguf",
                "error": "llama.cpp convert_hf_to_gguf.py 없음. ~/llama.cpp 에 빌드하세요.",
                "fused_path": str(fused_path),
            }

        conv_cmd = ["python3", convert_script, str(fused_path), "--outfile", str(gguf_path), "--outtype", "f16"]
        r = subprocess.run(conv_cmd, capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            return {"ok": False, "stage": "gguf_convert", "error": r.stderr[:300]}

        # Step 3: quantize
        q_path = _ft_dir() / f"{model_name}-q4km.gguf"
        quantize_bin = shutil.which("llama-quantize") or str(
            Path.home() / "llama.cpp" / "build" / "bin" / "llama-quantize"
        )
        if Path(quantize_bin).exists():
            q_cmd = [quantize_bin, str(gguf_path), str(q_path), "Q4_K_M"]
            r = subprocess.run(q_cmd, capture_output=True, text=True, timeout=600)
            if r.returncode == 0 and q_path.exists():
                gguf_path.unlink(missing_ok=True)
                gguf_path = q_path

        # Step 4: Ollama create
        modelfile = _ft_dir() / f"Modelfile-{model_name}"
        modelfile.write_text(
            f'FROM {gguf_path}\n'
            f'PARAMETER temperature 0.3\n'
            f'PARAMETER top_p 0.9\n'
            f'PARAMETER stop "<end_of_turn>"\n'
            f'SYSTEM "당신은 사용자의 개인 지식으로 학습된 Raphael 어시스턴트입니다."\n'
        )
        ollama_cmd = ["ollama", "create", model_name, "-f", str(modelfile)]
        r = subprocess.run(ollama_cmd, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            return {"ok": False, "stage": "ollama", "error": r.stderr[:300], "gguf_path": str(gguf_path)}

        return {
            "ok": True,
            "model_name": model_name,
            "gguf_path": str(gguf_path),
            "adapter": adapter_name,
            "base_model": base_model,
        }

    def list_models(self) -> list[dict]:
        """등록된 파인튜닝 어댑터 목록."""
        out = []
        for d in sorted(_adapters_dir().iterdir()):
            if not d.is_dir():
                continue
            meta_path = d / "meta.json"
            meta = {}
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text())
                except Exception:
                    pass
            out.append({
                "name": d.name,
                "base_model": meta.get("base_model", ""),
                "iters": meta.get("iters", 0),
                "created": meta.get("created", ""),
                "path": str(d),
            })
        return out

    def delete(self, adapter_name: str) -> dict:
        """어댑터 삭제."""
        adapter_path = _adapters_dir() / adapter_name
        if adapter_path.exists():
            shutil.rmtree(adapter_path)
        return {"ok": True, "deleted": adapter_name}
