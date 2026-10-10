# 讲义 Skill 包（Lecture Notes Skill Kit）

把一份课件（PPT/PDF）+ 课堂录音，整理成**忠实、可编译、可直接复习的中文 LaTeX 讲义**。
本包是中山大学岭南学院《投资学》《国际贸易》《平台经济学》《世界发展》《经济学研究方法》
五门课讲义工程的沉淀产物——**11 份讲义、332 个课堂实录框、404 页课件**的实战检验。

## 包含什么

| 类别 | 内容 | 作用 |
|---|---|---|
| **总编排** | `business-lecture-orchestrator` | 薄编排层：判定层级、规定调用顺序、裁决冲突、把关交付 |
| **内容 skill** | `courseware-notes`（读课件/套模板/编译）、`lecture-notes-zh`（教学结构）、`rigorous-derivation`（逐步推导）、`exam-problems`（例题精解） | 真正干活 |
| **语境包** | `investment-lecture-orchestrator`（投资学）、`platform-economy-orchestrator`（平台经济） | 领域术语与易错点 |
| **录音工具箱** | `_tools/transcript_kit.py` | 十道工序：结构探明／幻觉检测／术语订正／粒度合并／同课判定／跨讲切分／质量报告／索引／对账 |
| **资料资产** | `assets/glossary/*.md`、`assets/hallucination_blacklist.txt`、`assets/samples/` | 课程术语表、幻觉词黑名单、黄金样例 |
| **环境工具** | `_shared/doctor.py`、`_shared/config.json`、`_shared/install.*`、`_shared/verify_golden.py` | 自检／配置／安装／跨机一致性验证 |

## 快速开始（三步）

```bash
# 1) 克隆到 skills 目录（WorkBuddy 或 Claude Code）
git clone https://github.com/chenmc7/skill-store.git ~/.workbuddy/skills/skill-store

# 2) 安装（建立链接 + 自动自检）
bash ~/.workbuddy/skills/skill-store/_shared/install.sh          # macOS / Linux
# powershell -ExecutionPolicy Bypass -File _shared\install.ps1   # Windows

# 3) 验证环境与工具链
python _shared/verify_golden.py     # 期望 12/12 全绿
```

安装完成后，直接对 AI 说：**「把这份课件做成讲义」**（把课件 PDF 一并给它）。

## 目录结构

```
skill-store/
├── business-lecture-orchestrator/SKILL.md      ← 总编排（先看它）
├── courseware-notes/  SKILL.md + assets/notes-template.tex
├── lecture-notes-zh/  SKILL.md + lecture-outline.md
├── rigorous-derivation/  exam-problems/
├── investment-lecture-orchestrator/  platform-economy-orchestrator/
├── _tools/transcript_kit.py                    ← 录音处理十道工序
├── _shared/  config.json · doctor.py · install.sh · install.ps1 · verify_golden.py
└── assets/  glossary/ · hallucination_blacklist.txt · samples/
```

## 录音处理（本包的重点）

十道工序，各自对应一条实战教训：

```bash
python _tools/transcript_kit.py probe    <文件>    # 结构探明：三种排布 + 说话人时间码拆解 + 单调性验伪
python _tools/transcript_kit.py detect   <文件>    # 幻觉/异常段（司法语汇黑名单 + 中英混排）
python _tools/transcript_kit.py glossary <文件> --course investment   # 术语订正（讹写→正确）
python _tools/transcript_kit.py merge    <文件>    # 粒度合并（≤8 秒且 <300 字）
python _tools/transcript_kit.py compare  <A> <B>   # 同课判定（相似度 ≥0.80 同课）
python _tools/transcript_kit.py split    <文件> --cut HH:MM:SS --left a.md --right b.md
python _tools/transcript_kit.py quality  <文件>    # 质量报告（可用率 / 建议层级）
python _tools/transcript_kit.py index    <文件>    # 段号索引
python _tools/transcript_kit.py verify   <讲义索引> <转写>            # 时间码对账
python _tools/transcript_kit.py selftest           # 内置自检
```

**能力边界（请先读）**：检测基于**词表与形态规则**，只能抓**词汇层面**的幻觉；
**语义层面的讹写**（如英文句子被听错成另一个句子）抓不到，必须人工抽查一段正文。

## 跨机一致性：能保证什么 / 不能保证什么

**能保证（工程手段）**
- 依赖与环境：`doctor.py` 自检 Python / XeLaTeX / ctex / 中文字体 / poppler，缺失会给安装指引；字体按平台自动选（Windows→Microsoft YaHei，macOS→PingFang SC，Linux→Noto Sans CJK）
- 配置可移植：路径与参数集中在 `_shared/config.json`，`--autodetect` 自动探测
- 工具行为确定：`verify_golden.py` 用黄金样例校验 12 项，工具层跨机结果相同
- 下限硬指标：讲义侧靠「四查 + 双向覆盖核对」保证 **0 实录框、0 时间码、0 转述口吻、知识点不丢、能编译**

**不能保证（诚实声明）**
- **文风与凝练质量取决于底层大模型**——不同模型写出的讲义风格会不同。本包只能把"下限"焊死，
  不允许把"文风一致"写进承诺。
- 转录工具本身（讯飞/Whisper/不同版本）的词错率与粒度差异，会影响上限；`quality` 会量化披露。

## 已知限制

- 工具箱的 PDF 抽取依赖 `pypdfium2` 或 poppler，二者皆缺时只能处理 docx/txt/md；
- 图片型课件（无文字层）无法用文本匹配核对，改用「页级脉络表 + `【承上｜课件 pXX】` 页码标记」两条链覆盖；
- 讲义 PDF 需中文字体，Windows/macOS/Linux 的字体名不同（由 `config.json` 的 `fonts.main` 控制）。

## 许可

MIT（见 `LICENSE`）。课件与录音原文不在本仓库内——它们属于课程与授课教师，请勿随包分发。
