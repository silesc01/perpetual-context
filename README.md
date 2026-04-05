# Perpetual Context Cartographer

A background observation system that maintains a structured entity-relationship graph across Claude Code sessions. It watches tool calls, file operations, and conversation patterns to build a persistent model of who you are, what you work on, and how you prefer to work — then injects relevant context into every new session automatically.

It never interrupts. It never contributes to the conversation. It just watches and writes.

## Why This Exists

LLM sessions are stateless. Every new conversation starts from zero. Project instructions (CLAUDE.md) help, but they're manually maintained and don't capture behavioral patterns, evolving relationships, or soft preferences that emerge over dozens of sessions.

The Cartographer solves this by passively observing every session and building a structured graph that grows over time. When a new session starts, it injects the relevant slice of that graph — so the AI knows your preferences, your business context, and your constraints without you having to repeat them.

## How It Works

### Two Phases

**Daytime — silent hooks across all Claude Code sessions:**

```
SessionStart (sync)   → inject filtered context from .ctx graph
PostToolUse (async)    → extract observations → append to pending.ctx
SessionEnd (async)     → log session summary
```

Hooks are global (`~/.claude/settings.json`). They fire in every session regardless of project — Higgins, Nexus, Subarb, PRDM, Dossier, whatever you're working on.

**Nightly — scheduled merge (11:45 PM):**

```
1. Read pending.ctx (day's observations)
2. Merge into context.ctx (add nodes, update edges, increment counters)
3. Run confidence decay on unobserved edges (-0.02/week)
4. Prune stale low-confidence edges → archive.ctx
5. Flag contradictions → contradictions.log
6. Write summary for morning briefing
7. Clear pending.ctx
```

### The .ctx Format

Plain text, pipe-delimited. No database, no binary format, no dependencies. Human-readable, git-diffable.

```
#meta
version | 0.1.0
created | 2026-03-29
owner | scott

#nodes
scott | person | founder of exergy holding, teaches political risk at GWU
prdm | brand | political risk demystified — community, courses, book, coaching
nexus | tool | OSINT intelligence engine — events, CRM, briefing builder

#edges
scott > founded > exergy-holding | confidence=1.0 | seen=50 | last=2026-03-29 | source_type=manual
scott > uses > claude-code | confidence=0.95 | seen=30 | last=2026-04-03 | source_type=behavior

#preferences
prefers_terse_responses | confidence=0.95 | seen=20 | context=communication
prefers_automation_over_manual | confidence=0.9 | seen=30 | context=workflow

#constraints
never_publish_without_approval | type=execution_rule | override=false
vault_is_source_of_truth | type=data_rule | override=false

#aliases
subarb | llm-manager | llm manager
```

### Context Injection

At session start, the Cartographer reads the working directory to determine which business line you're in, then injects only the relevant slice of the graph:

| Working Directory | What Gets Injected |
|---|---|
| `*/higgins/*` | Higgins edges, automation preferences |
| `*/nexus/*` | Nexus edges, Exergy/client relationships |
| `*/PRDM/*` | PRDM edges, community/course relationships |
| `*/Dossier/*` | Dossier edges, content pipeline |

Preferences and constraints always inject regardless of project. Hard cap: 1500 tokens.

### Confidence and Decay

Every edge has a confidence score (0.0–1.0) that reflects how certain the system is about the relationship.

**Initial confidence by source:**

| Source | Confidence |
|---|---|
| Manual (seed data) | 1.0 |
| Transaction (purchase, sale) | 0.9 |
| Email | 0.7 |
| Conversation | 0.6 |
| Behavior (observed pattern) | 0.5 |
| Inferred | 0.4 |

**How confidence changes:**
- Each re-observation: +0.05 (max 1.0)
- Decay: -0.02 per week if not re-observed
- Inferred edges decay at 2x rate unless confirmed
- Manual entries never decay

**Pruning (nightly):**
- Archive when: `seen=1` AND `confidence < 0.3` AND older than 30 days
- Never prune: constraints, manual edges, edges above 0.8 confidence

### Contradiction Handling

When a new observation conflicts with an existing high-confidence edge:
1. Don't overwrite — log to `contradictions.log`
2. If the new observation reaches `seen=3` and `confidence > 0.7`, flag in morning briefing
3. Human reviews and confirms, dismisses, or ignores (decay handles it)

## File Structure

```
perpetual_context/
├── __init__.py
├── cartographer.py        # Core: .ctx parser, merger, extraction, decay, pruning
├── hooks.py               # Claude Code hook entry points
├── config.json            # Tuning parameters (decay rate, thresholds, etc.)
├── README.md              # This file
└── data/
    ├── context.ctx        # The live graph
    ├── pending.ctx        # Unprocessed observations queue
    ├── archive.ctx        # Pruned edges (kept for history)
    ├── changelog.ctx      # All modifications logged
    ├── contradictions.log # Flagged conflicts for review
    └── nightly_summary.json # Latest merge stats
```

## What It Extracts

### Entity Relationships
- Slack channel names in tool calls → business line context
- Vault file paths in Read/Write/Edit → which business is being worked on
- Email addresses in script output → contact entities
- URLs (Beehiiv, Gumroad, Teachable) → service relationships
- Nexus API calls → client and prospect entities

### Behavioral Patterns
- Session working directory → which projects get time
- Tool call frequency → tool preferences
- Session timestamps → time-of-day work patterns
- Script names in Bash calls → manual vs automated workflow preferences

### Preferences and Constraints
- Corrections ("don't do X") → constraints with rising confidence
- Rejected suggestions → negative preference signals
- Repeated patterns across sessions → soft preferences

### What It Does NOT Extract
- Individual file reads/writes (noise)
- Code content or framework imports (not relevant to the person graph)
- Git operations (tracked by git itself)
- Anything already captured by other memory systems

## Configuration

`config.json`:

```json
{
  "decay_rate": 0.02,
  "decay_interval_days": 7,
  "prune_min_confidence": 0.3,
  "prune_min_age_days": 30,
  "inference_enabled": false,
  "confidence_increment": 0.05,
  "max_confidence": 1.0,
  "context_injection_max_tokens": 1500
}
```

`inference_enabled` is off by default. When enabled, the system infers relationships it hasn't directly observed (e.g., if Scott uses Nexus and Nexus connects to Exergy International, infer Scott works with Exergy International). Inferred edges start at 0.4 confidence and decay at 2x rate.

## Hook Configuration

Add to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "type": "command",
        "command": "python perpetual_context/hooks.py session-start",
        "timeout": 5000
      }
    ],
    "PostToolUse": [
      {
        "type": "command",
        "command": "python perpetual_context/hooks.py post-tool-use",
        "timeout": 3000
      }
    ],
    "Stop": [
      {
        "type": "command",
        "command": "python perpetual_context/hooks.py session-end",
        "timeout": 3000
      }
    ]
  }
}
```

## Nightly Merge

Schedule `scripts/cartographer_merge.py` to run daily (e.g., 11:45 PM). It:
1. Merges pending observations into the main graph
2. Runs confidence decay
3. Prunes stale edges
4. Writes a summary for the morning briefing

## How It's Been Used

The Cartographer was built for [Higgins](https://github.com/), a voice AI majordomo that manages five business lines under Exergy Holding LLC. Here's how it operates in production:

### Current Graph (as of April 2026)
- **19 nodes** — the owner, 5 business brands, 6 tools/services, and key platforms
- **32 edges** — ownership, creation, usage, and dependency relationships
- **8 preferences** — communication style (terse, no emoji, no trailing summaries), workflow patterns (automation over manual, batch over single, scripts for data movement, AI for judgment only)
- **6 constraints** — execution rules that never get violated (never publish without approval, never send email without approval, vault is source of truth, drafts and flags only)
- **1,912 changelog entries** — every observation and merge logged

### What It Does in Practice

**Session continuity:** When a new Claude Code session opens in the PRDM project directory, the Cartographer injects PRDM-specific context — that PRDM is a community with courses on Teachable, a newsletter on Beehiiv, a job board, and a talent directory. The session knows this without reading CLAUDE.md.

**Preference enforcement:** After observing across 20+ sessions that the user prefers terse responses with no emoji and no trailing summaries, the Cartographer injects these as preferences with 0.9+ confidence. New sessions respect these without being told.

**Constraint safety:** Constraints like "never publish without approval" and "never send email without approval" are injected into every session with `override=false`. These can't be decayed away — they persist permanently.

**Cross-project awareness:** Working on the Higgins project but referencing PRDM? The Cartographer includes high-confidence edges from other business lines (above 0.8) even when they're not the primary project, so the session has peripheral awareness.

### The Subconscious Pipeline

The Cartographer runs alongside an existing "subconscious" pipeline that processes Claude Code transcripts overnight:

```
11:00 PM — process_transcripts.py (extract freeform observations from session logs)
11:30 PM — update_memory_blocks.py (deduplicate, age out, enforce limits)
11:45 PM — cartographer_merge.py (merge structured observations, decay, prune)
12:00 AM — git_backup.py (commit everything)
 2:00 AM — compile_context.py (recompile context.md for next day's sessions)
```

The subconscious provides freeform observations ("Scott spent 3 hours on PRDM job board today"). The Cartographer provides structured relationships ("Scott > uses > job-board | confidence=0.9"). They complement each other.

### Morning Briefing Integration

The nightly merge summary is included in the 6 AM morning briefing:

```
## Cartographer
- Graph: 19 nodes, 32 edges
- Overnight: 82 changes merged, 0 decayed, 0 pruned
- Contradictions: 0
```

If contradictions are flagged, they appear in the morning triage for human review.

## Design Principles

1. **Never interrupt** — The Cartographer is invisible during sessions. It hooks silently, extracts asynchronously, and injects only at session start.

2. **Plain text over databases** — The `.ctx` format is a flat text file. It can be read with `cat`, diffed with `git diff`, edited with any text editor, and backed up with `git push`.

3. **Decay over deletion** — Nothing is deleted outright. Edges lose confidence over time if not re-observed. Low-confidence edges get archived, not destroyed. Manual entries never decay.

4. **Human resolves conflicts** — The system flags contradictions but never overwrites high-confidence data. Ambiguity is surfaced, not resolved autonomously.

5. **Relevance filtering** — Not everything gets injected into every session. The working directory determines which slice of the graph is relevant. A Dossier session doesn't need Nexus CRM relationships.

6. **Token budget** — Context injection is hard-capped at 1500 tokens. The most relevant, highest-confidence edges are prioritized. Preferences and constraints always fit within the budget.

## Limitations

- **No inference engine yet** — `inference_enabled` is off. The system only tracks what it directly observes. Planned for activation after the graph stabilizes (~4 weeks of data).
- **Extraction is pattern-based** — It matches Slack channel names, vault paths, and URLs. It doesn't understand natural language in conversations (that's what the subconscious pipeline does).
- **Single-owner model** — The graph has one owner node. Multi-user support would require per-user graphs and access controls.
- **No UI** — Graph inspection is via the `.ctx` file or Python API. A visualization tool would help but isn't built yet.

## License

MIT
