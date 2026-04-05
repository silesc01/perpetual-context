"""Perpetual Context Cartographer — CtxFile parser and writer."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CTX_DIR = Path(__file__).resolve().parent / "data"

DEFAULT_CONFIG: dict[str, Any] = {
    "confidence_increment": 0.05,
    "max_confidence": 1.0,
    "initial_confidence": {
        "manual": 1.0,
        "transaction": 0.9,
        "email": 0.7,
        "conversation": 0.6,
        "behavior": 0.5,
        "inferred": 0.4,
    },
}

# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def normalize_id(text: str) -> str:
    """Lowercase, strip, replace spaces with hyphens, remove non-alphanumeric (except hyphens/underscores), max 64 chars."""
    text = text.strip().lower()
    text = text.replace(" ", "-")
    text = re.sub(r"[^a-z0-9\-_]", "", text)
    return text[:64]


def load_config() -> dict[str, Any]:
    """Read config.json from CTX_DIR if it exists, merge with defaults."""
    config_path = Path(__file__).resolve().parent / "config.json"
    config = dict(DEFAULT_CONFIG)
    config["initial_confidence"] = dict(DEFAULT_CONFIG["initial_confidence"])
    if config_path.exists():
        try:
            with config_path.open("r", encoding="utf-8") as fh:
                user_config = json.load(fh)
            config.update(user_config)
        except (json.JSONDecodeError, OSError):
            pass
    return config


def _now_iso() -> str:
    """Return current UTC datetime as ISO 8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today_iso() -> str:
    """Return current UTC date as ISO 8601 date string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# CtxFile
# ---------------------------------------------------------------------------


class CtxFile:
    """Parse, query, and write .ctx pipe-delimited context files.

    .ctx sections: #meta, #nodes, #edges, #preferences, #constraints, #aliases

    Meta:        key | value
    Nodes:       id | type | description
    Edges:       source > rel > target | key=value ...
    Preferences: pref_id | key=value ...
    Constraints: constraint_id | key=value ...
    Aliases:     alias = canonical
    Comments:    lines starting with //
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path: Path | None = path
        self.meta: dict[str, str] = {}
        self.nodes: dict[str, dict[str, str]] = {}
        self.edges: list[dict[str, str]] = []
        self.preferences: list[dict[str, str]] = []
        self.constraints: list[dict[str, str]] = []
        self.aliases: dict[str, str] = {}
        self._config = load_config()

        if path is not None and path.exists():
            self._parse()

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def _parse(self) -> None:
        """Read the .ctx file and populate all section data."""
        assert self.path is not None
        with self.path.open("r", encoding="utf-8") as fh:
            lines = fh.readlines()

        section: str | None = None
        for raw in lines:
            line = raw.rstrip("\n").rstrip()
            # Skip blanks and comments
            if not line or line.startswith("//"):
                continue
            # Section header
            if line.startswith("#"):
                section = line.lstrip("#").strip().lower()
                continue
            # Dispatch to section parser
            if section == "meta":
                self._parse_meta(line)
            elif section == "nodes":
                self._parse_node(line)
            elif section == "edges":
                self._parse_edge(line)
            elif section == "preferences":
                self._parse_preference(line)
            elif section == "constraints":
                self._parse_constraint(line)
            elif section == "aliases":
                self._parse_alias(line)

    def _parse_meta(self, line: str) -> None:
        parts = [p.strip() for p in line.split("|", 1)]
        if len(parts) == 2:
            self.meta[parts[0]] = parts[1]

    def _parse_node(self, line: str) -> None:
        parts = [p.strip() for p in line.split("|", 2)]
        if len(parts) >= 2:
            node_id = parts[0]
            node_type = parts[1]
            description = parts[2] if len(parts) == 3 else ""
            self.nodes[node_id] = {"type": node_type, "description": description}

    def _parse_edge(self, line: str) -> None:
        # Format: source > rel > target | key=value | key=value ...
        pipe_parts = [p.strip() for p in line.split("|")]
        if not pipe_parts:
            return
        # First segment contains "source > rel > target"
        triple = [t.strip() for t in pipe_parts[0].split(">")]
        if len(triple) != 3:
            return
        edge: dict[str, str] = {
            "source": triple[0],
            "rel": triple[1],
            "target": triple[2],
        }
        # Remaining pipe segments are key=value pairs
        for kv_segment in pipe_parts[1:]:
            edge.update(self._parse_kv_segment(kv_segment))
        self.edges.append(edge)

    def _parse_preference(self, line: str) -> None:
        pipe_parts = [p.strip() for p in line.split("|")]
        if not pipe_parts:
            return
        pref: dict[str, str] = {"id": pipe_parts[0]}
        for kv_segment in pipe_parts[1:]:
            pref.update(self._parse_kv_segment(kv_segment))
        self.preferences.append(pref)

    def _parse_constraint(self, line: str) -> None:
        pipe_parts = [p.strip() for p in line.split("|")]
        if not pipe_parts:
            return
        constraint: dict[str, str] = {"id": pipe_parts[0]}
        for kv_segment in pipe_parts[1:]:
            constraint.update(self._parse_kv_segment(kv_segment))
        self.constraints.append(constraint)

    def _parse_alias(self, line: str) -> None:
        # Format: alias = canonical
        if "=" in line:
            alias, _, canonical = line.partition("=")
            self.aliases[alias.strip()] = canonical.strip()

    @staticmethod
    def _parse_kv_segment(segment: str) -> dict[str, str]:
        """Parse a single 'key=value' segment into a dict."""
        result: dict[str, str] = {}
        if "=" in segment:
            key, _, value = segment.partition("=")
            result[key.strip()] = value.strip()
        return result

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def resolve_alias(self, name: str) -> str:
        """Return the canonical id for an alias, or the name unchanged."""
        return self.aliases.get(name, name)

    def has_node(self, node_id: str) -> bool:
        """Return True if the node exists."""
        return node_id in self.nodes

    def has_edge(self, source: str, rel: str, target: str) -> dict[str, str] | None:
        """Return the edge dict if found, else None."""
        for edge in self.edges:
            if edge["source"] == source and edge["rel"] == rel and edge["target"] == target:
                return edge
        return None

    # ------------------------------------------------------------------
    # Mutation helpers
    # ------------------------------------------------------------------

    def add_node(self, node_id: str, node_type: str, description: str) -> bool:
        """Add a node. Return True if new, False if already exists."""
        if node_id in self.nodes:
            return False
        self.nodes[node_id] = {"type": node_type, "description": description}
        return True

    def add_edge(
        self,
        source: str,
        rel: str,
        target: str,
        source_type: str = "inferred",
        **metadata: str,
    ) -> str:
        """Add or update an edge.

        Returns "added" if new, "updated" if the edge already existed.
        Confidence is set from initial_confidence[source_type] on add.
        On update, confidence increments by confidence_increment (capped at max_confidence)
        and seen is incremented.
        """
        existing = self.has_edge(source, rel, target)
        if existing is None:
            initial = self._config["initial_confidence"].get(source_type, 0.4)
            edge: dict[str, str] = {
                "source": source,
                "rel": rel,
                "target": target,
                "confidence": str(initial),
                "seen": "1",
                "last": _today_iso(),
                "source_type": source_type,
            }
            edge.update({k: str(v) for k, v in metadata.items()})
            self.edges.append(edge)
            return "added"
        else:
            # Increment seen
            seen = int(existing.get("seen", "1")) + 1
            existing["seen"] = str(seen)
            # Increment confidence
            current_conf = float(existing.get("confidence", "0.4"))
            increment = self._config["confidence_increment"]
            max_conf = self._config["max_confidence"]
            new_conf = min(round(current_conf + increment, 10), max_conf)
            existing["confidence"] = str(new_conf)
            existing["last"] = _today_iso()
            existing.update({k: str(v) for k, v in metadata.items()})
            return "updated"

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def write(self, path: Path) -> None:
        """Serialize all sections to .ctx format and write to path."""
        lines: list[str] = []

        # Meta
        if self.meta:
            lines.append("#meta")
            for key, value in self.meta.items():
                lines.append(f"{key} | {value}")
            lines.append("")

        # Nodes
        if self.nodes:
            lines.append("#nodes")
            for node_id, data in self.nodes.items():
                node_type = data.get("type", "")
                description = data.get("description", "")
                lines.append(f"{node_id} | {node_type} | {description}")
            lines.append("")

        # Edges
        if self.edges:
            lines.append("#edges")
            for edge in self.edges:
                source = edge["source"]
                rel = edge["rel"]
                target = edge["target"]
                # Collect extra key=value pairs (everything except source/rel/target)
                extras = {k: v for k, v in edge.items() if k not in ("source", "rel", "target")}
                kv_str = " | ".join(f"{k}={v}" for k, v in extras.items())
                if kv_str:
                    lines.append(f"{source} > {rel} > {target} | {kv_str}")
                else:
                    lines.append(f"{source} > {rel} > {target}")
            lines.append("")

        # Preferences
        if self.preferences:
            lines.append("#preferences")
            for pref in self.preferences:
                pref_id = pref["id"]
                extras = {k: v for k, v in pref.items() if k != "id"}
                kv_str = " | ".join(f"{k}={v}" for k, v in extras.items())
                if kv_str:
                    lines.append(f"{pref_id} | {kv_str}")
                else:
                    lines.append(pref_id)
            lines.append("")

        # Constraints
        if self.constraints:
            lines.append("#constraints")
            for constraint in self.constraints:
                c_id = constraint["id"]
                extras = {k: v for k, v in constraint.items() if k != "id"}
                kv_str = " | ".join(f"{k}={v}" for k, v in extras.items())
                if kv_str:
                    lines.append(f"{c_id} | {kv_str}")
                else:
                    lines.append(c_id)
            lines.append("")

        # Aliases
        if self.aliases:
            lines.append("#aliases")
            for alias, canonical in self.aliases.items():
                lines.append(f"{alias} = {canonical}")
            lines.append("")

        path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Decay and Pruning
# ---------------------------------------------------------------------------


def _parse_date(date_str: str) -> datetime:
    """Parse an ISO date string (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ) into a timezone-naive UTC datetime."""
    date_str = date_str.strip()
    if "T" in date_str:
        # Full ISO datetime
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.replace(tzinfo=None)
    else:
        return datetime.strptime(date_str, "%Y-%m-%d")


def run_decay(ctx: CtxFile, reference_date: str | None = None) -> int:
    """Apply time-based confidence decay to non-manual edges.

    For each edge that is not source_type=manual:
    - Calculates age in days from edge["last"] to reference_date (or now).
    - decay_cycles = age_days // decay_interval_days
    - total_decay = decay_rate * decay_cycles * multiplier
      where multiplier is 2.0 if inferred=true, 1.0 otherwise.
    - Reduces confidence: max(0.0, confidence - total_decay)

    Returns the count of edges that were actually decayed (confidence changed).
    """
    config = load_config()
    decay_rate: float = config.get("decay_rate", 0.02)
    decay_interval_days: int = config.get("decay_interval_days", 7)

    if reference_date is not None:
        ref_dt = _parse_date(reference_date)
    else:
        ref_dt = datetime.now(timezone.utc).replace(tzinfo=None)

    decayed_count = 0
    for edge in ctx.edges:
        if edge.get("source_type") == "manual":
            continue

        last_str = edge.get("last", _today_iso())
        last_dt = _parse_date(last_str)
        age_days = (ref_dt - last_dt).days
        if age_days < 0:
            age_days = 0

        decay_cycles = age_days // decay_interval_days
        if decay_cycles == 0:
            continue

        multiplier = 2.0 if edge.get("inferred", "").lower() == "true" else 1.0
        total_decay = decay_rate * decay_cycles * multiplier

        current_conf = float(edge.get("confidence", "0.5"))
        new_conf = max(0.0, round(current_conf - total_decay, 10))

        if new_conf != current_conf:
            edge["confidence"] = str(new_conf)
            decayed_count += 1

    return decayed_count


def run_pruning(
    ctx: CtxFile, reference_date: str | None = None
) -> tuple[int, list[dict[str, str]]]:
    """Remove stale low-confidence edges from ctx, returning archived edges.

    Never prune:
    - source_type=manual
    - confidence > 0.8

    Archive (remove from ctx.edges) when any of:
    - seen <= 1 AND confidence < 0.3 AND age > 30 days
    - inferred=true AND confidence < 0.2 AND age > 14 days

    Returns (count_pruned, archived_edges_list).
    """
    config = load_config()
    prune_min_confidence: float = config.get("prune_min_confidence", 0.3)
    prune_min_age_days: int = config.get("prune_min_age_days", 30)

    if reference_date is not None:
        ref_dt = _parse_date(reference_date)
    else:
        ref_dt = datetime.now(timezone.utc).replace(tzinfo=None)

    to_keep: list[dict[str, str]] = []
    to_archive: list[dict[str, str]] = []

    for edge in ctx.edges:
        # Never prune manual edges
        if edge.get("source_type") == "manual":
            to_keep.append(edge)
            continue

        confidence = float(edge.get("confidence", "0.5"))

        # Never prune high-confidence edges
        if confidence > 0.8:
            to_keep.append(edge)
            continue

        last_str = edge.get("last", _today_iso())
        last_dt = _parse_date(last_str)
        age_days = (ref_dt - last_dt).days
        if age_days < 0:
            age_days = 0

        seen = int(edge.get("seen", "1"))
        is_inferred = edge.get("inferred", "").lower() == "true"

        should_archive = False

        # Rule 1: stale low-confidence
        if seen <= 1 and confidence < prune_min_confidence and age_days > prune_min_age_days:
            should_archive = True

        # Rule 2: inferred edges that haven't gained traction
        if is_inferred and confidence < 0.2 and age_days > 14:
            should_archive = True

        if should_archive:
            to_archive.append(edge)
        else:
            to_keep.append(edge)

    ctx.edges = to_keep
    return len(to_archive), to_archive


# ---------------------------------------------------------------------------
# Extraction Logic — Selective Observer
# ---------------------------------------------------------------------------

# Business line detection patterns
BUSINESS_PATTERNS = {
    "prdm": ["prdm", "political-risk", "03-PRDM"],
    "subarb": ["subarb", "llm-manager", "04-Subarb", "LLM Manager"],
    "dossier": ["dossier", "05-Dossier"],
    "exergy-international": ["exergy", "prospecting", "02-Exergy"],
    "nexus": ["nexus", "07-Nexus"],
    "higgins": ["higgins", "10-Higgins"],
}

SERVICE_PATTERNS = {
    "beehiiv": ["beehiiv.com", "beehiiv"],
    "gumroad": ["gumroad.com", "gumroad"],
    "teachable": ["teachable.com", "teachable"],
    "slack": ["slack.com", "slack_tools", "#prdm", "#subarb", "#dossier", "#exergy", "#higgins"],
}

IGNORE_COMMANDS = ["git ", "cd ", "ls ", "cat ", "echo ", "pwd"]


def extract_observations(tool_name: str, tool_input: dict, tool_output: str) -> list[dict]:
    """Extract entity-relationship observations from a tool call.

    Selective — only extracts business context, services, and scripts.
    Returns list of observation dicts.
    """
    observations: list[dict] = []

    if tool_name == "Bash":
        command = tool_input.get("command", "")

        # Ignore housekeeping commands
        for prefix in IGNORE_COMMANDS:
            if command.startswith(prefix):
                return []

        # Detect business line
        command_lower = command.lower()
        for biz_id, patterns in BUSINESS_PATTERNS.items():
            for pattern in patterns:
                if pattern.lower() in command_lower:
                    observations.append({
                        "type": "edge",
                        "source": "scott",
                        "rel": "worked_on",
                        "target": biz_id,
                        "source_type": "behavior",
                    })
                    break  # one match per business line is enough

        # Detect service usage
        for svc_id, patterns in SERVICE_PATTERNS.items():
            for pattern in patterns:
                if pattern.lower() in command_lower:
                    observations.append({
                        "type": "node",
                        "id": svc_id,
                        "node_type": "service",
                        "description": f"External service: {svc_id}",
                    })
                    observations.append({
                        "type": "edge",
                        "source": "scott",
                        "rel": "uses_service",
                        "target": svc_id,
                        "source_type": "behavior",
                    })
                    break  # one match per service is enough

        # Detect script execution: python scripts/SCRIPTNAME.py
        script_match = re.search(r"python\s+scripts/([a-zA-Z0-9_\-]+)\.py", command)
        if script_match:
            raw_name = script_match.group(1)
            # Convert underscores to hyphens then normalize
            normalized = normalize_id(raw_name.replace("_", "-"))
            observations.append({
                "type": "edge",
                "source": "scott",
                "rel": "ran_script",
                "target": normalized,
                "source_type": "behavior",
            })

    elif tool_name in ("Read", "Write", "Edit"):
        file_path = tool_input.get("file_path", "")
        file_path_lower = file_path.lower()

        # Only extract business line — no file nodes
        for biz_id, patterns in BUSINESS_PATTERNS.items():
            for pattern in patterns:
                if pattern.lower() in file_path_lower:
                    observations.append({
                        "type": "edge",
                        "source": "scott",
                        "rel": "worked_on",
                        "target": biz_id,
                        "source_type": "behavior",
                    })
                    break  # one match per business line is enough

    return observations


# ---------------------------------------------------------------------------
# Pending file operations
# ---------------------------------------------------------------------------


def append_pending(observations, pending_path=None):
    """Append observations to pending.ctx."""
    path = pending_path or (CTX_DIR / "pending.ctx")
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = _now_iso()
    with open(path, "a", encoding="utf-8") as f:
        for obs in observations:
            f.write(f"{timestamp} | {json.dumps(obs)}\n")


def read_pending(pending_path=None):
    """Read and parse all pending observations."""
    path = pending_path or (CTX_DIR / "pending.ctx")
    if not path.exists():
        return []
    observations = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(" | ", 1)
            if len(parts) == 2:
                try:
                    obs = json.loads(parts[1])
                    obs["_timestamp"] = parts[0]
                    observations.append(obs)
                except json.JSONDecodeError:
                    continue
    return observations


def clear_pending(pending_path=None):
    """Clear the pending file."""
    path = pending_path or (CTX_DIR / "pending.ctx")
    with open(path, "w", encoding="utf-8") as f:
        f.write("")


def log_change(action, details, changelog_path=None):
    """Append a change entry to changelog.ctx."""
    path = changelog_path or (CTX_DIR / "changelog.ctx")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{_now_iso()} | {action} | {details}\n")


# ---------------------------------------------------------------------------
# Merge logic — pending into context
# ---------------------------------------------------------------------------


def merge_pending(ctx_path=None, pending_path=None, changelog_path=None):
    """Process pending observations and merge into context.ctx. Returns change count."""
    ctx_path = ctx_path or (CTX_DIR / "context.ctx")
    pending_path = pending_path or (CTX_DIR / "pending.ctx")
    changelog_path = changelog_path or (CTX_DIR / "changelog.ctx")

    observations = read_pending(pending_path)
    if not observations:
        return 0

    ctx = CtxFile(ctx_path)
    owner = ctx.meta.get("owner", "scott")

    if not ctx.has_node(owner):
        ctx.add_node(owner, "person", "file owner")

    changes = 0

    for obs in observations:
        obs_type = obs.get("type")

        if obs_type == "node":
            node_id = obs.get("id", "")
            if not node_id:
                continue
            node_id = ctx.resolve_alias(node_id)
            if ctx.add_node(node_id, obs.get("node_type", "unknown"), obs.get("description", "")):
                log_change("ADD_NODE", f"{node_id} | {obs.get('node_type')} | {obs.get('description')}", changelog_path)
                changes += 1

        elif obs_type == "edge":
            source = ctx.resolve_alias(obs.get("source", ""))
            target = ctx.resolve_alias(obs.get("target", ""))
            rel = obs.get("rel", "")

            if not source or not target or not rel:
                continue

            if not ctx.has_node(source):
                ctx.add_node(source, "unknown", source)
            if not ctx.has_node(target):
                ctx.add_node(target, "unknown", target)

            metadata = {}
            for k in ("source_type", "inferred", "context", "note"):
                if k in obs:
                    metadata[k] = obs[k]

            result = ctx.add_edge(source, rel, target, **metadata)
            if result == "added":
                log_change("ADD_EDGE", f"{source} > {rel} > {target}", changelog_path)
                changes += 1
            elif result == "updated":
                log_change("UPDATE_EDGE", f"{source} > {rel} > {target}", changelog_path)
                changes += 1

    ctx.write(ctx_path)
    clear_pending(pending_path)
    return changes
