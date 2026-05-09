#!/usr/bin/env python3
"""
Vault duplicate node merger — Mneme-native deduplication with synapse-strength priority.

Usage:
    mneme dedup --vault /path/to/vault --db /path/to/db.sqlite [--dry-run] [--auto]
    mneme dedup --vault /path/to/vault --db /path/to/db.sqlite --title-threshold 0.8 --content-threshold 0.7
"""

import hashlib
import json
import re
import shutil
import sqlite3
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Optional, Tuple

DEFAULT_BACKUP_DIR = os.path.expanduser("~/.hermes/vault_backups")
SIMILARITY_THRESHOLD = 0.75
CONTENT_OVERLAP_THRESHOLD = 0.6
MIN_SYNAPSE_STRENGTH_DIFF = 0.5

EXCLUDE_PATTERNS = [
    'venv/', 'node_modules/', '__pycache__/', '.git/',
    'Archives/', 'langextract_env/', 'vision_venv/',
    'timeline_server/', 'skills/'
]


def normalize_title(title: str) -> str:
    """Normalize a title for comparison (lowercase, remove special chars)."""
    title = title.lower().strip()
    title = re.sub(r'[^a-z0-9\s]', '', title)
    title = re.sub(r'\s+', ' ', title)
    return title


def title_similarity(title1: str, title2: str) -> float:
    """Calculate similarity between two titles (0.0 to 1.0)."""
    n1, n2 = normalize_title(title1), normalize_title(title2)
    if n1 == n2:
        return 1.0
    return SequenceMatcher(None, n1, n2).ratio()


def content_overlap(content1: str, content2: str) -> float:
    """Calculate content overlap ratio (shared lines / total unique lines)."""
    lines1 = set(line.strip() for line in content1.split('\n') if line.strip())
    lines2 = set(line.strip() for line in content2.split('\n') if line.strip())
    if not lines1 and not lines2:
        return 1.0
    if not lines1 or not lines2:
        return 0.0
    intersection = lines1 & lines2
    union = lines1 | lines2
    return len(intersection) / len(union) if union else 0.0


def extract_date_from_path(filepath: Path) -> Optional[str]:
    """Extract YYYY-MM-DD date from filepath if present."""
    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', str(filepath))
    return date_match.group(1) if date_match else None


def is_daily_note_file(filepath: Path) -> bool:
    """Check if this is a daily note (memory/YYYY-MM-DD.md or Daily/YYYY-MM-DD.md)."""
    if not filepath.name.endswith('.md'):
        return False
    date_match = re.match(r'(\d{4}-\d{2}-\d{2})\.md$', filepath.name)
    if not date_match:
        return False
    path_str = str(filepath)
    daily_dirs = ['memory/', 'Daily/', 'daily/']
    return any(d in path_str for d in daily_dirs)


def should_merge_as_duplicates(file1: Dict, file2: Dict, title_sim: float, content_overlap: float,
                                title_threshold: float, content_threshold: float) -> bool:
    """
    Determine if two files should be considered duplicates.
    Special handling for daily notes: different dates = NOT duplicates.
    """
    if is_daily_note_file(file1['path']) and is_daily_note_file(file2['path']):
        date1 = extract_date_from_path(file1['path'])
        date2 = extract_date_from_path(file2['path'])
        if date1 and date2 and date1 != date2:
            return False

    if title_sim > 0.9 or content_overlap > content_threshold:
        return True

    return False


def extract_title_from_file(filepath: Path) -> Tuple[str, str]:
    """Extract title from markdown file (first H1 or filename). Returns (title, content)."""
    try:
        content = filepath.read_text(encoding='utf-8', errors='replace')
        h1_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
        if h1_match:
            return (h1_match.group(1).strip(), content)
        return (filepath.stem, content)
    except Exception as e:
        print(f"  ⚠️ Error reading {filepath}: {e}", file=__import__('sys').stderr)
        return (filepath.stem, "")


def get_synapse_strength_for_node(db_path: str, node_path: str) -> Tuple[float, int]:
    """
    Query Mneme DB for total synapse strength connected to a node.
    Returns (total_strength, synapse_count).

    Schema: nodes(source_path) -> synapses(src_node_id, dst_node_id, strength)
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT id FROM nodes WHERE source_path = ?", (node_path,))
        node_result = cursor.fetchone()

        if not node_result:
            return (0.0, 0)

        node_id = node_result[0]

        cursor.execute("""
            SELECT SUM(strength) as total_strength, COUNT(*) as synapse_count
            FROM synapses
            WHERE src_node_id = ? OR dst_node_id = ?
        """, (node_id, node_id))

        result = cursor.fetchone()
        conn.close()

        if result and result[0] is not None:
            return (float(result[0]), int(result[1]))
        return (0.0, 0)
    except Exception:
        return (0.0, 0)


def merge_content(content_primary: str, content_secondary: str, secondary_path: str) -> str:
    """
    Merge content from secondary into primary, avoiding exact duplicates.
    Adds a merge metadata section at the end.
    """
    sections = re.split(r'^(##+ .+)$', content_secondary, flags=re.MULTILINE)

    primary_lines = content_primary.rstrip().split('\n')

    for i in range(1, len(sections), 2):
        if i + 1 < len(sections):
            section_header = sections[i]
            section_content = sections[i + 1]

            section_title = section_header.strip('#').strip()
            if section_title not in content_primary:
                primary_lines.append('')
                primary_lines.append(section_header)
                primary_lines.extend(section_content.strip().split('\n'))

    merge_metadata = f"""

---
## 🔄 Merge Metadata
- **Merged from:** `{secondary_path}`
- **Merge date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- **Reason:** Duplicate node consolidation (synapse-strength priority)
"""

    return '\n'.join(primary_lines) + merge_metadata


def create_backup(filepath: Path, backup_dir: str) -> Path:
    """Create timestamped backup of a file."""
    backup_path = Path(backup_dir) / f"{filepath.stem}.{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(filepath, backup_path)
    return backup_path


def scan_vault_for_duplicates(vault_path: Path, db_path: str, similarity_threshold: float, content_threshold: float) -> List[Dict]:
    """Scan vault for duplicate nodes and return merge candidates."""
    md_files = list(vault_path.rglob("*.md"))
    md_files = [
        f for f in md_files
        if not any(pattern in str(f) for pattern in EXCLUDE_PATTERNS)
    ]

    file_data = []
    for filepath in md_files:
        if '.bak' in str(filepath) or 'node_modules' in str(filepath):
            continue

        title, content = extract_title_from_file(filepath)
        rel_path = str(filepath.relative_to(vault_path))
        strength, count = get_synapse_strength_for_node(db_path, rel_path)

        file_data.append({
            'path': filepath,
            'rel_path': rel_path,
            'title': title,
            'content': content,
            'synapse_strength': strength,
            'synapse_count': count
        })

    duplicates = []
    processed = set()

    for i, file1 in enumerate(file_data):
        if file1['rel_path'] in processed:
            continue

        group = [file1]
        for j, file2 in enumerate(file_data[i+1:], start=i+1):
            if file2['rel_path'] in processed:
                continue

            title_sim = title_similarity(file1['title'], file2['title'])
            if title_sim < similarity_threshold:
                continue

            content_ov = content_overlap(file1['content'], file2['content'])
            if not should_merge_as_duplicates(file1, file2, title_sim, content_ov, similarity_threshold, content_threshold):
                continue

            group.append(file2)
            processed.add(file2['rel_path'])

        if len(group) > 1:
            processed.add(file1['rel_path'])
            group.sort(key=lambda x: x['synapse_strength'], reverse=True)
            duplicates.append({
                'winner': group[0],
                'losers': group[1:],
                'title_similarity': title_similarity(group[0]['title'], group[1]['title'])
            })

    return duplicates


def merge_duplicates(duplicates: List[Dict], vault_path: Path, backup_dir: str, auto: bool = False, dry_run: bool = True, json_output: bool = False) -> Dict:
    """Perform the merge operations."""
    results = {
        'merged': [],
        'skipped': [],
        'errors': [],
        'backups': []
    }

    for dup_group in duplicates:
        winner = dup_group['winner']
        losers = dup_group['losers']

        if not json_output:
            print(f"\n📋 Merge candidate:")
            print(f"  🏆 Keep: {winner['rel_path']} (strength: {winner['synapse_strength']:.2f}, synapses: {winner['synapse_count']})")
            for loser in losers:
                print(f"  ❌ Delete: {loser['rel_path']} (strength: {loser['synapse_strength']:.2f}, synapses: {loser['synapse_count']})")

        if dry_run:
            if not json_output:
                print(f"  [DRY RUN] Would merge {len(losers)} node(s) into winner")
            results['merged'].append({
                'winner': winner['rel_path'],
                'losers': [l['rel_path'] for l in losers],
                'dry_run': True
            })
            continue

        if not auto:
            confirm = input("\n  Proceed with this merge? [y/N]: ").strip().lower()
            if confirm != 'y':
                if not json_output:
                    print(f"  ⏭️ Skipped")
                results['skipped'].append({
                    'winner': winner['rel_path'],
                    'losers': [l['rel_path'] for l in losers]
                })
                continue

        try:
            merged_content = winner['content']
            merged_from = []

            for loser in losers:
                backup_path = create_backup(loser['path'], backup_dir)
                results['backups'].append(str(backup_path))
                if not json_output:
                    print(f"  💾 Backed up: {loser['rel_path']} → {backup_path}")

                merged_content = merge_content(merged_content, loser['content'], loser['rel_path'])
                merged_from.append(loser['rel_path'])

                loser['path'].unlink()
                if not json_output:
                    print(f"  🗑️ Deleted: {loser['rel_path']}")

            winner['path'].write_text(merged_content, encoding='utf-8')
            if not json_output:
                print(f"  ✅ Updated: {winner['rel_path']}")

            results['merged'].append({
                'winner': winner['rel_path'],
                'losers': merged_from,
                'dry_run': False
            })

        except Exception as e:
            if not json_output:
                print(f"  ❌ Error: {e}")
            results['errors'].append({
                'winner': winner['rel_path'],
                'losers': [l['rel_path'] for l in losers],
                'error': str(e)
            })

    return results


def run_dedup(args) -> Dict:
    """Main entry point for mneme dedup command."""
    import sys

    vault_path = Path(args.vault) if args.vault else None
    db_path = Path(args.db) if args.db else None
    backup_dir = args.backup_dir or DEFAULT_BACKUP_DIR

    if not vault_path:
        return {"ok": False, "error": "Vault path required (--vault or config)"}
    if not db_path:
        return {"ok": False, "error": "Database path required (--db or config)"}

    if not vault_path.exists():
        return {"ok": False, "error": f"Vault not found: {vault_path}"}
    if not db_path.exists():
        return {"ok": False, "error": f"Mneme DB not found: {db_path}"}

    if not args.json:
        print(f"🔧 Vault Duplicate Node Merger")
        print(f"   Vault: {vault_path}")
        print(f"   DB: {db_path}")
        print(f"   Mode: {'DRY RUN' if args.dry_run else 'LIVE'} {'(auto-confirm)' if args.auto else '(manual confirm)'}")
        print()

    duplicates = scan_vault_for_duplicates(
        vault_path,
        str(db_path),
        args.title_threshold,
        args.content_threshold
    )

    if not duplicates:
        result = {"ok": True, "duplicates_found": 0, "message": "No duplicates found"}
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("\n✅ No duplicates found!")
        return result

    if not args.json:
        print(f"\n📊 Found {len(duplicates)} duplicate groups")

    results = merge_duplicates(
        duplicates,
        vault_path,
        backup_dir,
        auto=args.auto,
        dry_run=args.dry_run,
        json_output=args.json
    )

    summary = {
        "ok": True,
        "duplicates_found": len(duplicates),
        "merged": len(results['merged']),
        "skipped": len(results['skipped']),
        "errors": len(results['errors']),
        "backups": len(results['backups']),
        "backup_dir": backup_dir,
        "details": results
    }

    if not args.json:
        print(f"\n{'='*60}")
        print(f"📈 Summary:")
        print(f"   ✅ Merged: {len(results['merged'])} groups")
        print(f"   ⏭️ Skipped: {len(results['skipped'])} groups")
        print(f"   ❌ Errors: {len(results['errors'])} groups")
        print(f"   💾 Backups: {len(results['backups'])} files")
        if results['backups']:
            print(f"\n   Backups stored in: {backup_dir}")
        if results['errors']:
            print(f"\n   Errors:")
            for err in results['errors']:
                print(f"     - {err['winner']}: {err['error']}")

    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))

    return summary
