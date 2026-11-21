from contextlib import asynccontextmanager
from importlib import import_module
from fastapi import FastAPI, Request, Body
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from app.config import ROOT, META, MODULES, DB_PATH
from app.errors import BusinessError
from app.identity import carrier_from_request
from app.engine import evaluate
from app import store
from app.archive import serialize

@asynccontextmanager
async def lifespan(app):
    store.save(DB_PATH,evaluate())
    yield
app=FastAPI(title=META['title'],lifespan=lifespan)
app.mount('/static',StaticFiles(directory=str(ROOT/'app/static')),name='static')
@app.exception_handler(BusinessError)
async def business_error(request:Request,error:BusinessError):
    return JSONResponse({'code':error.code,'detail':error.message},status_code=error.status)
@app.get('/')
def home():
    return RedirectResponse('/'+MODULES[0],status=303)
@app.get('/healthz')
def health():
    return {'status':'ok','project':META['short']}
@app.post('/api/runs')
def create(request:Request,payload:dict=Body(default={})):
    carrier=carrier_from_request(request)
    payload={**payload,'carrier_id':carrier}
    return store.save(DB_PATH,evaluate(payload))
@app.post('/api/runs/{run_id}/rerun')
def rerun(run_id:str,request:Request):
    carrier=carrier_from_request(request)
    previous=store.get(DB_PATH,run_id,carrier)
    if 'input_snapshot' not in previous:
        raise BusinessError('INPUT_SNAPSHOT_MISSING','旧批缺少源快照，请重新导入')
    return store.save(DB_PATH,evaluate({'dataset':previous['source']},snapshot=previous['input_snapshot']))
@app.get('/api/runs')
def runs(request:Request):
    return store.history(DB_PATH,carrier_from_request(request))
@app.get('/api/runs/{run_id}')
def run(run_id:str,request:Request):
    return store.get(DB_PATH,run_id,carrier_from_request(request))
@app.post('/api/runs/{run_id}/review')
def review(run_id:str,request:Request,payload:dict=Body(...)):
    revision=payload.get('revision')
    if not isinstance(revision,int) or revision<1: raise BusinessError('BAD_REVISION','版本号须为正整数')
    return store.review(DB_PATH,run_id,revision,carrier_from_request(request))
@app.get('/api/export/{run_id}')
def export(run_id:str,request:Request):
    result=store.get(DB_PATH,run_id,carrier_from_request(request))
    return Response(serialize(result),media_type='application/zip',headers={'Content-Disposition':f'attachment; filename="{run_id}.zip"'})
for key in MODULES:
    app.include_router(import_module(f'app.modules.{key}.handler').router)
