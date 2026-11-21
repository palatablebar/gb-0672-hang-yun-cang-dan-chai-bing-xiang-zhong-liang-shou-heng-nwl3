# 批次接入裁决测试：只在本承运人范围内复用，跨承运人不可越权
import io, json, sqlite3, zipfile
from fastapi.testclient import TestClient
from app import main, store
from app.config import ROOT
from app.engine import evaluate
from app.identity import normalize_carrier, DEFAULT_CARRIER
from app.errors import BusinessError
import pytest

CARRIER_A = {'X-Carrier-Id': 'CARRIER-ALPHA'}
CARRIER_B = {'X-Carrier-Id': 'CARRIER-BETA'}


def _client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'DB_PATH', str(tmp_path / 'isolation.sqlite'))
    return TestClient(main.app)


def test_manifest_carrier_bound_into_digest():
    # 相同舱单内容，承运人不同 => 指纹与批号必须不同
    a = evaluate({'carrier_id': 'CARRIER-ALPHA'})
    b = evaluate({'carrier_id': 'CARRIER-BETA'})
    assert a['manifest']['sha256'] != b['manifest']['sha256']
    assert a['manifest']['run_id'] != b['manifest']['run_id']
    assert a['manifest']['carrier'] == 'CARRIER-ALPHA'
    assert b['manifest']['carrier'] == 'CARRIER-BETA'
    # 同一承运人相同内容 => 同批号
    a2 = evaluate({'carrier_id': 'CARRIER-ALPHA'})
    assert a2['manifest']['run_id'] == a['manifest']['run_id']


def test_same_carrier_retry_single_batch(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    first = c.post('/api/runs', json={}, headers=CARRIER_A).json()
    second = c.post('/api/runs', json={}, headers=CARRIER_A).json()
    assert first['manifest']['run_id'] == second['manifest']['run_id']
    # 第一次新建，第二次复用本承运人的同一次处理
    assert first['accession']['reused'] is False
    assert second['accession']['reused'] is True
    assert second['accession']['reused_run_id'] == first['manifest']['run_id']
    assert second['accession']['evidence_owner'] == 'CARRIER-ALPHA'
    # 同一承运人重试不新增第二条批次
    assert len(c.get('/api/runs', headers=CARRIER_A).json()) == 1


def test_identical_manifest_cross_carrier_distinct_batches(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    a = c.post('/api/runs', json={}, headers=CARRIER_A).json()
    b = c.post('/api/runs', json={}, headers=CARRIER_B).json()
    # 内容相同但承运人不同 => 两条独立批次
    assert a['manifest']['run_id'] != b['manifest']['run_id']
    assert a['manifest']['sha256'] != b['manifest']['sha256']
    history_a = c.get('/api/runs', headers=CARRIER_A).json()
    history_b = c.get('/api/runs', headers=CARRIER_B).json()
    assert [r['id'] for r in history_a] == [a['manifest']['run_id']]
    assert [r['id'] for r in history_b] == [b['manifest']['run_id']]


def test_cross_carrier_cannot_read_detail(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    a = c.post('/api/runs', json={}, headers=CARRIER_A).json()
    rid = a['manifest']['run_id']
    # B 不能读 A 的批次详情：按不存在处理，不泄露存在性
    resp = c.get('/api/runs/' + rid, headers=CARRIER_B)
    assert resp.status_code == 404
    assert resp.json()['code'] == 'NOT_FOUND'


def test_cross_carrier_cannot_read_history(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    a = c.post('/api/runs', json={}, headers=CARRIER_A).json()
    b = c.post('/api/runs', json={}, headers=CARRIER_B).json()
    # 历史严格按承运人隔离，互看不到对方批号
    ids_a = {r['id'] for r in c.get('/api/runs', headers=CARRIER_A).json()}
    ids_b = {r['id'] for r in c.get('/api/runs', headers=CARRIER_B).json()}
    assert a['manifest']['run_id'] in ids_a and b['manifest']['run_id'] not in ids_a
    assert b['manifest']['run_id'] in ids_b and a['manifest']['run_id'] not in ids_b


def test_cross_carrier_cannot_export(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    rid = c.post('/api/runs', json={}, headers=CARRIER_A).json()['manifest']['run_id']
    assert c.get('/api/export/' + rid, headers=CARRIER_B).status_code == 404
    # 本承运人可下载，且导出证据标注归属
    pkg = c.get('/api/export/' + rid, headers=CARRIER_A)
    assert pkg.status_code == 200
    z = zipfile.ZipFile(io.BytesIO(pkg.content))
    evidence = json.loads(z.read('evidence.json'))
    assert evidence['evidence_owner'] == 'CARRIER-ALPHA'
    manifest = json.loads(z.read('manifest.json'))
    assert manifest['carrier'] == 'CARRIER-ALPHA'


def test_cross_carrier_cannot_review_or_rerun(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    rid = c.post('/api/runs', json={}, headers=CARRIER_A).json()['manifest']['run_id']
    review = c.post('/api/runs/' + rid + '/review', json={'revision': 1}, headers=CARRIER_B)
    assert review.status_code == 404
    rerun = c.post('/api/runs/' + rid + '/rerun', json={}, headers=CARRIER_B)
    assert rerun.status_code == 404
    # 本承运人复核与重跑正常，且重跑批号不变
    assert c.post('/api/runs/' + rid + '/review', json={'revision': 1}, headers=CARRIER_A).status_code == 200
    rerun_a = c.post('/api/runs/' + rid + '/rerun', json={}, headers=CARRIER_A)
    assert rerun_a.status_code == 200
    assert rerun_a.json()['manifest']['run_id'] == rid
    # 重跑仍是复用，不新增批次
    assert len(c.get('/api/runs', headers=CARRIER_A).json()) == 1


def test_cross_carrier_html_page_blocked(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    rid = c.post('/api/runs', json={}, headers=CARRIER_A).json()['manifest']['run_id']
    blocked = c.get('/intake', params={'run_id': rid, 'carrier_id': 'CARRIER-BETA'})
    assert blocked.status_code == 404
    own = c.get('/intake', params={'run_id': rid, 'carrier_id': 'CARRIER-ALPHA'})
    assert own.status_code == 200
    # 页面导航链接带承运人参数，结论面板可见
    assert 'carrier_id=CARRIER-ALPHA' in own.text
    assert '批次接入结论' in own.text


def test_carrier_via_query_param_equivalent(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    via_header = c.post('/api/runs', json={}, headers=CARRIER_A).json()
    via_param = c.post('/api/runs', params={'carrier_id': 'carrier-alpha'}, json={}).json()
    # 查询参数与头等价（大小写规范化），复用同一条批次
    assert via_header['manifest']['run_id'] == via_param['manifest']['run_id']
    assert len(c.get('/api/runs', headers=CARRIER_A).json()) == 1


def test_invalid_carrier_rejected():
    for bad in ('', 'a', 'bad carrier!', '中文承运人', 'A' * 41):
        with pytest.raises(BusinessError) as exc:
            normalize_carrier(bad)
        assert exc.value.code == 'BAD_CARRIER'
    assert normalize_carrier(None) == DEFAULT_CARRIER
    assert normalize_carrier('carrier-alpha') == 'CARRIER-ALPHA'


def test_invalid_carrier_api_400(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    resp = c.post('/api/runs', json={}, headers={'X-Carrier-Id': 'bad carrier!'})
    assert resp.status_code == 400
    assert resp.json()['code'] == 'BAD_CARRIER'


def test_legacy_rows_migrate_to_default_carrier(tmp_path, monkeypatch):
    # 模拟隔离上线前的旧库：无 carrier 列、全局唯一 digest
    db = str(tmp_path / 'legacy.sqlite')
    state = evaluate()
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE runs (id TEXT PRIMARY KEY, digest TEXT UNIQUE NOT NULL, result TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT '待复核')")
    con.execute('INSERT INTO runs(id,digest,result) VALUES(?,?,?)',
                (state['manifest']['run_id'], state['manifest']['sha256'], json.dumps(state, ensure_ascii=False)))
    con.commit(); con.close()
    # 连接即迁移，旧批归入缺省演示承运人且仍可读
    got = store.get(db, state['manifest']['run_id'], DEFAULT_CARRIER)
    assert got['manifest']['sha256'] == state['manifest']['sha256']
    # 其他承运人仍读不到旧批
    with pytest.raises(BusinessError):
        store.get(db, state['manifest']['run_id'], 'CARRIER-ALPHA')


def test_custom_csv_carrier_scoped(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    original = (ROOT / 'sample_data' / 'clean.csv').read_text()
    first = original.splitlines()[1].split(',')[0]
    custom = original.replace(first, first + '-ISO')
    a = c.post('/api/runs', json={'csv_text': custom}, headers=CARRIER_A).json()
    b = c.post('/api/runs', json={'csv_text': custom}, headers=CARRIER_B).json()
    assert a['manifest']['run_id'] != b['manifest']['run_id']
    assert c.get('/api/export/' + a['manifest']['run_id'], headers=CARRIER_B).status_code == 404
