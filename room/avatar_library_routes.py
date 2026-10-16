"""Local designer publication and assignment HTTP surface."""
import os
import base64
import re
import struct
import json
import hashlib
from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, FileResponse
from core import avatar_library as library
from core.body_packages import BodyPackageError
from core.body_candidates import candidate_model_path

def install(app, repo, candidate_root, *, standalone=False):
    root = os.environ.get('JNAIQ_AVATAR_LIBRARY', os.path.join(repo, 'state', 'avatar_library'))
    app.state.avatar_library_root = root
    from core.avatar_accessories import recover_interrupted
    recover_interrupted(root)
    from core.avatar_piece_jobs import recover_interrupted as recover_piece_jobs
    recover_piece_jobs(root)
    router = APIRouter(prefix='/api/avatar-library')

    @router.post('/eye-finish')
    def eye_finish(values: dict):
        from core.body_recipes import normalize_appearance
        from core.avatar_fantasy_eyes import resolve_fantasy
        try:
            normalized=normalize_appearance(values)
            return {'eye_texture_data':resolve_fantasy(normalized)}
        except BodyPackageError as exc:
            return JSONResponse(status_code=422,content={'error':str(exc)})

    @router.post('/hair-finish/{candidate_id}')
    def hair_finish(candidate_id: str, values: dict):
        from core.body_recipes import normalize_appearance
        from core.avatar_hair_finish import resolve_hair
        try:
            path=candidate_model_path(candidate_root(), candidate_id, 'starter_persona')
            return resolve_hair(path,normalize_appearance(values))
        except BodyPackageError as exc:
            return JSONResponse(status_code=422,content={'error':str(exc)})

    @router.post('/clothing-finish/{candidate_id}')
    def clothing_finish(candidate_id: str, values: dict):
        from core.body_recipes import normalize_appearance
        from core.avatar_hair_finish import resolve_clothing
        try:
            path=candidate_model_path(candidate_root(),candidate_id,'starter_persona')
            return resolve_clothing(path,normalize_appearance(values))
        except BodyPackageError as exc:
            return JSONResponse(status_code=422,content={'error':str(exc)})

    def targets():
        if standalone:
            return []
        from core.avatar_identities import targets as list_targets
        return list_targets(repo,app.state.rooms.values())

    def members():
        return [target['id'] for target in targets()]

    @router.get('')
    def index():
        return dict(packages=library.list_packages(root), assignments=library.assignments(root),
                    members=members(),targets=targets())

    @router.get('/starters')
    def starters():
        return json.loads((Path(repo) / 'room/avatar_starters.json').read_text(encoding='utf-8'))

    @router.get('/wardrobe-pieces')
    def wardrobe_pieces():
        from core.avatar_piece_jobs import catalog
        return catalog(repo, public=True)

    @router.post('/wardrobe/{candidate_id}')
    def change_wardrobe(candidate_id: str, values: dict):
        from core.avatar_wardrobe import change
        try:
            return change(repo,root,candidate_root(),candidate_id,values.get('outfit_id'))
        except (BodyPackageError,ValueError,KeyError,StopIteration) as exc:
            return JSONResponse({'error':str(exc) or 'This model does not contain a compatible fitted outfit.'},status_code=422)

    @router.post('/wardrobe-pieces/{candidate_id}')
    def fit_wardrobe_pieces(candidate_id: str, values: dict):
        from core import avatar_piece_jobs
        try:
            return avatar_piece_jobs.start(repo,root,candidate_root(),candidate_id,values)
        except (BodyPackageError,ValueError,KeyError,StopIteration) as exc:
            return JSONResponse({'error':str(exc)},status_code=422)

    @router.get('/wardrobe-pieces/jobs/{job}')
    def wardrobe_piece_status(job: str, after: str = ''):
        from core import avatar_piece_jobs
        try:return avatar_piece_jobs.status(root,job,after)
        except BodyPackageError as exc:return JSONResponse({'error':str(exc)},status_code=404)

    @router.post('/accessories/{category}')
    async def accessory(category: str, request: Request, outfit: str = 'male_casualsuit01'):
        if standalone:
            return JSONResponse({'error': 'New accessory fitting requires the Blender/MPFB authoring installation. Included hairstyles and outfits are ready to edit.'}, status_code=409)
        from core import avatar_accessories
        from io import BytesIO
        import zipfile
        try:
            content=bytearray()
            async for block in request.stream():
                content.extend(block)
                if len(content)>64*1024*1024: raise BodyPackageError('Accessory ZIP exceeds 64 MB')
            return avatar_accessories.start(repo,root,candidate_root(),BytesIO(content),category,outfit)
        except (BodyPackageError,zipfile.BadZipFile,ValueError,UnicodeError) as exc:
            return JSONResponse({'error':str(exc)},status_code=400)

    @router.get('/accessories/jobs/{job}')
    def accessory_status(job: str, after: str = ''):
        from core import avatar_accessories
        try: return avatar_accessories.status(root,job,after)
        except BodyPackageError as exc: return JSONResponse({'error':str(exc)},status_code=404)

    @router.post('/packages')
    async def publish(request: Request):
        try:
            data = await request.json()
            return library.publish(root, candidate_root(), data.get('candidate_id'),
                                   data.get('name'), data.get('mapping_source'))
        except (BodyPackageError, ValueError, TypeError) as exc:
            return JSONResponse({'error': str(exc)}, status_code=400)

    @router.post('/textures')
    async def upload_texture(request: Request):
        try:
            data = bytearray()
            async for block in request.stream():
                data.extend(block)
                if len(data) > 16 * 1024 * 1024:
                    raise BodyPackageError('Texture exceeds 16 MB')
            if len(data) < 24 or data[:8] != b'\x89PNG\r\n\x1a\n':
                raise BodyPackageError('Expected a PNG texture')
            width, height = struct.unpack('>II', data[16:24])
            if min(width,height) < 1 or max(width,height) > 2048:
                raise BodyPackageError('Texture dimensions must be 1–2048 pixels')
            # Decode before accepting: a PNG signature alone is not image validation.
            from PIL import Image
            from io import BytesIO
            with Image.open(BytesIO(data)) as image:
                image.verify()
            digest = hashlib.sha256(data).hexdigest()
            path = Path(root) / 'textures' / (digest + '.png')
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists(): path.write_bytes(data)
            return {'texture_id':digest,'width':width,'height':height}
        except (BodyPackageError, ValueError, OSError) as exc:
            return JSONResponse({'error':str(exc)},status_code=400)

    @router.get('/textures/{texture_id}')
    def texture(texture_id: str):
        if not re.fullmatch('[a-f0-9]{64}',texture_id):
            return JSONResponse({'error':'Invalid texture identifier'},status_code=400)
        path=Path(root)/'textures'/(texture_id+'.png')
        if not path.is_file(): return JSONResponse({'error':'Texture unavailable'},status_code=404)
        return FileResponse(path,media_type='image/png',headers={'Cache-Control':'private, max-age=31536000, immutable'})

    def thumbnail_path(recipe, revision):
        if not all(re.fullmatch('[a-f0-9]{32}', value) for value in [recipe, revision]):
            raise BodyPackageError('Invalid design revision')
        return Path(root) / 'thumbnails' / recipe / (revision + '.png')

    @router.post('/thumbnails/{recipe}/{revision}')
    async def save_thumbnail(recipe: str, revision: str, request: Request):
        try:
            path = thumbnail_path(recipe, revision)
            data = await request.json()
            image = data.get('image', '')
            if not isinstance(image, str) or len(image) > 512000 or not image.startswith('data:image/png;base64,'):
                raise BodyPackageError('Expected a small PNG thumbnail')
            raw = base64.b64decode(image.split(',', 1)[1], validate=True)
            if len(raw) < 24 or raw[:8] != b'\x89PNG\r\n\x1a\n' or max(struct.unpack('>II', raw[16:24])) > 512:
                raise BodyPackageError('Invalid thumbnail dimensions')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            return {'saved': True}
        except (BodyPackageError, ValueError, TypeError) as exc:
            return JSONResponse({'error': str(exc)}, status_code=400)

    @router.get('/thumbnails/{recipe}/{revision}')
    def thumbnail(recipe: str, revision: str):
        try:
            path = thumbnail_path(recipe, revision)
            if not path.is_file(): return JSONResponse({'error': 'No thumbnail'}, status_code=404)
            return FileResponse(path, media_type='image/png')
        except BodyPackageError as exc:
            return JSONResponse({'error': str(exc)}, status_code=400)

    @router.get('/packages/{package_id}/model')
    def model(package_id: str):
        try:
            package = library.load_package(root, package_id)
            from core.asset_delivery import model_path, delivery_headers
            source = candidate_model_path(candidate_root(), package['candidate_id'], 'starter_persona')
            prepared = model_path(source)
            headers = delivery_headers(source, prepared)
            headers['Cache-Control'] = 'private, no-cache'
            return FileResponse(prepared, media_type='model/gltf-binary', headers=headers)
        except BodyPackageError as exc:
            return JSONResponse({'error': str(exc)}, status_code=404)

    @router.post('/assignments/{member}')
    async def assignment(member: str, request: Request):
        try:
            if member.casefold() not in {n.casefold() for n in members()}:
                raise BodyPackageError('Choose an existing persona or user')
            data = await request.json()
            record = library.assign(root, member, data.get('package_id'),
                                    data.get('expected_revision'), bool(data.get('restore')))
            # A renderer event carries the package change, never a chat or an
            # instruction about the resident's experience of their body.
            from core.avatar_identities import member_keys
            aliases=member_keys(repo)
            for room in app.state.rooms.values():
                for name in room.members:
                    if aliases.get(str(name).casefold(),str(name).casefold()) == member.casefold():
                        room.emit(str(name), 'avatar_changed', {'avatar_package': record.get('package_id')})
            return record
        except (BodyPackageError, ValueError, TypeError) as exc:
            return JSONResponse({'error': str(exc)}, status_code=409)

    app.include_router(router)
