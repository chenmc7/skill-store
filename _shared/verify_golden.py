#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_golden.py —— 跨机一致性验证（黄金样例 + 环境 12 项检查）

用法：
  python _shared/verify_golden.py

**能验证什么、不能验证什么（务必先读）**：
  · 能验证：工具链（转写解析/幻觉检测/术语订正/粒度判定/时长累加）＋ 环境（LaTeX/字体/poppler）
    ＋ 确定性硬指标；
  · **不能验证**：讲义正文的质量与文风——那取决于底层大模型。
    跨机一致性只能保证"下限"（知识点不丢、体例不破、能编译），不能保证"文风一致"。
"""
from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "_tools"))
import transcript_kit as tk  # noqa: E402

SAMPLE = ROOT / "assets" / "samples" / "sample_transcript.md"
EXPECT = json.loads((ROOT / "assets" / "samples" / "expected.json").read_text(encoding="utf-8"))["expect"]

results = []


def check(name: str, ok: bool, detail: str = "", hard: bool = True):
    results.append((name, ok, detail, hard))
    mark = "✅" if ok else ("❌" if hard else "⚠️")
    print(f"  {mark} {name}" + (f" —— {detail}" if detail else ""))


def has_exe(name: str) -> bool:
    return bool(shutil.which(name)) or any(
        (Path(d) / f"{name}.exe").exists() or (Path(d) / name).exists()
        for d in ["D:/texlive/2025/bin/windows", "/usr/bin", "/usr/local/bin", "/Library/TeX/texbin"])


def main() -> int:
    print("== 跨机一致性验证（黄金样例） ==\n")
    text = SAMPLE.read_text(encoding="utf-8")
    segs = tk.parse_segments(text)
    with_tc = [s for s in segs if s.tc]

    print("【A. 工具链 · 黄金样例】")
    check("样例可解析", len(segs) > 0, f"{len(segs)} 段")

    tc_lines = sum(1 for l in text.split("\n") if tk.RE_SPEAKER_TC.match(l.strip()))
    layout = "② 时间码段与正文段交替" if tc_lines else "① 一段一码"
    check("结构判定 = 交替式", layout == EXPECT["layout"], layout)

    check("段数与期望一致", len(segs) == EXPECT["segments"],
          f"实际 {len(segs)}／期望 {EXPECT['segments']}")

    secs = [s.sec for s in with_tc]
    mono = all(secs[i] >= secs[i - 1] - 1 for i in range(1, len(secs)))
    check("检出时间码非单调（分段重启）", mono is False, "含 41:10→00:24 重启")

    dur_min = tk.total_duration(secs) / 60
    check("时长按分段累加（非 末−首）", dur_min >= EXPECT["min_duration_minutes"],
          f"{dur_min:.0f} 分钟 ≥ {EXPECT['min_duration_minutes']}")

    flagged = [s for s in segs if tk.classify_segment(s.text)]
    check("幻觉段被抓出", len(flagged) >= EXPECT["min_anomaly_segments"],
          f"{len(flagged)} 段（司法语汇）")

    pairs = tk.load_glossary("investment", ROOT / "assets")
    hits = sum(1 for w, _ in pairs if w in text)
    check("术语表命中 ≥ 期望", hits >= EXPECT["glossary_min_hits"],
          f"{hits} 条（{EXPECT['glossary_min_hits']} 期望）")

    g = tk.granularity_of(segs)
    check("粒度判定正确", EXPECT["granularity"] in g, g)

    print("\n【B. 环境】")
    check("xelatex 可用", has_exe("xelatex"), "TeX Live")
    kp = subprocess.run(["kpsewhich", "ctexart.cls"], capture_output=True, text=True) \
        if has_exe("kpsewhich") else None
    check("ctexart.cls 可用（中文排版）", bool(kp and kp.stdout.strip()), "ctex 宏包")

    cfg_path = ROOT / "_shared" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
    font = cfg.get("fonts", {}).get("main", "")
    check("中文字体已配置", bool(font), font or "未配置（跑 doctor.py --autodetect）", hard=False)

    check("poppler（pdftotext/pdftoppm）", has_exe("pdftotext") and has_exe("pdftoppm"),
          "课件逐页核对用", hard=False)

    hard_fail = [r for r in results if not r[1] and r[3]]
    soft_fail = [r for r in results if not r[1] and not r[3]]
    print(f"\n== 结论 ==")
    print(f"  通过 {sum(1 for r in results if r[1])}/{len(results)}"
          f"｜硬指标失败 {len(hard_fail)}｜软指标失败 {len(soft_fail)}")
    if hard_fail:
        print("  ❌ 硬指标未过：" + "、".join(r[0] for r in hard_fail))
    if soft_fail:
        print("  ⚠️ 软指标未过：" + "、".join(r[0] for r in soft_fail))
    if not hard_fail:
        print("  ✅ 工具链与环境一致性通过——工具层的跨机行为与参考机相同")
    print("\n  ⓘ 提醒：本脚本**不验证讲义正文质量**（那取决于底层大模型）。"
          "跨机一致性只保证『下限』：知识点不丢、体例不破、能编译。")
    return 1 if hard_fail else 0


if __name__ == "__main__":
    sys.exit(main())
