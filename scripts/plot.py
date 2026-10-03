#!/usr/bin/env python3
"""Plot recorded observations, not inferred significance intervals."""
import json, statistics
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
root=Path(__file__).resolve().parents[1]
rows=json.loads((root/"results/raw/trials.json").read_text())
gaps=[0,100,500,1000,3000]
fig,ax=plt.subplots(figsize=(9,4.8),layout="constrained")
for mode,color,label,offset in [("A","#64748b","A · recompute",-.12),("B","#d97706","B · request-time restore",0),("C","#0284c7","C · proactive restore",.12)]:
    medians=[]
    for i,gap in enumerate(gaps):
        values=[r["ttft_ms"] for r in rows if r["mode"]==mode and r["gap_ms"]==gap]
        medians.append(statistics.median(values))
        ax.scatter([i+offset]*len(values),values,color=color,alpha=.4,s=20)
    ax.plot(range(5),medians,color=color,label=label,marker="o",linewidth=2)
ax.set_xticks(range(5),[str(x) for x in gaps]);ax.set_xlabel("Tool gap (ms)");ax.set_ylabel("Continuation TTFT (ms)")
ax.set_title("ToolGap · medians and all three observations per condition")
ax.set_ylim(bottom=0);ax.grid(axis="y",alpha=.2);ax.legend(frameon=False)
fig.text(.5,-.04,"Single L4 · Qwen2.5-1.5B · 4096 input / 4080 restored tokens · file L3 · n=3",ha="center",fontsize=9)
for ext in ["png","svg"]:fig.savefig(root/f"results/ttft.{ext}",dpi=180,bbox_inches="tight")

svg = root / "results/ttft.svg"
svg.write_text("\n".join(line.rstrip() for line in svg.read_text().splitlines()) + "\n")
