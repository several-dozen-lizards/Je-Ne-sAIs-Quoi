"""Public UI adapter for an optional household 3D runtime.

Only fixed, existing room APIs are used. Capability discovery is not a claim
that an optional renderer or asset package has passed release acceptance.
"""
from pathlib import Path
import hmac
import json
import re
import secrets
from urllib.parse import urlsplit, quote

import httpx
from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse
from shell.builders_portal import local_request


def room_origin(value):
    try:
        parsed=urlsplit(value or '')
    except (ValueError,TypeError):
        return None
    if (parsed.scheme!='http' or parsed.hostname not in {'127.0.0.1','localhost','::1'}
            or parsed.username or parsed.password or parsed.path not in {'','/'}
            or parsed.query or parsed.fragment):
        return None
    try:
        if not parsed.port: return None
    except ValueError:
        return None
    return value.rstrip('/')


def exchange(base, path, payload=None):
    with httpx.Client(timeout=4,trust_env=False,follow_redirects=False) as client:
        response=(client.get(base+path) if payload is None else client.post(base+path,json=payload))
        if response.status_code>=400:
            try: message=response.json().get('error')
            except (ValueError,AttributeError): message=None
            return response.status_code,{'error':str(message or 'The optional runtime could not complete this request.')}
        if 'application/json' not in response.headers.get('content-type',''):
            return response.status_code,{'html':'text/html' in response.headers.get('content-type','')}
        return response.status_code,response.json()


def status(base):
    result={'connected':False,'renderer':False,'avatars':False,'environments':False,
            'packages':[],'targets':[],'assignments':{},'destinations':[]}
    if not base: return result
    for feature,path in [('renderer','/3d/'),('avatars','/api/avatar-library'),
                         ('environments','/api/world-destinations')]:
        try: code,data=exchange(base,path)
        except (httpx.HTTPError,ValueError): continue
        if code!=200 or not isinstance(data,dict): continue
        if feature=='renderer':
            result['renderer']=data.get('html') is True
            if result['renderer']:result['viewer_url']=base+'/3d/'
        elif feature=='avatars' and isinstance(data.get('packages'),list) and isinstance(data.get('targets'),list):
            result['avatars']=True
            result['packages']=[{'id':p['package_id'],'name':str(p.get('name','Avatar'))}
                for p in data['packages'] if isinstance(p,dict) and re.fullmatch('[a-f0-9]{32}',str(p.get('package_id','')))]
            result['targets']=[{'id':str(t['id']),'name':str(t.get('name',t['id']))}
                for t in data['targets'] if isinstance(t,dict) and t.get('id')]
            assignments=data.get('assignments',{})
            if isinstance(assignments,dict):
                result['assignments']={k:{'package_id':v.get('package_id'),'revision':v.get('revision'),
                                           'can_restore':bool(v.get('history'))}
                    for k,v in assignments.items() if isinstance(v,dict)}
        elif feature=='environments' and isinstance(data.get('destinations'),list) and data.get('shared') is True:
            result['environments']=True
            result['destinations']=[{'id':d['id'],'name':str(d.get('name','Environment')),'revision':d.get('revision')}
                for d in data['destinations'] if isinstance(d,dict) and re.fullmatch('[a-f0-9]{32}',str(d.get('id','')))]
    result['connected']=any(result[key] for key in ('renderer','avatars','environments'))
    return result


def install(app,root,room_url=None):
    base=room_origin(room_url)
    token=secrets.token_urlsafe(32)
    def response(data,code=200):
        return JSONResponse(data,status_code=code,headers={'Cache-Control':'no-store'})
    def allowed(request,write=False):
        return local_request(request) and (not write or hmac.compare_digest(request.headers.get('x-jnaiq-3d-token',''),token))

    @app.get('/spaces',response_class=HTMLResponse)
    def page(request:Request):
        if not allowed(request):return response({'error':'Open Worlds from your local JNAIQ window.'},403)
        text=(Path(root)/'shell/spaces.html').read_text(encoding='utf-8')
        return HTMLResponse(text.replace('/*SESSION*/',json.dumps({'token':token})),headers={'Cache-Control':'no-store'})

    @app.get('/api/3d/status')
    def get_status(request:Request):
        if not allowed(request):return response({'error':'Local JNAIQ requests only.'},403)
        value=status(base)
        if value.get('viewer_url'):value['viewer_url']+='?member='+quote(local_member(),safe='')
        return response(value)

    def local_member():
        return str(getattr(app.state,'local_identity',{}).get('user_id') or 'user')

    @app.post('/api/3d/assignment')
    async def assignment(request:Request):
        if not allowed(request,True):return response({'error':'Reopen Worlds before changing an avatar.'},403)
        if not base:return response({'error':'The household room service is unavailable.'},503)
        try:
            data=await request.json()
            if not isinstance(data,dict):raise ValueError()
            member=data.get('member');package=data.get('package_id');revision=data.get('expected_revision')
            if not isinstance(member,str) or not 1<=len(member)<=128 or any(ord(c)<32 for c in member):raise ValueError()
            if package is not None and not re.fullmatch('[a-f0-9]{32}',str(package)):raise ValueError()
            if revision is not None and not re.fullmatch('[a-f0-9]{32}',str(revision)):raise ValueError()
            if not isinstance(data.get('restore',False),bool):raise ValueError()
            if package is None and not data.get('restore',False):raise ValueError()
            code,value=exchange(base,'/api/avatar-library/assignments/'+quote(member,safe=''),
                {'package_id':package,'expected_revision':revision,'restore':data.get('restore',False)})
            return response(value,code)
        except (ValueError,TypeError):return response({'error':'Choose a household member and a library avatar.'},422)
        except httpx.HTTPError:return response({'error':'The room service is unavailable. Refresh before trying again.'},503)

    @app.get('/api/3d/environment/{ident}')
    def environment(ident:str,request:Request,revision:str):
        if not allowed(request):return response({'error':'Local JNAIQ requests only.'},403)
        if not base:return response({'error':'The household room service is unavailable.'},503)
        if not re.fullmatch('[a-f0-9]{32}',ident) or not re.fullmatch('[a-f0-9]{32}',revision):
            return response({'error':'Refresh the environment library.'},422)
        try:
            code,value=exchange(base,'/api/world-destinations/'+ident+'?revision='+revision)
            if code!=200:return response(value,code)
            expected='/assets/island-workshop/visit.html?visit='+ident+'&revision='+revision
            if value.get('load_ready') is not True or value.get('load_url')!=expected:
                return response({'error':'This environment has no verified viewing route.'},409)
            return response({'url':base+expected+'&member='+quote(local_member(),safe='')})
        except (httpx.HTTPError,ValueError,AttributeError):
            return response({'error':'The environment could not be opened. Refresh and try again.'},503)
