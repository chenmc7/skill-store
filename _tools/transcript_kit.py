#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""transcript_kit.py —— 课堂录音转写处理工具箱（十道工序）

配套 skill：business-lecture-orchestrator「录音处理」节
每条规则的来源与踩过的坑，都写在对应函数的 docstring 里。

用法：
  python transcript_kit.py probe    <文件> [--json]                结构探明
  python transcript_kit.py extract  <文件> [--out 输出.txt]         统一抽取
  python transcript_kit.py detect   <文件> [--json]                幻觉/异常段检测
  python transcript_kit.py glossary <文件> --course investment [--out 输出.md]
  python transcript_kit.py merge    <文件> [--out 输出.md]          粒度合并
  python transcript_kit.py compare  <文件A> <文件B>                 同课判定
  python transcript_kit.py split    <文件> --cut HH:MM:SS --left A.md --right B.md
  python transcript_kit.py quality  <文件> [--json]                质量报告
  python transcript_kit.py index    <文件> [--out index.md]         段号索引
  python transcript_kit.py verify   <讲义索引.md> <转写文件>        时间码对账
  python transcript_kit.py selftest                              内置自检

依赖：Python 3.9+ 标准库。PDF 抽取可选依赖 pypdfium2（缺失时给出提示）。
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
import unicodedata
import zipfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ----------------------------------------------------------------------------
# 常量与词表
# ----------------------------------------------------------------------------

# 幻觉黑名单：2026-10-02 世界发展 lec2 实测，转写工具在无法识别英文讲授时
# 会生成整段司法语汇（「上诉人／被上诉人／原告／被告／诉讼请求」），该课 71% 段落为幻觉。
HALLUCINATION_TERMS = [
    "上诉人", "被上诉人", "原告", "被告", "诉讼请求", "本院认为", "判决如下",
    "驳回", "开庭", "法庭", "证人", "辩护人", "审判长", "起诉", "受理费",
    "一审", "二审", "再审", "裁定", "合议庭", "诉讼费", "委托代理人",
]

# 说话人 + 一位数字 + 时间码 的粘连式（说话人号只占 1 位数字）
# 反面教训：用贪婪的 (\d+) 会把「说话人210:36」读成「说话人 21 + 0:36」（实为 10:36），
# 于是时间戳整体错乱且表面上仍像正常时间。单调性是唯一可靠的验伪手段。
# 2026-10-10 补充：世界发展两份转写用「发言人1　01:06」（全角空格），必须一并支持。
RE_SPEAKER_TC = re.compile(r"^(?:说话人|发言人|Speaker)\s*(\d)[\s\u3000]*(\d{1,2}:\d{2}(?::\d{2})?)$")
# markdown 形式：### [000] 00:09 (S1)
RE_MD_TC = re.compile(r"^#{1,6}\s*\[(\d+)\]\s*(\d{1,2}:\d{2}(?::\d{2})?)\s*(?:\(S(\d)\))?\s*$")
# 行内任意时间码
RE_ANY_TC = re.compile(r"(\d{1,2}:\d{2}(?::\d{2})?)")
RE_CJK = re.compile(r"[\u4e00-\u9fff]")
RE_LATIN = re.compile(r"[A-Za-z]{2,}")

DEFAULT_MERGE_GAP_SEC = 8      # 相邻段起点间隔 ≤8 秒 → 合并（2026-10-02 国际贸易实测）
DEFAULT_MERGE_MAX_CHARS = 300  # 且当前段 <300 字
DEFAULT_GAP_MARK_SEC = 60      # 间隔 >60 秒 → 记「语音间隔」标记
SAME_LECTURE_THRESHOLD = 0.80  # 逐字相似度 ≥0.80 = 同一节课（实测 0.85/0.83）
DIFF_LECTURE_THRESHOLD = 0.15  # ≤0.15 = 完全不同的课（实测 0.08–0.12）

ASSETS = Path(__file__).resolve().parent.parent / "assets"


def load_blacklist(base: Path = ASSETS) -> list:
    """从 assets/hallucination_blacklist.txt 并入额外幻觉词（文件存在时生效）。"""
    p = base / "hallucination_blacklist.txt"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").split("\n"):
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


ALL_TERMS = HALLUCINATION_TERMS + [t for t in load_blacklist() if t not in HALLUCINATION_TERMS]


# ----------------------------------------------------------------------------
# 基础：抽取
# ----------------------------------------------------------------------------

def extract_docx(path: Path) -> str:
    """docx 抽取：直读 word/document.xml。

    来源：2026-10-09 实测——本地 docx 走编辑器通道只能拿到每段 ≤200 字预览，
    必须回落 Python 解析 XML。
    """
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", "replace")
    paras = re.findall(r"<w:p[ >].*?</w:p>", xml, re.S)
    out = []
    for p in paras:
        txt = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", p, re.S))
        txt = (txt.replace("&amp;", "&").replace("&lt;", "<")
                  .replace("&gt;", ">").replace("&quot;", '"'))
        out.append(txt)
    return "\n".join(out)


def extract_pdf(path: Path) -> str:
    """PDF 抽取：优先 pypdfium2，退化到外部 pdftotext。"""
    try:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(str(path))
        return "\n".join(page.get_textpage().get_text_range() for page in doc)
    except Exception:
        pass
    import subprocess
    for exe in ("pdftotext",):
        try:
            r = subprocess.run([exe, "-layout", str(path), "-"], capture_output=True)
            if r.returncode == 0:
                return r.stdout.decode("utf-8", "replace")
        except FileNotFoundError:
            continue
    raise RuntimeError("无法抽取 PDF：请安装 pypdfium2（pip install pypdfium2）或 poppler 的 pdftotext")


def extract(path: Path) -> str:
    """按扩展名分派抽取。"""
    suf = path.suffix.lower()
    if suf == ".docx":
        return extract_docx(path)
    if suf == ".pdf":
        return extract_pdf(path)
    if suf in (".txt", ".md", ".srt", ".vtt"):
        return path.read_text(encoding="utf-8", errors="replace")
    if suf == ".doc":
        raise RuntimeError("旧版 .doc 请先另存为 .docx")
    raise RuntimeError(f"不支持的文件类型：{suf}")


# ----------------------------------------------------------------------------
# 基础：解析为段
# ----------------------------------------------------------------------------

def tc_to_sec(tc: str) -> int:
    parts = [int(x) for x in tc.split(":")]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0]


def sec_to_tc(sec: int) -> str:
    h, rem = divmod(int(sec), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def total_duration(secs: list) -> int:
    """累计时长，遇时间码重启则分段累加。

    来源：2026-10-02 世界发展 lec2——同一次课的两节录音各自从 00:00 计时，
    若直接取 末-首 会得到负值或错值。2026-10-10 由 probe 自动检出该结构后补此逻辑。
    """
    if not secs:
        return 0
    total, group_start, prev = 0, secs[0], secs[0]
    for s in secs[1:]:
        if s < prev - 1:
            total += prev - group_start
            group_start = s
        prev = s
    return total + (prev - group_start)


class Seg:
    __slots__ = ("idx", "tc", "sec", "spk", "text")

    def __init__(self, idx, tc, sec, spk, text):
        self.idx, self.tc, self.sec, self.spk, self.text = idx, tc, sec, spk, text

    def __repr__(self):
        return f"<Seg {self.idx} {self.tc} S{self.spk} {self.text[:18]!r}>"


def parse_segments(text: str) -> list:
    """把任意排布的转写解析为段列表。

    自动适配三种排布（2026-10-02 skill 原文）：
      ① 一段一码：每段形如 `说话人N HH:MM:SS` + 正文
      ② 时间码段 + 正文段交替：相邻段落里偶数段只有“说话人+时间码”，奇数段才是正文
      ③ 纯正文无时间码：按自然段切分
    以及 markdown 形式 `### [000] 00:09 (S1)`。
    """
    lines = [l.rstrip() for l in text.split("\n")]
    segs, pending = [], None
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        m_md = RE_MD_TC.match(line)
        if m_md:
            pending = (m_md.group(2), int(m_md.group(3) or 1))
            continue
        m_sp = RE_SPEAKER_TC.match(line)
        if m_sp:
            pending = (m_sp.group(2), int(m_sp.group(1)))
            continue
        # 纯时间码行（某些工具导出为 "00:09" 单独一行）
        if RE_ANY_TC.fullmatch(line):
            pending = (line, 1)
            continue
        if pending is not None:
            tc, spk = pending
            segs.append(Seg(len(segs), tc, tc_to_sec(tc), spk, line))
            pending = None
        else:
            segs.append(Seg(len(segs), "", -1, 0, line))
    if pending is not None:  # 末尾悬挂的时间码丢弃
        pass
    return segs


def norm_for_compare(text: str) -> str:
    """归一化：去时间码行、说话人标签、全部非中文/数字/字母字符（skill 原文）。"""
    keep = []
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        if RE_SPEAKER_TC.match(line) or RE_MD_TC.match(line) or RE_ANY_TC.fullmatch(line):
            continue
        line = re.sub(r"^#+\s*", "", line)
        for ch in line:
            if unicodedata.category(ch)[0] in ("L", "N") or "\u4e00" <= ch <= "\u9fff":
                keep.append(ch)
    return "".join(keep)


# ----------------------------------------------------------------------------
# 工序 1：probe —— 结构探明
# ----------------------------------------------------------------------------

def cmd_probe(args):
    path = Path(args.file)
    text = extract(path)
    segs = parse_segments(text)
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    tc_lines = sum(1 for l in lines if RE_SPEAKER_TC.match(l) or RE_MD_TC.match(l) or RE_ANY_TC.fullmatch(l))
    with_tc = [s for s in segs if s.tc]

    # 结构判定
    ratio = tc_lines / max(len(lines), 1)
    if not with_tc:
        layout = "③ 纯正文（无时间码）"
    elif 0.4 <= ratio <= 0.6:
        layout = "② 时间码段与正文段交替"
    else:
        layout = "① 一段一码（说话人+时间码 紧邻正文）"

    # 单调性验证：这是拆解正确与否的唯一验伪手段
    secs = [s.sec for s in with_tc]
    breaks = [i for i in range(1, len(secs)) if secs[i] < secs[i - 1] - 1]
    restarts = sum(1 for i in breaks if secs[i] < 60)

    speakers = {}
    for s in with_tc:
        speakers[s.spk] = speakers.get(s.spk, 0) + 1

    rep = {
        "文件": str(path),
        "行数": len(lines),
        "段数": len(segs),
        "带时间码段数": len(with_tc),
        "结构判定": layout,
        "粒度": granularity_of(segs),
        "说话人分布": speakers,
        "时长": sec_to_tc(total_duration(secs)) if secs else "-",
        "时间码单调": not breaks,
        "倒退处": len(breaks),
        "疑似分段重启（回到 0 附近）": restarts,
        "重复时间码": len(secs) - len(set(secs)),
    }
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print(f"== 结构探明：{path.name} ==")
        for k, v in rep.items():
            if k == "文件":
                continue
            print(f"  {k}: {v}")
        if breaks:
            print("  ⚠ 时间码非单调——若为「多文件拼接」，请按组分别处理并在讲义中标注")
            for i in breaks[:5]:
                print(f"     · 第 {with_tc[i-1].idx} 段 {with_tc[i-1].tc} → "
                      f"第 {with_tc[i].idx} 段 {with_tc[i].tc}")
    return 0


# ----------------------------------------------------------------------------
# 工序 2：detect —— 幻觉与异常段检测
# ----------------------------------------------------------------------------

def hallucination_score(text: str) -> tuple:
    hits = sum(text.count(t) for t in ALL_TERMS)
    cjk = len(RE_CJK.findall(text))
    lat = len(RE_LATIN.findall(text))
    return hits, cjk, lat


def classify_segment(text: str) -> list:
    """判定一段是否**幻觉/异常**（不含粒度问题）。

    2026-10-10 用 24 份真实转写回归后两次校准：
      · 司法语汇阈值 ≥2 降到 ≥1——黑名单词在任何学术转写里出现都极不可能是正常内容；
      · 「中英混排异常」收窄为「短中文碎片（≤5 字）夹在英文（≥8 词）中」，
        否则英文授课课的正常段落会被整片误报（世界发展两份就是英文授课）；
      · **不再把「过短碎片」算作异常**——逐小句切分是粒度问题，交给 `probe`/`merge` 处理，
        否则 lecture4_transcript_clean（864 段）会被误报 62% 异常。
    """
    hits, cjk, lat = hallucination_score(text)
    reasons = []
    if hits >= 1:
        reasons.append(f"司法语汇×{hits}")
    if 0 < cjk <= 5 and lat >= 8:
        reasons.append("中英混排异常")
    return reasons


def granularity_of(segs: list) -> str:
    """粒度判定（skill 原文）：≤12 字段落占比 >40% ⇒ 逐小句，必须先合并再用。"""
    if not segs:
        return "-"
    short = sum(1 for s in segs if len(s.text) <= 12)
    ratio = short / len(segs)
    return (f"逐小句（{ratio * 100:.0f}% 段 ≤12 字，**需先 merge**）" if ratio > 0.4
            else f"段落级（{ratio * 100:.0f}% 段 ≤12 字）")


def cmd_detect(args):
    path = Path(args.file)
    segs = parse_segments(extract(path))
    flagged = []
    for s in segs:
        reasons = classify_segment(s.text)
        if reasons:
            flagged.append({"段号": s.idx, "时间码": s.tc, "原因": reasons, "文本": s.text[:60]})

    total = len(segs)
    bad = len(flagged)
    usable = total - bad
    rep = {
        "文件": str(path),
        "总段数": total,
        "疑似幻觉/异常段": bad,
        "可用段": usable,
        "可用率": f"{usable / max(total, 1) * 100:.1f}%",
        "样例": flagged[:8],
        "免责声明": "本检测基于词表与形态规则，只能抓词汇层面的幻觉；"
                    "语义层面的讹写（英文句子被听错成另一个句子）需人工抽查。",
    }
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print(f"== 幻觉/异常检测：{path.name} ==")
        print(f"  总段数 {total}｜疑似异常 {bad}｜可用 {usable}（{rep['可用率']}）")
        for f in flagged[:8]:
            print(f"  · 段{f['段号']} [{f['时间码']}] {'/'.join(f['原因'])}：{f['文本']}")
        if bad:
            print("  → 建议：这些段整段剔除，并在讲义「录音可读范围说明」里披露剔除量")
        print(f"  ⓘ {rep['免责声明']}")
    return 0


# ----------------------------------------------------------------------------
# 工序 3：glossary —— 术语订正
# ----------------------------------------------------------------------------

def load_glossary(course: str, base: Path) -> list:
    p = base / "glossary" / f"{course}.md"
    if not p.exists():
        return []
    pairs = []
    for line in p.read_text(encoding="utf-8").split("\n"):
        m = re.match(r"^\s*[-*|]?\s*`?([^`|→]+?)`?\s*(?:→|->|=>)\s*`?([^`|]+?)`?\s*\|?\s*$", line)
        if m:
            pairs.append((m.group(1).strip(), m.group(2).strip()))
    return pairs


def cmd_glossary(args):
    path = Path(args.file)
    text = extract(path)
    pairs = load_glossary(args.course, Path(__file__).resolve().parent.parent / "assets")
    if not pairs:
        print(f"未找到术语表（course={args.course}）；请在 assets/glossary/ 下创建", file=sys.stderr)
        return 2
    applied = []
    for wrong, right in pairs:
        n = text.count(wrong)
        if n:
            text = text.replace(wrong, right)
            applied.append((wrong, right, n))
    out = Path(args.out) if args.out else path.with_name(path.stem + "_glossary.md")
    out.write_text(text, encoding="utf-8")
    print(f"== 术语订正：{path.name} → {out.name} ==")
    print(f"  应用 {len(applied)} 条，共替换 {sum(a[2] for a in applied)} 处")
    for w, r, n in applied:
        print(f"  · {w} → {r}（{n} 处）")
    return 0


# ----------------------------------------------------------------------------
# 工序 4：merge —— 粒度合并
# ----------------------------------------------------------------------------

def cmd_merge(args):
    path = Path(args.file)
    segs = [s for s in parse_segments(extract(path)) if s.tc]
    if not segs:
        print("无时间码段，跳过合并", file=sys.stderr)
        return 2
    blocks, cur = [], None
    for s in segs:
        if cur is None:
            cur = {"start": s.sec, "end": s.sec, "spk": s.spk, "text": s.text}
            continue
        gap = s.sec - cur["end"]
        if gap <= DEFAULT_MERGE_GAP_SEC and len(cur["text"]) < DEFAULT_MERGE_MAX_CHARS:
            cur["end"] = s.sec
            cur["text"] = cur["text"] + s.text
        else:
            blocks.append(cur)
            if gap > DEFAULT_GAP_MARK_SEC:
                blocks.append({"gap": gap, "start": cur["end"], "end": s.sec})
            cur = {"start": s.sec, "end": s.sec, "spk": s.spk, "text": s.text}
    if cur:
        blocks.append(cur)

    lines = [f"# {path.stem} · 合并稿", "",
             f"- 源文件：`{path.name}`", f"- 原始段数：{len(segs)}｜合并后块数：{sum(1 for b in blocks if 'text' in b)}",
             f"- 合并规则：相邻起点间隔 ≤{DEFAULT_MERGE_GAP_SEC} 秒且当前块 <{DEFAULT_MERGE_MAX_CHARS} 字",
             "- 时间码为**区间**，保留可回溯性", ""]
    n = 0
    for b in blocks:
        if "gap" in b:
            lines.append(f"\n〔语音间隔 {b['gap']} 秒（{sec_to_tc(b['start'])}–{sec_to_tc(b['end'])}）："
                         f"此处多为看图／板书时间，无语音〕\n")
            continue
        n += 1
        lines.append(f"### [{n:03d}] {sec_to_tc(b['start'])}–{sec_to_tc(b['end'])} (S{b['spk']})\n{b['text']}\n")
    out = Path(args.out) if args.out else path.with_name(path.stem + "_clean.md")
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"== 粒度合并：{len(segs)} 段 → {n} 块，写入 {out.name} ==")
    return 0


# ----------------------------------------------------------------------------
# 工序 5：compare —— 同课判定
# ----------------------------------------------------------------------------

def cmd_compare(args):
    a = norm_for_compare(extract(Path(args.file_a)))
    b = norm_for_compare(extract(Path(args.file_b)))
    if not a or not b:
        print("归一化后文本为空，无法比较", file=sys.stderr)
        return 2
    probe = a[:150]
    best = (0.0, 0)
    for off in range(0, max(len(b) - len(probe), 1), 50):
        r = difflib.SequenceMatcher(None, probe, b[off:off + len(probe)]).ratio()
        if r > best[0]:
            best = (r, off)
    off = best[1]
    sims = []
    for i in range(3):
        s1 = a[i * 1500:(i + 1) * 1500]
        s2 = b[off + i * 1500: off + (i + 1) * 1500]
        if s1 and s2:
            sims.append(difflib.SequenceMatcher(None, s1, s2).ratio())
    avg = sum(sims) / max(len(sims), 1)
    verdict = ("同一节课的不同转写版本" if avg >= SAME_LECTURE_THRESHOLD
               else "完全不同的课" if avg <= DIFF_LECTURE_THRESHOLD
               else "不确定（需人工看）")
    print(f"== 同课判定 ==")
    print(f"  A: {Path(args.file_a).name}（归一化 {len(a)} 字）")
    print(f"  B: {Path(args.file_b).name}（归一化 {len(b)} 字）")
    print(f"  对齐偏移: {off} 字｜分段相似度: {['%.3f' % s for s in sims]}｜均值 {avg:.3f}")
    print(f"  判定: {verdict}（阈值：≥{SAME_LECTURE_THRESHOLD} 同课 / ≤{DIFF_LECTURE_THRESHOLD} 异课）")
    if off > 0 and avg >= SAME_LECTURE_THRESHOLD:
        print(f"  → B 在偏移前仍有 {off} 字：B 更全（全本），旧件是被截掉开头的版本；"
              f"引用旧件时间码时需按偏移量换算")
    return 0


# ----------------------------------------------------------------------------
# 工序 6：split —— 跨讲切分
# ----------------------------------------------------------------------------

def cmd_split(args):
    path = Path(args.file)
    text = extract(path)
    segs = [s for s in parse_segments(text) if s.tc]
    cut = tc_to_sec(args.cut)
    # 按「段序」切分：无时间码的段（幻觉段、纯正文段）sec=-1，若按秒数比较会全部误归左片。
    # 正确做法：找到第一个 sec >= cut 的段，以它的下标为切点（2026-10-10 自检发现）。
    cut_idx = next((i for i, s in enumerate(segs) if s.sec >= cut), None)
    if cut_idx in (None, 0):
        print(f"切点 {args.cut} 落在边界外（段范围 {segs[0].tc}–{segs[-1].tc}）", file=sys.stderr)
        return 2
    left, right = segs[:cut_idx], segs[cut_idx:]
    if not left or not right:
        print(f"切点 {args.cut} 落在边界外（段范围 {segs[0].tc}–{segs[-1].tc}）", file=sys.stderr)
        return 2

    def render(segs_, head):
        out = [head, "", "## 内容地图", "",
               "| 项 | 值 |", "|---|---|",
               f"| 来源文件 | `{path.name}` |",
               f"| 录音时段 | {segs_[0].tc} – {segs_[-1].tc} |",
               f"| 段数 | {len(segs_)} |",
               f"| 首段 | {segs_[0].text[:40]} |",
               f"| 末段 | {segs_[-1].text[:40]} |",
               f"| 拆分依据 | 切点 {args.cut}（{args.reason or '信号句'}）|", ""]
        for s in segs_:
            out.append(f"### [{s.idx:03d}] {s.tc} (S{s.spk})\n{s.text}\n")
        return "\n".join(out)

    lp = Path(args.left); rp = Path(args.right)
    lp.write_text(render(left, f"""# {lp.stem}

- 本片段共 {sec_to_tc(left[-1].sec - left[0].sec)}（{left[0].tc}–{left[-1].tc}）
- **互指**：同一次录音自 {args.cut} 起转入另一讲，已另存 `{rp.name}`
- **两侧核对**：本片末段为收束句 ✅（{left[-1].text[:30]}）"""), encoding="utf-8")
    rp.write_text(render(right, f"""# {rp.stem}

- 本片段共 {sec_to_tc(right[-1].sec - right[0].sec)}（{right[0].tc}–{right[-1].tc}）
- **互指**：本片段之前的同一次录音已另存 `{lp.name}`
- **两侧核对**：本片首段为新话题开场 ✅（{right[0].text[:30]}）"""), encoding="utf-8")
    print(f"== 跨讲切分 ==\n  左片 {len(left)} 段（{left[0].tc}–{left[-1].tc}）→ {lp.name}")
    print(f"  右片 {len(right)} 段（{right[0].tc}–{right[-1].tc}）→ {rp.name}")
    print("  → 请人工复核：左片末段应是收束句、右片首段应是新话题开场")
    return 0


# ----------------------------------------------------------------------------
# 工序 7：quality —— 质量报告
# ----------------------------------------------------------------------------

def cmd_quality(args):
    path = Path(args.file)
    text = extract(path)
    segs = parse_segments(text)
    with_tc = [s for s in segs if s.tc]
    flagged = sum(1 for s in segs if classify_segment(s.text))
    usable = len(segs) - flagged
    usable_ratio = usable / max(len(segs), 1)
    dur = total_duration([s.sec for s in with_tc]) if with_tc else 0
    readable_min = dur * usable_ratio / 60
    if usable_ratio >= 0.75:
        advice = "L2 双源（录音质量良好，可作为主要素材）"
    elif usable_ratio >= 0.35:
        advice = "L2 部分（录音可用但缺口明显，讲义需逐节标注覆盖范围）"
    else:
        advice = "L1 主导（录音仅作补充，讲义以课件为准并在开头披露）"
    rep = {
        "文件": str(path),
        "段数": len(segs),
        "带时间码": len(with_tc),
        "疑似异常段": flagged,
        "可用段": usable,
        "可用率": f"{usable_ratio * 100:.1f}%",
        "粒度": granularity_of(segs),
        "录音总时长": sec_to_tc(dur) if dur else "-",
        "可用时长约": f"{readable_min:.0f} 分钟",
        "建议层级": advice,
    }
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print(f"== 质量报告：{path.name} ==")
        for k, v in rep.items():
            if k != "文件":
                print(f"  {k}: {v}")
        print("  ⓘ 可用率由词表与形态规则估计，只能抓词汇层面问题；"
              "语义讹写（尤其英文授课课）需人工抽查一段正文后再定。")
    return 0


# ----------------------------------------------------------------------------
# 工序 8：index —— 段号索引
# ----------------------------------------------------------------------------

def cmd_index(args):
    path = Path(args.file)
    segs = [s for s in parse_segments(extract(path)) if s.tc]
    out = Path(args.out) if args.out else path.with_name(path.stem + "_index.md")
    lines = [f"# {path.stem} · 段号索引", "",
             "| 段号 | 时间码 | 说话人 | 前 30 字 |", "|---|---|---|---|"]
    for s in segs:
        lines.append(f"| {s.idx:03d} | {s.tc} | S{s.spk} | {s.text[:30].replace('|', '/')} |")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"== 段号索引：{len(segs)} 段 → {out.name} ==")
    return 0


# ----------------------------------------------------------------------------
# 工序 9：verify —— 讲义时间码对账
# ----------------------------------------------------------------------------

def cmd_verify(args):
    idx = Path(args.index).read_text(encoding="utf-8")
    tr = extract(Path(args.transcript))
    tcs = set(re.findall(r"\d{1,2}:\d{2}(?::\d{2})?", tr))
    used = re.findall(r"\d{1,2}:\d{2}(?::\d{2})?", idx)
    miss = [t for t in used if t not in tcs]
    print(f"== 时间码对账 ==")
    print(f"  讲义索引中时间码 {len(used)} 个｜转写中可查到 {len(used) - len(miss)} 个")
    if miss:
        print(f"  ⚠ 未命中 {len(miss)} 个：{miss[:10]}")
        print("     → 可能是换算口径不同（如区间起点 vs 段起点），需人工确认")
    else:
        print("  ✅ 全部可回溯到原始转写")
    return 0


# ----------------------------------------------------------------------------
# 自检
# ----------------------------------------------------------------------------

SAMPLE = """说话人200:04
就是很多时候要去这个举一反三。
说话人100:40
OK。
说话人200:42
好，我们说这个质量分成 high and low，各自的先验概率是 1/2。
上诉人 被上诉人 原告 被告 诉讼请求 本院认为 判决如下 一审 二审
说话人100:53
好，继续。
"""


def cmd_selftest(args):
    segs = parse_segments(SAMPLE)
    print(f"[1] 解析：{len(segs)} 段（期望 5）")
    assert len(segs) == 5, segs
    print(f"[2] 时间码：{[s.tc for s in segs]}（期望 00:04/00:40/00:42/00:53）")
    assert segs[0].tc == "00:04" and segs[1].sec == 40
    bad = sum(1 for s in segs if hallucination_score(s.text)[0] >= 2)
    print(f"[3] 幻觉检测：命中 {bad} 段（期望 1）")
    assert bad == 1
    n = norm_for_compare(SAMPLE)
    print(f"[4] 归一化：{len(n)} 字（去时间码与标签）")
    assert "00:04" not in n and "说话人" not in n
    print("[5] 切分：", end="")
    cut = tc_to_sec("00:42")
    cut_idx = next((i for i, s in enumerate(segs) if s.sec >= cut), None)
    left, right = segs[:cut_idx], segs[cut_idx:]
    print(f"左 {len(left)} 段 / 右 {len(right)} 段")
    assert len(left) == 2 and len(right) == 3, (len(left), len(right))
    print("\n✅ 自检全部通过")
    return 0


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

def main(argv=None):
    p = argparse.ArgumentParser(prog="transcript_kit.py",
                                description="课堂录音转写处理工具箱（十道工序）")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("probe", help="结构探明")
    s.add_argument("file"); s.add_argument("--json", action="store_true"); s.set_defaults(func=cmd_probe)

    s = sub.add_parser("extract", help="统一抽取为纯文本")
    s.add_argument("file"); s.add_argument("--out"); s.set_defaults(func=lambda a: (
        Path(a.out).write_text(extract(Path(a.file)), encoding="utf-8")
        if a.out else print(extract(Path(a.file))) or 0))

    s = sub.add_parser("detect", help="幻觉/异常段检测")
    s.add_argument("file"); s.add_argument("--json", action="store_true"); s.set_defaults(func=cmd_detect)

    s = sub.add_parser("glossary", help="术语订正")
    s.add_argument("file"); s.add_argument("--course", default="investment")
    s.add_argument("--out"); s.set_defaults(func=cmd_glossary)

    s = sub.add_parser("merge", help="粒度合并")
    s.add_argument("file"); s.add_argument("--out"); s.set_defaults(func=cmd_merge)

    s = sub.add_parser("compare", help="同课判定")
    s.add_argument("file_a"); s.add_argument("file_b"); s.set_defaults(func=cmd_compare)

    s = sub.add_parser("split", help="跨讲切分")
    s.add_argument("file"); s.add_argument("--cut", required=True)
    s.add_argument("--left", required=True); s.add_argument("--right", required=True)
    s.add_argument("--reason", default=""); s.set_defaults(func=cmd_split)

    s = sub.add_parser("quality", help="质量报告")
    s.add_argument("file"); s.add_argument("--json", action="store_true"); s.set_defaults(func=cmd_quality)

    s = sub.add_parser("index", help="段号索引")
    s.add_argument("file"); s.add_argument("--out"); s.set_defaults(func=cmd_index)

    s = sub.add_parser("verify", help="时间码对账")
    s.add_argument("index"); s.add_argument("transcript"); s.set_defaults(func=cmd_verify)

    s = sub.add_parser("selftest", help="内置自检")
    s.set_defaults(func=cmd_selftest)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
