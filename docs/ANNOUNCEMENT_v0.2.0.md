ToolGap v0.2 is out: experimental proactive KV prefetch for SGLang tool-using agents.

When reusable KV has fallen to file-backed L3, ToolGap restores it into host L2
while the tool works. The normal continuation then reuses it through SGLang's
ordinary H2D path. If KV is already GPU-resident, there is little to hide.

Our real model → document search → continuation demo observed median TTFT of
512→134ms for L3-only KV, versus128→127ms for GPU-resident KV. Tool-dispatch →
first continuation token fell1159→764ms in the L3-only condition.

Scope: one L4, Qwen2.5-1.5B,3520 reusable tokens,local file L3,three runs/condition,
controlled cache eviction,10,000 synthetic document records and potentially warm
OS page cache. No artificial tool sleep and no universal performance claim.

The repository includes the thin Python client, exact-token demo, cache-state
checks, raw trials, trace, chart and reproduction commands.
https://github.com/mks-hash/toolgap/releases/tag/v0.2.0

This is a prepared project description, not a post automatically sent anywhere.
