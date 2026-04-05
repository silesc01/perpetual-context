"""
Claude Code hook entry points for the Perpetual Context Cartographer.

Three hooks:
  - session-start: inject filtered .ctx into session context
  - post-tool-use: extract observations silently (async)
  - session-end: log session summary

Called via ~/.claude/settings.json hooks configuration.
"""

import json
import sys
from pathlib import Path

from cartographer import (
    CTX_DIR,
    CtxFile,
    append_pending,
    extract_observations,
)

# Project directory -> context group mapping.
# Customize this to match your project structure.
# Keys are substrings matched against the working directory path.
# Values are lists of node IDs whose edges should be injected.
PROJECT_MAP = {
    # Example:
    # "my-project": ["my-project", "my-org"],
    # "backend": ["api", "database"],
}


def _detect_project(cwd):
    """Detect which context groups are relevant from the working directory."""
    cwd_lower = cwd.lower().replace("\\", "/")
    for key, groups in PROJECT_MAP.items():
        if key in cwd_lower:
            return groups
    return []


def inject_context(project_dir, ctx_path=None):
    """Read context.ctx and return relevant context string for session injection."""
    ctx_path = ctx_path or (CTX_DIR / "context.ctx")
    if not ctx_path.exists():
        return ""

    ctx = CtxFile(ctx_path)
    owner = ctx.meta.get("owner", "")
    relevant_groups = _detect_project(project_dir)

    lines = []
    lines.append("## Perpetual Context")
    lines.append("")

    # Owner's edges — filtered to relevant groups if detected
    owner_edges = [e for e in ctx.edges if e["source"] == owner]
    if relevant_groups:
        project_edges = [e for e in owner_edges if e["target"] in relevant_groups]
        other_edges = [e for e in owner_edges if e["target"] not in relevant_groups
                       and float(e.get("confidence", 0)) >= 0.8]
        show_edges = project_edges + other_edges
    else:
        show_edges = [e for e in owner_edges if float(e.get("confidence", 0)) >= 0.7]

    if show_edges:
        lines.append("### Relationships")
        for e in sorted(show_edges, key=lambda x: float(x.get("confidence", 0)), reverse=True):
            target_id = e["target"]
            target_desc = ctx.nodes.get(target_id, {}).get("description", target_id)
            lines.append(f"- {e['rel']}: {target_id} ({target_desc}) (conf={e.get('confidence', '?')})")

    # Preferences — always inject
    if ctx.preferences:
        lines.append("")
        lines.append("### Preferences")
        for p in ctx.preferences:
            parts = [f"{k}={v}" for k, v in p.items() if k != "id"]
            lines.append(f"- {p['id']}: {', '.join(parts)}")

    # Constraints — always inject
    if ctx.constraints:
        lines.append("")
        lines.append("### Constraints (never violate)")
        for c in ctx.constraints:
            parts = [f"{k}={v}" for k, v in c.items() if k != "id"]
            lines.append(f"- {c['id']}: {', '.join(parts)}")

    result = "\n".join(lines)

    # Enforce token cap (rough: 4 chars per token)
    max_chars = 1500 * 4
    if len(result) > max_chars:
        result = result[:max_chars] + "\n[truncated]"

    return result


def hook_session_start():
    """SessionStart hook: inject perpetual context into session."""
    try:
        input_data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        input_data = {}

    cwd = input_data.get("cwd", "")
    context = inject_context(cwd)

    if context:
        output = {
            "hookSpecificOutput": {
                "additionalContext": context,
            },
            "suppressOutput": True,
        }
        print(json.dumps(output))

    sys.exit(0)


def hook_post_tool_use():
    """PostToolUse hook: extract observations from tool calls (async, silent)."""
    try:
        input_data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    tool_output = input_data.get("tool_result", "")

    observations = extract_observations(tool_name, tool_input, tool_output)

    if observations:
        append_pending(observations)

    sys.exit(0)


def hook_session_end():
    """Stop hook: log session completion."""
    try:
        input_data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        input_data = {}

    cwd = input_data.get("cwd", "")
    groups = _detect_project(cwd)
    if groups:
        append_pending([{
            "type": "edge",
            "source": "owner",
            "rel": "completed_session",
            "target": groups[0],
            "source_type": "behavior",
        }])

    sys.exit(0)


# CLI entry point
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python hooks.py <session-start|post-tool-use|session-end>")
        sys.exit(1)

    hook = sys.argv[1]
    if hook == "session-start":
        hook_session_start()
    elif hook == "post-tool-use":
        hook_post_tool_use()
    elif hook == "session-end":
        hook_session_end()
    else:
        print(f"Unknown hook: {hook}")
        sys.exit(1)
