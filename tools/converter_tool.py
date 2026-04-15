"""파일 변환 — 마크다운 → HTML, CSV → 차트, 이미지 리사이즈."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from tools.path_guard import check_path


class ConverterTool:
    def md_to_html(self, src: str, dst: str = "") -> str:
        src_p = check_path(src)
        if not dst:
            dst = str(src_p.with_suffix(".html"))
        dst_p = check_path(dst)
        try:
            import markdown
            html = markdown.markdown(
                src_p.read_text(encoding="utf-8"),
                extensions=["fenced_code", "tables"],
            )
        except ImportError:
            return "markdown 라이브러리 미설치 (pip install markdown)"
        full = f"<!DOCTYPE html>\n<html><head><meta charset='utf-8'></head><body>\n{html}\n</body></html>\n"
        dst_p.write_text(full, encoding="utf-8")
        return f"HTML 생성: {dst_p}"

    def md_to_pdf(self, src: str, dst: str = "") -> str:
        src_p = check_path(src)
        if not dst:
            dst = str(src_p.with_suffix(".pdf"))
        dst_p = check_path(dst)
        # 우선 pandoc 시도
        if shutil.which("pandoc"):
            r = subprocess.run(
                ["pandoc", str(src_p), "-o", str(dst_p)],
                capture_output=True, text=True
            )
            if r.returncode == 0:
                return f"PDF 생성 (pandoc): {dst_p}"
            return f"pandoc 실패: {r.stderr.strip()}"
        # weasyprint fallback
        try:
            from weasyprint import HTML
            html_path = self.md_to_html(src, str(dst_p.with_suffix(".html")))
            HTML(filename=html_path.split(": ")[-1]).write_pdf(str(dst_p))
            return f"PDF 생성 (weasyprint): {dst_p}"
        except ImportError:
            return "PDF 변환 도구 없음 (brew install pandoc 또는 pip install weasyprint)"

    def csv_to_chart(self, src: str, dst: str = "", x: str = "", y: str = "") -> str:
        src_p = check_path(src)
        if not dst:
            dst = str(src_p.with_suffix(".png"))
        dst_p = check_path(dst)
        try:
            import pandas as pd
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ImportError:
            return "pandas/matplotlib 미설치"
        df = pd.read_csv(src_p)
        x = x or df.columns[0]
        y = y or df.columns[1]
        df.plot(x=x, y=y)
        plt.tight_layout()
        plt.savefig(dst_p)
        plt.close()
        return f"차트 생성: {dst_p}"

    def image_resize(self, src: str, width: int, dst: str = "") -> str:
        src_p = check_path(src)
        if not dst:
            dst = str(src_p.parent / f"resized_{src_p.name}")
        dst_p = check_path(dst)
        try:
            from PIL import Image
        except ImportError:
            return "Pillow 미설치"
        img = Image.open(src_p)
        ratio = width / img.width
        new_h = int(img.height * ratio)
        img.resize((width, new_h)).save(dst_p)
        return f"리사이즈됨: {dst_p} ({width}x{new_h})"
