"""
Nightly merge script for the Perpetual Context Cartographer.

Merges pending observations into the main context graph,
runs confidence decay, and prunes stale edges.

Usage:
    python merge.py

Schedule to run daily (e.g., 11:45 PM).
"""

import json
import logging
import sys
from pathlib import Path

from cartographer import CTX_DIR, CtxFile, merge_pending, decay_edges, prune_edges

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)


def main():
    ctx_path = CTX_DIR / "context.ctx"
    pending_path = CTX_DIR / "pending.ctx"
    archive_path = CTX_DIR / "archive.ctx"

    if not ctx_path.exists():
        logger.error("No context.ctx found. Create one from context.ctx.example first.")
        sys.exit(1)

    ctx = CtxFile(ctx_path)

    # Merge pending observations
    changes = 0
    if pending_path.exists():
        changes = merge_pending(ctx, pending_path)
        logger.info(f"Merged {changes} changes from pending")
        # Clear pending
        pending_path.write_text("", encoding="utf-8")

    # Decay unobserved edges
    decayed = decay_edges(ctx)
    logger.info(f"Decayed {decayed} edges")

    # Prune low-confidence stale edges
    pruned = prune_edges(ctx, archive_path)
    logger.info(f"Pruned {pruned} edges")

    # Save updated context
    ctx.save(ctx_path)

    # Write summary
    summary = {
        "nodes": len(ctx.nodes),
        "edges": len(ctx.edges),
        "changes": changes,
        "decayed": decayed,
        "pruned": pruned,
        "contradictions": 0,
        "timestamp": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
    }
    summary_path = CTX_DIR / "nightly_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    logger.info(f"Summary: {summary['nodes']} nodes, {summary['edges']} edges, "
                f"{changes} changes, {decayed} decayed, {pruned} pruned, 0 contradictions")
    logger.info("Cartographer nightly merge complete.")


if __name__ == "__main__":
    main()
