#!/usr/bin/env python3
"""Create a readable Markdown companion to the standalone report source."""

import re
from pathlib import Path

folder = Path(__file__).resolve().parent
source = (folder / "toolgap-report.tex").read_text()
body = source.split(r"\begin{document}", 1)[1].split(r"\end{document}", 1)[0]
references = dict(
    re.findall(r"\\bibitem\{([^}]+)\}(.*?)(?=\\bibitem|\\end\{thebibliography\})", body, re.S)
)
urls = {}
for key, text in references.items():
    match = re.search(r"\\(?:href|url)\{([^}]+)\}", text)
    urls[key] = match.group(1)


def plain(text):
    text = re.sub(r"\\nolinkurl\{([^}]+)\}", r"`\1`", text)
    text = re.sub(r"\\code\{([^}]+)\}", r"`\1`", text)
    text = re.sub(r"\\href\{([^}]+)\}\{([^}]+)\}", r"[\2](\1)", text)
    text = re.sub(r"\\url\{([^}]+)\}", r"[\1](\1)", text)
    text = re.sub(r"\\cite\{([^}]+)\}", lambda m: f"[{m[1]}]({urls[m[1]]})", text)
    text = re.sub(r"\\textbf\{([^}]+)\}", r"**\1**", text)
    text = re.sub(r"\\emph\{([^}]+)\}", r"*\1*", text)
    text = text.replace(r"\repo", "[github.com/mks-hash/toolgap](https://github.com/mks-hash/toolgap)")
    for old, new in [(r"\%", "%"), (r"\_", "_"), (r"\#", "#"), (r"\,", " "), ("~", " "), ("---", "—"), ("--", "–")]:
        text = text.replace(old, new)
    text = text.replace("``", "“").replace("''", "”")
    text = re.sub(r"\\(?:small|footnotesize|bfseries)\b", "", text)
    return text.strip()


def table(match):
    text = match[0]
    text = text[text.index(r"\toprule") + len(r"\toprule"):]
    text = re.sub(r"\\(?:toprule|midrule|bottomrule)", "", text)
    text = re.sub(r"\\end\{(?:tabular|tabularx)\}", "", text)
    rows = [row.strip() for row in re.split(r"\\\\", text) if row.strip()]
    rows = [[plain(cell.strip()) for cell in row.split("&")] for row in rows]
    lines = ["| " + " | ".join(row) + " |" for row in rows]
    lines.insert(1, "| " + " | ".join("---" for _ in rows[0]) + " |")
    return "\n\n" + "\n".join(lines) + "\n\n"


body = re.sub(r"\\thispagestyle\{[^}]+\}\s*\\begin\{center\}.*?\\end\{center\}", "", body, count=1, flags=re.S)
blocks = []


def code(match):
    blocks.append("```bash\n" + match[1].strip() + "\n```")
    return f"CODEBLOCK{len(blocks)-1}PLACEHOLDER"


body = re.sub(r"\\begin\{lstlisting\}(.*?)\\end\{lstlisting\}", code, body, flags=re.S)
figures = [
    "\n```mermaid\nflowchart LR\n  Signal[Exact-prefix control] --> Read[Existing L3 query/read]\n  Read --> L2[Terminal ACK and resident host L2]\n  Tool[Real tool work] --> Request[Ordinary continuation]\n  Request --> Inference[Prefix match, normal H2D, generation]\n  L2 --> Inference\n```\n",
    "\n![Recorded synthetic-gap benchmark](../../results/ttft.png)\n",
    "\n![All recorded real-tool TTFT observations](../../results/tool-loop/ttft.png)\n",
]
index = 0


def figure(match):
    global index
    result = figures[index]
    index += 1
    if result.lstrip().startswith("```"):
        blocks.append(result.strip())
        return f"CODEBLOCK{len(blocks)-1}PLACEHOLDER"
    return result


body = re.sub(r"\\begin\{tikzpicture\}.*?\\end\{tikzpicture\}", figure, body, flags=re.S)
body = re.sub(r"\\begin\{tabularx?\}.*?\\end\{tabularx?\}", table, body, flags=re.S)
body = re.sub(r"\\begin\{thebibliography\}.*?\\end\{thebibliography\}", "", body, flags=re.S)
body = re.sub(r"\\section\{([^}]+)\}", r"\n## \1\n", body)
body = re.sub(r"\\subsection\{([^}]+)\}", r"\n### \1\n", body)
body = body.replace(r"\begin{abstract}", "## Abstract\n").replace(r"\end{abstract}", "")
body = re.sub(r"\\(?:begin|end)\{center\}", "", body)
body = re.sub(r"\\vspace\{[^}]+\}", "", body).replace(r"\pagemark", "")
body = plain(body)
# Presentation-only braces surrounding the figure/table captions.
body = re.sub(r"\{\s*(\*\*(?:Figure|Table).*?)\}\s*(?=\n)", r"\1", body, flags=re.S)
body = body.replace("**Figure 2.** Synthetic-gap medians. Equal x-spacing denotes conditions, not a linear time axis. The repository retains all individual observations.", "**Figure 2.** Recorded synthetic-gap chart. The standalone LaTeX source plots the same five condition medians with explicitly categorical spacing; the repository retains all individual observations.")
body = re.sub(r"\n{3,}", "\n\n", body)
body = re.sub(r"(?<!\n)\n(#{2,3} )", r"\n\n\1", body)
for i, block in enumerate(blocks):
    body = body.replace(f"CODEBLOCK{i}PLACEHOLDER", block)
header = "# ToolGap: Hiding KV-Cache Restore Latency During LLM Agent Tool Execution\n\n**Maxim Yakimov** · October 4, 2026 · Technical report, revision 2\n\nReadable companion to `toolgap-report.tex`. The author-exported eight-page Overleaf PDF was visually reviewed; the current source also compiled successfully in the built-in editor on October 4, 2026. Verification provenance is recorded in `pdf-validation.json`. This copy uses the repository's existing recorded charts.\n\n"
bibliography = "\n\n## References\n\n" + "\n\n".join(f"- **{key}:** {plain(text)}" for key, text in references.items()) + "\n"
(folder / "technical-report.md").write_text(header + body + bibliography)
print("Readable report written; prose and references derived from LaTeX source.")
