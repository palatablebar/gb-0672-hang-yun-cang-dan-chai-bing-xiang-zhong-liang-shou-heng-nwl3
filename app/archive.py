import io, json, zipfile
from app.errors import BusinessError

def serialize(result):
    if not result.get('manifest') or not result.get('views'):
        raise BusinessError('INCOMPLETE_RUN','批次尚未完成')
    carrier=result['manifest'].get('carrier')
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('manifest.json',json.dumps({**result['manifest'],'revision':result.get('revision',1),'status':result.get('status','待复核')},ensure_ascii=False,indent=2))
        evidence={'carrier_id':carrier,'evidence_owner':carrier,
                  'evidence_scope':'证据归属承运人 %s，跨承运人不可见、不可导出' % carrier,
                  'counts':result['counts'],'views':result['views'],'quarantine':result['quarantine']}
        if result.get('accession'):
            evidence['accession']=result['accession']
        archive.writestr('evidence.json',json.dumps(evidence,ensure_ascii=False,indent=2))
    return buffer.getvalue()
