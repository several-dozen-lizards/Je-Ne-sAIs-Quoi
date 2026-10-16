"""Local, bounded MPFB accessory imports using the existing fitted-body compiler."""
import json
import hashlib
import os
import re
import stat
import subprocess
import sys
import threading
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from concurrent.futures import ThreadPoolExecutor
from core.body_packages import BodyPackageError
from core.body_candidates import CandidateStager, save_candidate_mapping

EXECUTOR=ThreadPoolExecutor(max_workers=1,thread_name_prefix='avatar-fit')
LOCK=threading.Lock()
CHANGED=threading.Condition(LOCK)

def recover_interrupted(root):
    for path in (Path(root)/'accessory_jobs').glob('*/job.json'):
        record=json.loads(path.read_text())
        if record.get('status') in {'queued','fitting'}:
            record.update(status='failed',error='Fitting was interrupted by a room restart. Upload the ZIP again to retry.')
            path.write_text(json.dumps(record),encoding='utf-8')

def unpack(archive, destination):
    """Accept a data-only asset bundle with contained, existing file references."""
    destination=Path(destination).resolve()
    allowed={'.mhclo','.mhmat','.obj','.png','.jpg','.jpeg','.json','.txt','.license','.mtl'}
    with zipfile.ZipFile(archive) as bundle:
        files=[entry for entry in bundle.infolist() if not entry.is_dir()]
        if len(files)>128 or sum(e.file_size for e in files)>128*1024*1024:
            raise BodyPackageError('Accessory bundle is too large')
        for entry in files:
            relative=PurePosixPath(entry.filename.replace('\\','/'))
            target=(destination/str(relative)).resolve()
            if relative.is_absolute() or '..' in relative.parts or ':' in str(relative) or not target.is_relative_to(destination):
                raise BodyPackageError('Accessory bundle contains an external path')
            if stat.S_ISLNK(entry.external_attr>>16) or target.suffix.lower() not in allowed:
                raise BodyPackageError('Accessory bundle must contain model, material and image data only')
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(bundle.read(entry))
    definitions=list(destination.rglob('*.mhclo'))
    if len(definitions)!=1: raise BodyPackageError('Include exactly one .mhclo asset with its OBJ, material and textures')
    definition=definitions[0]
    if not re.fullmatch('[a-zA-Z0-9_-]{1,64}',definition.stem):
        raise BodyPackageError('Use letters, numbers, underscores or hyphens in the accessory filename')
    for document in [*destination.rglob('*.mhclo'),*destination.rglob('*.mhmat'),*destination.rglob('*.obj'),*destination.rglob('*.mtl')]:
        for line in document.read_text(encoding='utf-8',errors='strict').splitlines():
            parts=line.strip().split(maxsplit=1)
            if len(parts)<2 or parts[0].startswith('#'): continue
            key,value=parts
            if key.lower()=='rig' or (key.lower()=='basemesh' and value!='hm08'):
                raise BodyPackageError('Accessory fitting requires the standard hm08 base without a custom rig')
            if key in {'obj_file','material','vertexboneweights_file','mtllib'} or key.lower().endswith('texture') or key.startswith('map_'):
                path=(document.parent/value).resolve()
                if not path.is_relative_to(destination) or not path.is_file():
                    raise BodyPackageError('Every accessory file reference must resolve inside its ZIP')
    return definition

def start(repo, root, candidates, archive, category, outfit='male_casualsuit01'):
    if category not in {'hair','clothes'}: raise BodyPackageError('Choose hair or clothes')
    from tools.build_avatar_wardrobe import BLENDER,SOURCE,HAIR,anatomy_assets
    blender=os.environ.get('JNAIQ_BLENDER',BLENDER)
    source=os.environ.get('JNAIQ_AVATAR_SOURCE_BLEND',SOURCE)
    if not Path(blender).is_file() or not Path(source).is_file():
        raise BodyPackageError('Local fitting needs Blender with MPFB and a source body. Configure JNAIQ_BLENDER and JNAIQ_AVATAR_SOURCE_BLEND.')
    repo=Path(repo).resolve()
    allowed_outfits={entry.get('asset') for entry in json.loads((repo/'room/avatar_starters.json').read_text())['starters']}
    allowed_outfits.update({'male_casualsuit01','female_elegantsuit01','male_elegantsuit01','mindfront_f_dress_01'})
    separate=re.fullmatch(r'separates:([2-6]):([2-6])',outfit)
    bottom_source=None
    if separate:
        if category!='hair':raise BodyPackageError('Separate outfits are supported for hair fitting')
        catalog=json.loads((repo/'room/avatar_starters.json').read_text())['starters']
        top,bottom=separate.groups()
        bottom_entry=next((e for e in catalog if e.get('asset')==f'male_casualsuit{int(bottom):02}'),None)
        if bottom_entry is None:raise BodyPackageError('Matching trousers are unavailable')
        bottom_source=Path(candidates)/bottom_entry['candidate_id']/'body.glb'
        compile_outfit=f'male_casualsuit{int(top):02}'
    else:
        if outfit not in allowed_outfits:raise BodyPackageError('Choose a catalog outfit before fitting hair')
        compile_outfit=outfit
    digest=hashlib.sha256(archive.read());archive.seek(0)
    digest.update((category+outfit+str(Path(source).stat().st_mtime_ns)).encode())
    for module in ['tools/convert_makehuman_jnaiq.py','tools/build_avatar_wardrobe.py','tools/optimize_avatar_textures.py','tools/add_avatar_contour_morphs.py','core/avatar_accessories.py','tools/mix_avatar_clothes.py']:
        digest.update((repo/module).read_bytes())
    if bottom_source:digest.update(str(bottom_source).encode())
    build_key=digest.hexdigest()
    for path in (Path(root)/'accessory_jobs').glob('*/job.json'):
        previous=json.loads(path.read_text())
        if previous.get('build_key')==build_key and previous.get('status') in {'queued','fitting','ready'}:
            if previous['status']!='ready' or (Path(candidates)/previous['candidate_id']).is_dir():return previous
    directory=Path(root)/'accessory_jobs'/uuid.uuid4().hex
    directory.mkdir(parents=True)
    definition=unpack(archive,directory/'source')
    if definition.stem in HAIR:
        raise BodyPackageError('Give a custom accessory a distinct filename')
    record={'job_id':directory.name,'status':'queued','category':category,'name':definition.stem,'outfit':outfit,'build_key':build_key}
    def save():
        with CHANGED:
            temporary=directory/'job.partial'
            temporary.write_text(json.dumps(record),encoding='utf-8')
            os.replace(temporary,directory/'job.json')
            CHANGED.notify_all()
    save()
    def work():
        try:
            record['status']='fitting';save()
            output=directory/'body.glb'
            assets=anatomy_assets()
            assets+=['clothes:'+compile_outfit] if category=='hair' else []
            assets+=[category+':'+str(definition)]
            command=[blender,'--background','--python-exit-code','1','--python',str(repo/'tools/convert_makehuman_jnaiq.py'),'--','--source',source,'--output',str(output),'--manifest',str(directory/'conversion.json')]
            for asset in assets: command+=['--asset',asset]
            with (directory/'build.log').open('w',encoding='utf-8') as log:
                subprocess.run(command,cwd=repo,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=900,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            from tools.optimize_avatar_textures import optimize
            optimize(output)
            from tools.add_avatar_contour_morphs import refine
            refine(output,output)
            if bottom_source:
                from tools.mix_avatar_clothes import combine
                combined=directory/'combined.glb';combine(output,bottom_source,combined);output=combined
            stage=CandidateStager(candidates,definition.stem+'.glb','starter_persona')
            with output.open('rb') as handle:
                while block:=handle.read(1024*1024): stage.write(block)
            stage.finalize()
            adapter=json.loads((Path(candidates)/'a5bbba7fd0df4fefaa8c9ecba8d0faea'/'adapter.json').read_text())
            save_candidate_mapping(candidates,stage.candidate_id,'starter_persona',{key:adapter[key] for key in ['roles','expressions','optical_origin']})
            from tools.compact_avatar_preview import compact
            compact(Path(candidates)/stage.candidate_id/'body.glb',Path(candidates)/stage.candidate_id/'preview-compact-v1.glb')
            record.update(status='ready',candidate_id=stage.candidate_id);save()
        except Exception as error:
            record.update(status='failed',error=str(error));save()
    EXECUTOR.submit(work)
    return record.copy()

def status(root,job,after=None):
    if not re.fullmatch('[a-f0-9]{32}',job): raise BodyPackageError('Invalid accessory job')
    path=Path(root)/'accessory_jobs'/job/'job.json'
    if not path.is_file(): raise BodyPackageError('Accessory job unavailable')
    with CHANGED:
        if after:
            CHANGED.wait_for(lambda:json.loads(path.read_text())['status']!=after,timeout=25)
        return json.loads(path.read_text())
