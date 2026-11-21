from importlib import import_module
from pathlib import Path
from copy import deepcopy
import json, time, base64
from app.config import ROOT, MODULES, MAX_BYTES
from app.errors import BusinessError
from app.identity import normalize_carrier, DEFAULT_CARRIER
from app.manifest import digest, make_manifest

def evaluate(payload=None, until=7, snapshot=None):
    payload=payload or {}
    dataset=payload.get('dataset','dirty')
    if dataset not in {'dirty','clean','legacy'}: raise BusinessError('BAD_DATASET','样例名称无效')
    if not isinstance(payload.get('overrides',{}),dict): raise BusinessError('BAD_CONTEXT','参数须为对象')
    raw=(base64.b64decode(snapshot['bytes_b64'],validate=True) if snapshot is not None else (str(payload['csv_text']).encode() if 'csv_text' in payload else (ROOT/'sample_data'/f'{dataset}.csv').read_bytes()))
    if len(raw)>MAX_BYTES: raise BusinessError('TOO_LARGE','文件超过2MB',413)
    context=deepcopy(snapshot['context']) if snapshot is not None else json.loads((ROOT/'sample_data/context.json').read_text())
    context.update(deepcopy(payload.get('overrides',{})))
    # 重跑沿用批次固化的承运人；新建批次取请求声明的承运人（缺省为演示承运人）
    carrier=normalize_carrier(snapshot['carrier'] if snapshot is not None else payload.get('carrier_id',DEFAULT_CARRIER))
    start=time.perf_counter()
    state={'raw_bytes':raw,'context':context,'records':[],'quarantine':[], 'counts':{},'views':{},'source':dataset}
    for index,key in enumerate(MODULES,1):
        if index>until: break
        import_module(f'app.modules.{key}.rules').apply(state)
    state['input_snapshot']={'bytes_b64':base64.b64encode(raw).decode(),'context':deepcopy(context),'carrier':carrier}
    state.pop('raw_bytes',None)
    state['manifest']=make_manifest(digest(raw,context,carrier),dataset,time.perf_counter()-start,carrier)
    return state
