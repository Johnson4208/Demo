import json
import sqlite3
from pathlib import Path
from config import DB_PATH, STORAGE_DIR, APP_VERSION, PARSER_VERSION, initialize_persistent_storage

class _ManagedConnection:
    def __init__(self, path):
        self._conn=sqlite3.connect(path, timeout=30)
        self._conn.row_factory=sqlite3.Row
        self._conn.execute("PRAGMA busy_timeout=30000")
        self._conn.execute("PRAGMA foreign_keys=ON")
    def __enter__(self):
        self._conn.__enter__(); return self._conn
    def __exit__(self, exc_type, exc, tb):
        try: return self._conn.__exit__(exc_type, exc, tb)
        finally: self._conn.close()
    def __getattr__(self,name): return getattr(self._conn,name)

def connect():
    STORAGE_DIR.mkdir(parents=True,exist_ok=True)
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    return _ManagedConnection(DB_PATH)

def _ensure_column(conn,table,column,definition):
    columns={row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns: conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

def init_db():
    initialize_persistent_storage()
    with connect() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript("""
        CREATE TABLE IF NOT EXISTS documents(
            id INTEGER PRIMARY KEY,
            path TEXT UNIQUE,
            company TEXT,
            industry TEXT,
            year INTEGER,
            period_end TEXT,
            scope TEXT DEFAULT 'unknown',
            parser_version TEXT,
            sha256 TEXT,
            text TEXT,
            indexed_at TEXT DEFAULT CURRENT_TIMESTAMP,
            quality_score REAL DEFAULT 0,
            status TEXT DEFAULT 'review',
            warnings TEXT DEFAULT '[]',
            ocr_used INTEGER DEFAULT 0,
            app_version TEXT
        );
        CREATE TABLE IF NOT EXISTS observations(
            id INTEGER PRIMARY KEY,
            company TEXT,
            industry TEXT,
            year INTEGER,
            period_end TEXT,
            metric TEXT,
            value REAL,
            unit TEXT,
            source_path TEXT,
            confidence REAL DEFAULT 0.5,
            source_type TEXT DEFAULT 'statement',
            comparison_value REAL,
            UNIQUE(company,year,metric,source_path)
        );
        CREATE TABLE IF NOT EXISTS model_runs(id INTEGER PRIMARY KEY,company TEXT,model TEXT,result_json TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        -- Version-neutral scan history. Each report hash can keep multiple parser/app
        -- versions so upgrading or rolling back the application does not destroy
        -- previously verified extracted values.
        CREATE TABLE IF NOT EXISTS scan_snapshots(
            id INTEGER PRIMARY KEY,
            source_path TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            parser_version TEXT NOT NULL,
            app_version TEXT NOT NULL,
            company TEXT,
            industry TEXT,
            year INTEGER,
            period_end TEXT,
            scope TEXT DEFAULT 'unknown',
            text TEXT,
            quality_score REAL DEFAULT 0,
            status TEXT DEFAULT 'review',
            warnings TEXT DEFAULT '[]',
            ocr_used INTEGER DEFAULT 0,
            indexed_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(source_path,sha256,parser_version)
        );
        CREATE TABLE IF NOT EXISTS scan_snapshot_observations(
            id INTEGER PRIMARY KEY,
            snapshot_id INTEGER NOT NULL,
            company TEXT,
            industry TEXT,
            year INTEGER,
            period_end TEXT,
            metric TEXT,
            value REAL,
            unit TEXT,
            source_path TEXT,
            confidence REAL DEFAULT 0.5,
            source_type TEXT DEFAULT 'statement',
            comparison_value REAL,
            FOREIGN KEY(snapshot_id) REFERENCES scan_snapshots(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_scan_snapshots_hash ON scan_snapshots(source_path,sha256,parser_version);
        CREATE INDEX IF NOT EXISTS idx_scan_snapshot_obs ON scan_snapshot_observations(snapshot_id);
        CREATE INDEX IF NOT EXISTS idx_obs_company_metric_period ON observations(company,metric,period_end);
        CREATE INDEX IF NOT EXISTS idx_docs_company_period ON documents(company,period_end);
        """)
        for table,column,definition in [
            ("documents","period_end","TEXT"),("documents","scope","TEXT DEFAULT 'unknown'"),
            ("documents","quality_score","REAL DEFAULT 0"),("documents","status","TEXT DEFAULT 'review'"),
            ("documents","warnings","TEXT DEFAULT '[]'"),("documents","ocr_used","INTEGER DEFAULT 0"),
            ("documents","app_version","TEXT"),
            ("observations","period_end","TEXT"),("observations","source_type","TEXT DEFAULT 'statement'"),("observations","comparison_value","REAL")
        ]: _ensure_column(c,table,column,definition)
        c.commit()
    repair_period_metadata()


def _quarter_period_from_filename(path):
    """Return a strong quarter period from a filename, or None."""
    try:
        from .report_reader import _period_from_filename
        import re
        name=Path(str(path).replace("\\","/")).name.lower()
        explicit = ("quy" in name) or ("quý" in name) or ("quarter" in name) or bool(re.search(r"(?<![a-z])q[1-4](?!\d)", name))
        if not explicit:
            return None
        value=_period_from_filename(name)
        return value.isoformat() if value else None
    except Exception:
        return None

def repair_period_metadata():
    """Repair stale quarter dates from previous parser versions.

    Older databases could store quarterly FPT reports as 31-Dec-2025 because an
    upload/signature date was selected before the filename-aware period parser was
    introduced.  The quarter marker in the filename is strong evidence, so both the
    document and its observations are moved together to the correct quarter-end.
    """
    changed=0
    with connect() as c:
        rows=c.execute("SELECT path,period_end FROM documents").fetchall()
        for row in rows:
            inferred=_quarter_period_from_filename(row[0])
            if not inferred or inferred==row[1]:
                continue
            c.execute("UPDATE documents SET period_end=?, year=? WHERE path=?",(inferred,int(inferred[:4]),row[0]))
            c.execute("UPDATE observations SET period_end=?, year=? WHERE source_path=?",(inferred,int(inferred[:4]),row[0]))
            changed+=1
        c.commit()
    return changed



def _snapshot_observation_values(observations):
    values=[]
    for item in observations or []:
        metric,value,unit,confidence,source_type,*rest=item
        comparison=rest[0] if rest else None
        if value is None:
            continue
        values.append((metric,value,unit,confidence,source_type,comparison))
    return values


def save_scan_snapshot(path, sha256, parser_version, *, company, industry, year,
                        period_end, scope, text, quality_score=0, status="review",
                        warnings=None, ocr_used=0, observations=None, app_version=APP_VERSION):
    """Persist a complete scan result keyed by report hash + parser version."""
    with connect() as c:
        row=c.execute(
            "SELECT id FROM scan_snapshots WHERE source_path=? AND sha256=? AND parser_version=?",
            (str(path),str(sha256),str(parser_version)),
        ).fetchone()
        if row:
            return int(row[0])
        cur=c.execute("""
            INSERT INTO scan_snapshots(
                source_path,sha256,parser_version,app_version,company,industry,year,period_end,
                scope,text,quality_score,status,warnings,ocr_used
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,(
            str(path),str(sha256),str(parser_version),str(app_version),company,industry,year,period_end,
            scope,text,float(quality_score or 0),status,json.dumps(warnings or [],ensure_ascii=False),int(bool(ocr_used)),
        ))
        snapshot_id=int(cur.lastrowid)
        for metric,value,unit,confidence,source_type,comparison in _snapshot_observation_values(observations):
            c.execute("""
                INSERT INTO scan_snapshot_observations(
                    snapshot_id,company,industry,year,period_end,metric,value,unit,source_path,
                    confidence,source_type,comparison_value
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """,(
                snapshot_id,company,industry,year,period_end,metric,value,unit,str(path),
                confidence,source_type,comparison,
            ))
        c.commit()
        return snapshot_id


def snapshot_exists(path, sha256, parser_version):
    with connect() as c:
        row=c.execute(
            "SELECT id,app_version,indexed_at FROM scan_snapshots WHERE source_path=? AND sha256=? AND parser_version=?",
            (str(path),str(sha256),str(parser_version)),
        ).fetchone()
        return dict(row) if row else None


def snapshot_current_document(path):
    """Archive the current document/observations before replacing them."""
    with connect() as c:
        doc=c.execute("SELECT * FROM documents WHERE path=?",(str(path),)).fetchone()
        if not doc or not doc["sha256"] or not doc["parser_version"]:
            return None
        already=c.execute(
            "SELECT id FROM scan_snapshots WHERE source_path=? AND sha256=? AND parser_version=?",
            (str(path),str(doc["sha256"]),str(doc["parser_version"])),
        ).fetchone()
        if already:
            return int(already[0])
        obs=[tuple(r) for r in c.execute("""
            SELECT metric,value,unit,confidence,source_type,comparison_value
            FROM observations WHERE source_path=? ORDER BY id
        """,(str(path),)).fetchall()]
        cur=c.execute("""
            INSERT INTO scan_snapshots(
                source_path,sha256,parser_version,app_version,company,industry,year,period_end,
                scope,text,quality_score,status,warnings,ocr_used
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,(
            str(path),doc["sha256"],doc["parser_version"],doc["app_version"] or APP_VERSION,doc["company"],doc["industry"],
            doc["year"],doc["period_end"],doc["scope"],doc["text"],doc["quality_score"],doc["status"],
            doc["warnings"] or "[]",doc["ocr_used"] or 0,
        ))
        sid=int(cur.lastrowid)
        for item in obs:
            metric,value,unit,confidence,source_type,comparison=item
            c.execute("""
                INSERT INTO scan_snapshot_observations(
                    snapshot_id,company,industry,year,period_end,metric,value,unit,source_path,
                    confidence,source_type,comparison_value
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """,(sid,doc["company"],doc["industry"],doc["year"],doc["period_end"],metric,value,unit,str(path),confidence,source_type,comparison))
        c.commit()
        return sid


def restore_snapshot(path, sha256, parser_version):
    """Restore a previously scanned result without re-running OCR/extraction."""
    with connect() as c:
        snap=c.execute("""
            SELECT * FROM scan_snapshots
            WHERE source_path=? AND sha256=? AND parser_version=?
            ORDER BY id DESC LIMIT 1
        """,(str(path),str(sha256),str(parser_version))).fetchone()
        if not snap:
            return None
        c.execute("DELETE FROM observations WHERE source_path=?",(str(path),))
        c.execute("DELETE FROM documents WHERE path=?",(str(path),))
        c.execute("""
            INSERT INTO documents(path,company,industry,year,period_end,scope,parser_version,sha256,text,quality_score,status,warnings,ocr_used,indexed_at,app_version)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,(
            str(path),snap["company"],snap["industry"],snap["year"],snap["period_end"],snap["scope"],
            snap["parser_version"],snap["sha256"],snap["text"],snap["quality_score"],snap["status"],snap["warnings"],snap["ocr_used"],snap["indexed_at"],snap["app_version"],
        ))
        rows=c.execute("""
            SELECT company,industry,year,period_end,metric,value,unit,source_path,confidence,source_type,comparison_value
            FROM scan_snapshot_observations WHERE snapshot_id=? ORDER BY id
        """,(snap["id"],)).fetchall()
        for r in rows:
            c.execute("""
                INSERT INTO observations(company,industry,year,period_end,metric,value,unit,source_path,confidence,source_type,comparison_value)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,tuple(r))
        c.commit()
        return {
            "snapshot_id": int(snap["id"]),
            "app_version": snap["app_version"],
            "parser_version": snap["parser_version"],
            "observations": len(rows),
            "indexed_at": snap["indexed_at"],
        }


def existing_document(path):
    with connect() as c:
        row=c.execute("SELECT * FROM documents WHERE path=?",(str(path),)).fetchone(); return dict(row) if row else None

def observation_count(path):
    with connect() as c:
        row=c.execute("SELECT COUNT(*) FROM observations WHERE source_path=?",(str(path),)).fetchone()
        return int(row[0] or 0)

def replace_document(path,company,industry,year,period_end,scope,parser_version,sha256,text,quality_score=0,status="review",warnings=None,ocr_used=0,app_version=APP_VERSION):
    with connect() as c:
        c.execute("DELETE FROM documents WHERE path=?",(str(path),))
        c.execute("INSERT INTO documents(path,company,industry,year,period_end,scope,parser_version,sha256,text,quality_score,status,warnings,ocr_used,app_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (str(path),company,industry,year,period_end,scope,parser_version,sha256,text,float(quality_score or 0),status,json.dumps(warnings or [],ensure_ascii=False),int(bool(ocr_used)),str(app_version)))
        c.commit()

def replace_observations(source_path,company,industry,year,period_end,observations):
    with connect() as c:
        c.execute("DELETE FROM observations WHERE source_path=?",(str(source_path),))
        for item in observations:
            metric,value,unit,confidence,source_type,*rest=item; comparison=rest[0] if rest else None
            if value is None: continue
            c.execute("INSERT OR REPLACE INTO observations(company,industry,year,period_end,metric,value,unit,source_path,confidence,source_type,comparison_value) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                      (company,industry,year,period_end,metric,value,unit,str(source_path),confidence,source_type,comparison))
        c.commit()

def prune_missing_documents(root):
    root=Path(root).resolve().as_posix().rstrip("/")
    with connect() as c:
        rows=c.execute("SELECT path FROM documents").fetchall(); stale=[]
        for row in rows:
            normalized=Path(str(row[0]).replace("\\","/")).resolve().as_posix()
            if not normalized.startswith(root+"/"): stale.append(row[0])
        for path in stale:
            c.execute("DELETE FROM observations WHERE source_path=?",(path,)); c.execute("DELETE FROM documents WHERE path=?",(path,))
        c.commit(); return len(stale)

def companies():
    with connect() as c:
        rows=c.execute("""
            SELECT company, industry, COUNT(*) reports, MIN(year) first_year, MAX(year) last_year,
                   COALESCE(MAX(CASE WHEN scope='consolidated' THEN period_end END), MAX(period_end)) latest_period
            FROM documents
            GROUP BY company, industry
            ORDER BY company
        """).fetchall()
        return [dict(r) for r in rows]

def company_documents(company):
    with connect() as c: return [dict(r) for r in c.execute("SELECT * FROM documents WHERE company=? ORDER BY COALESCE(period_end,''),year,id",(company,)).fetchall()]

def observations(company,metrics=None):
    with connect() as c:
        params=[company]; where="o.company=?"
        if metrics:
            where+=f" AND o.metric IN ({','.join('?' for _ in metrics)})"; params.extend(metrics)
        return [dict(r) for r in c.execute(f"SELECT o.*,d.scope,d.indexed_at,d.status document_status,d.quality_score document_quality,d.warnings document_warnings FROM observations o LEFT JOIN documents d ON d.path=o.source_path WHERE {where} ORDER BY COALESCE(o.period_end,''),o.year,CASE WHEN d.scope='consolidated' THEN 1 WHEN d.scope='unknown' THEN 0 ELSE -1 END,o.source_path",params).fetchall()]

def industries():
    with connect() as c: return [r[0] for r in c.execute("SELECT DISTINCT industry FROM documents ORDER BY industry").fetchall()]

def peers(company):
    with connect() as c:
        row=c.execute("SELECT industry FROM documents WHERE company=? ORDER BY COALESCE(period_end,'') DESC,id DESC LIMIT 1",(company,)).fetchone()
        if not row:return []
        return [dict(r) for r in c.execute("SELECT company,industry,COUNT(*) reports,MIN(year) first_year,MAX(year) last_year FROM documents WHERE industry=? GROUP BY company,industry ORDER BY company",(row[0],)).fetchall()]
