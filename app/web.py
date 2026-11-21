from fastapi import Request
from fastapi.templating import Jinja2Templates
from app.config import ROOT, META
from app.engine import evaluate
from app.identity import carrier_from_request, CARRIER_PARAM
from app import store

templates=Jinja2Templates(directory=str(ROOT/'app/templates'))

def render(request:Request,key):
    from app.main import DB_PATH
    carrier=carrier_from_request(request)
    run_id=request.query_params.get('run_id')
    if run_id:
        state=store.get(DB_PATH,run_id,carrier)
    else:
        state=store.save(DB_PATH,evaluate({'dataset':request.query_params.get('dataset','dirty'),'carrier_id':carrier}))
    return templates.TemplateResponse(request=request,name=f'{key}.html',context={'meta':META,'key':key,'state':state,'view':state['views'][key],'carrier':carrier,'carrier_param':CARRIER_PARAM})
