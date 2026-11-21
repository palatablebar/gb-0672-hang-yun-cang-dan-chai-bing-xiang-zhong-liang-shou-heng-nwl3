import hashlib, json
from datetime import datetime, timezone
from app.config import RULE_VERSION

def digest(raw, context, carrier):
    # 承运人纳入指纹：相同舱单内容在不同承运人名下得到不同批号，
    # 从根上杜绝按内容全局复用导致的跨承运人越权。
    # 各段带长度前缀，避免拼接歧义。
    payload = json.dumps(context, ensure_ascii=False, sort_keys=True).encode()
    h = hashlib.sha256()
    h.update(str(len(carrier)).encode()); h.update(carrier.encode())
    h.update(str(len(raw)).encode()); h.update(raw)
    h.update(str(len(payload)).encode()); h.update(payload)
    h.update(RULE_VERSION.encode())
    return h.hexdigest()

def make_manifest(source_digest, source, elapsed, carrier):
    return {'run_id':source_digest[:16], 'sha256':source_digest, 'rule_version':RULE_VERSION,
            'carrier':carrier,
            'source':source, 'generated_at':datetime.now(timezone.utc).isoformat(),
            'elapsed_ms':round(elapsed*1000,3), 'timezone':'Asia/Shanghai'}
