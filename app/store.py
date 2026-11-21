import sqlite3, json
from pathlib import Path
from app.errors import BusinessError
from app.identity import DEFAULT_CARRIER

def connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con=sqlite3.connect(path,timeout=15)
    con.row_factory=sqlite3.Row
    con.execute('PRAGMA journal_mode=WAL')
    con.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, carrier TEXT NOT NULL DEFAULT 'DEMO-CARRIER', digest TEXT NOT NULL, result TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT '待复核', created_seq INTEGER NOT NULL DEFAULT 0)")
    _migrate(con)
    con.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_carrier_digest ON runs(carrier,digest)')
    return con

def _migrate(con):
    # 旧库没有 carrier 列：重建表，把历史批次归到缺省演示承运人，
    # 避免承运人隔离上线后旧批静默消失或被越权读取。
    cols={r['name'] for r in con.execute('PRAGMA table_info(runs)')}
    if cols and 'carrier' not in cols:
        con.execute('ALTER TABLE runs RENAME TO runs_legacy')
        con.execute("CREATE TABLE runs (id TEXT PRIMARY KEY, carrier TEXT NOT NULL DEFAULT 'DEMO-CARRIER', digest TEXT NOT NULL, result TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT '待复核', created_seq INTEGER NOT NULL DEFAULT 0)")
        con.execute("INSERT INTO runs(id,carrier,digest,result,revision,status,created_seq) SELECT id,?,digest,result,revision,status,rowid FROM runs_legacy",(DEFAULT_CARRIER,))
        con.execute('DROP TABLE runs_legacy')

def _accession(result, reused, reused_run_id, carrier):
    # 批次接入结论：每次写入/复用都明确裁决口径、复用来源与证据归属。
    return {
        'policy':'carrier_scoped',
        'reused':reused,
        'carrier_id':carrier,
        'reused_run_id':reused_run_id if reused else None,
        'reuse_of':'本承运人上一次相同内容处理' if reused else None,
        'evidence_owner':carrier,
        'evidence_scope':'本批次全部证据（采信记录、隔离项、核验视图、归档导出）归属承运人 %s，其他承运人不可见、不可导出' % carrier,
    }

def save(path, result):
    run_id=result['manifest']['run_id']
    carrier=result['manifest']['carrier']
    with connect(path) as con:
        existed=con.execute('SELECT id FROM runs WHERE carrier=? AND digest=?',(carrier,result['manifest']['sha256'])).fetchone()
        cur=con.execute('INSERT OR IGNORE INTO runs(id,carrier,digest,result,created_seq) VALUES(?,?,?,?,COALESCE((SELECT MAX(created_seq)+1 FROM runs),1))',
                        (run_id,carrier,result['manifest']['sha256'],json.dumps(result,ensure_ascii=False)))
        reused=existed is not None or cur.rowcount==0
        reused_id=existed['id'] if existed else run_id
    state=get(path,run_id,carrier)
    state['accession']=_accession(result,reused,reused_id,carrier)
    return state

def get(path, run_id, carrier):
    with connect(path) as con:
        row=con.execute('SELECT * FROM runs WHERE id=? AND carrier=?',(run_id,carrier)).fetchone()
    # 跨承运人一律按“不存在”处理，不泄露批次是否真实存在
    if not row: raise BusinessError('NOT_FOUND','批次不存在或不属于当前承运人',404)
    result=json.loads(row['result']);result.update(revision=row['revision'],status=row['status'])
    # 读取即复用本承运人已固化的处理，接入结论随每次访问给出
    result['accession']=_accession(result,True,row['id'],carrier)
    return result

def history(path, carrier):
    with connect(path) as con:
        return [dict(r) for r in con.execute('SELECT id,revision,status,carrier FROM runs WHERE carrier=? ORDER BY created_seq DESC, rowid DESC LIMIT 100',(carrier,))]

def review(path,run_id,revision,carrier):
    with connect(path) as con:
        cur=con.execute('UPDATE runs SET revision=revision+1,status=? WHERE id=? AND carrier=? AND revision=?',('已复核',run_id,carrier,revision))
        if cur.rowcount!=1:
            if not con.execute('SELECT 1 FROM runs WHERE id=? AND carrier=?',(run_id,carrier)).fetchone():
                raise BusinessError('NOT_FOUND','批次不存在或不属于当前承运人',404)
            raise BusinessError('STALE_VERSION','复核版本已更新，请刷新',409)
    return get(path,run_id,carrier)
