from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


class PromptLibrary:
    """Local approved prompts. Each write is an atomic SQLite transaction."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                db.execute('''CREATE TABLE IF NOT EXISTS approved_prompts (
                    id TEXT PRIMARY KEY, prompt TEXT NOT NULL,
                    created_at TEXT NOT NULL, model TEXT NOT NULL,
                    workflow TEXT NOT NULL, prompt_type TEXT NOT NULL,
                    UNIQUE(prompt, model, workflow, prompt_type)
                )''')
        except Exception:
            db.close()
            raise
        return db

    def save(self, prompt, *, approved=False, model='', workflow='', prompt_type=''):
        if not approved:
            raise ValueError('Approve the current prompt before saving.')
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError('The prompt cannot be empty.')
        with closing(self._connect()) as db, db:
            cursor = db.execute(
                'INSERT OR IGNORE INTO approved_prompts VALUES (?, ?, ?, ?, ?, ?)',
                (uuid4().hex, prompt, datetime.now(timezone.utc).isoformat(),
                 model or '', workflow or '', prompt_type or ''),
            )
            return cursor.rowcount == 1

    def list(self, query='', workflow=None, prompt_type=None):
        with closing(self._connect()) as db:
            rows = [dict(row) for row in db.execute(
                'SELECT * FROM approved_prompts ORDER BY created_at DESC, id DESC'
            )]
        query = query.casefold().strip()
        return [row for row in rows
                if (workflow is None or row['workflow'] == workflow)
                and (prompt_type is None or row['prompt_type'] == prompt_type)
                and (not query or query in ' '.join(str(v) for v in row.values()).casefold())]

    def delete(self, prompt_id):
        with closing(self._connect()) as db, db:
            return db.execute('DELETE FROM approved_prompts WHERE id = ?',
                              (prompt_id,)).rowcount == 1
