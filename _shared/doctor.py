#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doctor.py —— 讲义 skill 包的环境自检与自动探测

用法：
  python _shared/doctor.py                 # 只体检
  python _shared/doctor.py --autodetect    # 体检并把探测结果写回 config.json

检查项：Python 版本 / xelatex / ctex 宏包 / 中文字体 / pdftotext+pdftoppm /
        可选 Python 包（pypdf, pypdfium2, openpyxl）
"""
from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CFG = ROOT / "_shared" / "config.json"
FONT_BY_PLATFORM = {
    "win32": "Microsoft YaHei",
    "darwin": "PingFang SC",
    "linux": "Noto Sans CJK SC",
}
TEXLIVE_CANDIDATES = [
    r"D:/texlive/2025", r"C:/texlive/2025", "/usr/local/texlive/2025",
    r"D:/texlive/2024", "/usr/local/texlive/2024", "/Library/TeX/texbin",
]
POPPLER_CANDIDATES = [
    r"D:/texlive/2025/bin/windows", "/usr/bin", "/usr/local/bin", "/opt/homebrew/bin",
]


def load_cfg() -> dict:
    if CFG.exists():
        try:
            return json.loads(CFG.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"paths": {}, "fonts": {}, "params": {}}


def save_cfg(cfg: dict) -> None:
    CFG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def run(cmd, **kw):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, **kw)
    except Exception:
        return None


def find_exe(name: str, extra_dirs: list) -> str:
    p = shutil.which(name)
    if p:
        return p
    for d in extra_dirs:
        cand = Path(d) / (name + (".exe" if platform.system() == "Windows" else ""))
        if cand.exists():
            return str(cand)
    return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--autodetect", action="store_true", help="把探测结果写回 config.json")
    a = ap.parse_args()
    cfg = load_cfg()
    ok, warn, fail = [], [], []

    # 1 Python
    v = sys.version_info
    (ok if v >= (3, 9) else fail).append(f"Python {v.major}.{v.minor}.{v.micro}"
                                         + ("" if v >= (3, 9) else "（需 ≥3.9）"))

    # 2 xelatex
    texdirs = [cfg.get("paths", {}).get("texlive", "")] + TEXLIVE_CANDIDATES
    texdirs = [d for d in texdirs if d]
    xelatex = find_exe("xelatex", texdirs)
    if xelatex:
        r = run([xelatex, "--version"])
        ok.append("xelatex" + (f"（{r.stdout.splitlines()[0][:40]}）" if r and r.stdout else ""))
    else:
        fail.append("xelatex 未找到 —— 请安装 TeX Live（含 ctex）并加入 PATH，或填 config.json 的 paths.texlive")

    # 3 ctex
    if xelatex:
        r = run(["kpsewhich", "ctexart.cls"])
        if r and r.stdout.strip():
            ok.append("ctexart.cls（ctex 宏包）")
        else:
            fail.append("ctexart.cls 未找到 —— 需 `tlmgr install ctex`")

    # 4 中文字体
    font = cfg.get("fonts", {}).get("main") or FONT_BY_PLATFORM.get(sys.platform, "")
    if sys.platform == "win32":
        ok.append(f"中文字体（Windows 名）{font}")
    else:
        r = run(["fc-list", ":lang=zh"])
        if r and r.stdout.strip():
            ok.append(f"中文字体可用（建议 mainfont={font}）")
        else:
            warn.append(f"未检测到中文字体 —— 请安装（{font}），否则 PDF 会缺字")

    # 5 poppler
    dirs = [cfg.get("paths", {}).get("poppler", "")] + POPPLER_CANDIDATES
    dirs = [d for d in dirs if d]
    pdftotext = find_exe("pdftotext", dirs)
    pdftoppm = find_exe("pdftoppm", dirs)
    if pdftotext and pdftoppm:
        ok.append("poppler（pdftotext / pdftoppm）")
    else:
        warn.append("pdftotext / pdftoppm 缺失 —— 课件逐页核对与渲染受影响（可用 pypdfium2 降级）")

    # 6 可选 Python 包
    for mod in ("pypdf", "pypdfium2", "openpyxl"):
        try:
            __import__(mod)
            ok.append(f"可选包 {mod}")
        except Exception:
            warn.append(f"可选包 {mod} 未安装（部分工序会降级）")

    print("== 讲义 skill 包 · 环境自检 ==")
    print(f"平台：{platform.system()} {platform.release()}｜包根目录：{ROOT}\n")
    for t, items in (("✅ 通过", ok), ("⚠️ 提醒", warn), ("❌ 缺失", fail)):
        print(f"{t}")
        for i in items or ["（无）"]:
            print(f"   · {i}")
        print()

    if a.autodetect:
        p = cfg.setdefault("paths", {})
        f = cfg.setdefault("fonts", {})
        if xelatex:
            p["texlive"] = str(Path(xelatex).parent)
        if pdftotext:
            p["poppler"] = str(Path(pdftotext).parent)
        if not f.get("main"):
            f["main"] = FONT_BY_PLATFORM.get(sys.platform, "")
        save_cfg(cfg)
        print(f"已写回 {CFG}")

    print("结论：" + ("环境完备，可开工" if not fail else f"有 {len(fail)} 项缺失，请先补齐"))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
