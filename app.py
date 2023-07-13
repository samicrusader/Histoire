#!/usr/bin/env python3
# Config
import asyncio
import logging
import os
import yaml
from configparse import Settings

config_file = os.environ.get('HISTOIRE_CONFIG', './config.yaml')
config_file_message = 'Failed to open ' + config_file + '{message}'
if not os.path.exists(config_file):
    if 'HISTOIRE_CONFIG' in os.environ:
        logging.critical(config_file_message.format(message=' as the file does not exist.'))
    else:
        logging.critical(config_file_message.format(
            message=' as the file does not exist. Another config file can be specified with the HISTOIRE_CONFIG '
                    'environment variable.'))
    exit(1)
settings = None
try:
    settings = Settings.model_validate(yaml.safe_load(open(config_file)))
except yaml.YAMLError as e:
    logging.critical(config_file_message.format(message=': ' + str(e)), exc_info=True)
    exit(1)

import aiofiles
import aiopath
import asyncio
import base64
import concurrent.futures
import functools
import jinja2
import json
import math
import mimetypes
import urllib.parse
from datetime import datetime
from hypercorn.config import Config
from hypercorn.asyncio import serve as hyperserve
from quart import Quart, abort, send_from_directory, render_template, redirect, request, make_response
from typing import Union

if settings.file_server.enable_image_thumbnail or settings.file_server.enable_video_thumbnail:
    from io import BytesIO
    from PIL import Image, ImageOps
if settings.file_server.enable_header_files:
    import commonmark
    import markupsafe

    if settings.file_server.enable_header_scripts:
        from importlib.machinery import SourceFileLoader
if settings.file_server.enable_page_thumbnail:
    import imgkit
if settings.file_server.enable_video_thumbnail:
    import cv2

# Handle mimetypes
icon_db = json.load(open(os.path.join(
    os.path.dirname(os.path.realpath(__file__)), 'templates', 'listing', 'mimetypes.json')))
mimetypes.init()
mimetypes.add_type('text/json', '.json')
mimetypes.add_type('text/markdown', '.md')
mimetypes.add_type('text/plain', '.inf')
mimetypes.add_type('text/plain', '.ini')
mimetypes.add_type('text/plain', '.conf')
mimetypes.add_type('video/mp4', '.mov')
mimetypes.add_type('video/webm', '.mkv')
mimetypes.add_type('video/mp2t', '.ts')  # while this is mpeg2-ts it's also typescript, but who is indexing typescript
mimetypes.add_type('video/mp2t', '.m2ts')


# Quart
class PrefixMiddleware(object):  # https://stackoverflow.com/a/36033627
    def __init__(self, asgi_app, prefix=''):
        self.app = asgi_app
        self.prefix = prefix

    async def __call__(self, scope, receive, send):
        if scope['path'].startswith(self.prefix):
            scope['path'] = scope['path'][len(self.prefix):]
            scope['raw_path'] = scope['path'][len(self.prefix.encode()):]
            return await self.app(scope, receive, send)
        else:
            resp = b'404 Not Found\r\n'
            await send({
                'type': 'http.response.start',
                'status': 404,
                'headers': [(b'content-length', str(len(resp)).encode()), (b'content-type', b'text/plain')],
            })
            await send({
                'type': 'http.response.body',
                'body': resp,
                'more_body': False,
            })


app = Quart(__name__, instance_relative_config=False)
app.asgi_app = PrefixMiddleware(app.asgi_app, prefix=settings.file_server.base_path)
app.jinja_options = {'loader': jinja2.FileSystemLoader([
    settings.file_server.theme,
    os.path.join(os.path.dirname(os.path.realpath(__file__)), 'templates')
])}
app.jinja_env.globals.update(settings=settings, os=os, version='1.0')
app.url_map.strict_slashes = False


async def dir_walk(actual_path: str, full_path: Union[str, os.PathLike, aiopath.AsyncPath]):
    folders = list()
    files = list()
    async for _file in aiopath.scandir.scandir_async(full_path):
        if not settings.file_server.show_dot_files:
            if _file.name.startswith('.') or _file.name.startswith('_h5ai'):
                continue
        try:
            stat = await _file.stat()  # Query the file stats before doing any parsing as broken symlinks will kill it.
        except FileNotFoundError:
            continue
        file = dict()
        file['name'] = _file.name
        file['is_file'] = await _file.is_file()
        file['path'] = urllib.parse.quote(str(await aiopath.AsyncPath('/').joinpath(settings.file_server.base_path)
                                              .joinpath(str(actual_path).lstrip('/')).joinpath(_file.name).resolve()))
        file['modified_at_raw'] = stat.st_mtime
        if os.name != 'nt':
            file['modified_at'] = datetime.fromtimestamp(stat.st_mtime).strftime('%-m/%-d/%Y %-I:%M:%S %p')
        else:
            file['modified_at'] = datetime.fromtimestamp(stat.st_mtime).strftime('%m/%d/%Y %I:%M:%S %p')
        if int(stat.st_size) == 0:
            file['size'] = '-'
        else:
            dec = int(math.floor(math.log(int(stat.st_size), 1024)))
            i = ('B', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB', 'YB')[dec]
            s = round(int(stat.st_size) / math.pow(1024, dec), 2)
            file['size'] = '%s %s' % (s, i)
        if file['is_file']:
            f = aiopath.AsyncPath(full_path).joinpath(_file.name)
            file['extension'] = f.suffix.lstrip('.')
            mimetype = mimetypes.guess_type(str(f))
            if not mimetype[0]:
                file['icon'] = 'bin'
                file['mimetype'] = 'application/octet-stream'
            else:
                file['mimetype'] = mimetype[0]

            if file['extension'].lower() in icon_db:
                file['icon'] = file['extension'].lower()
            else:
                match file['mimetype'].split('/')[0]:
                    case 'application':
                        file['icon'] = 'bin'
                    case 'text':
                        file['icon'] = 'txt'
                    case 'video':
                        file['icon'] = 'mp4'
                    case 'image':
                        file['icon'] = 'png'
                    case 'audio':
                        file['icon'] = '3ga'
                    case 'message':
                        file['icon'] = 'txt'
                    case 'font':
                        file['icon'] = 'otf'
                    case _:
                        file['icon'] = 'bin'
            files.append(file)
        else:
            file['extension'] = ''
            file['icon'] = 'folder'
            file['path'] += '/'
            file['mimetype'] = 'text/directory'
            folders.append(file)
    return sorted(folders, key=lambda _i: _i['name'].lower()) + sorted(files, key=lambda _i: _i['name'].lower())


async def verify_path(path: str):
    # _ is root mount
    if path == '/':
        if '_' not in settings.serve_paths.keys():  # If the root mount doesn't exist, and we're hitting the root dir,
            return False, None, None, None  # indicate a failed pull (404's in `serve`),
        return True, '_', aiopath.AsyncPath(settings.serve_paths['_'].path), '/'  # otherwise return the root mount
    # If anyone knows a better way to do the following: mailto:hi@samicrusader.me
    # aiopath.AsyncPath is basically the same as pathlib.Path
    path = path.lstrip('/')
    path = path.replace('/..', '')  # This is THE hack, but it should serve to boot anyone even trying to fuck around.
    path = aiopath.AsyncPath(path)
    if path.parts[0] == settings.file_server.base_path.strip('/'):  # If the first bit of the URL matches the base path,
        mount = path.parts[1]  # make the mount name and parts seem like the base path was never there!
        parts = path.parts[1:]
    else:  # Otherwise,
        mount = path.parts[0]  # just leave the regular name and URL parts.
        parts = path.parts
    if mount not in settings.serve_paths.keys():
        if '_' in settings.serve_paths.keys():  # use root mount as root mount point
            mount = '_'
            mount_serve_path = aiopath.AsyncPath(settings.serve_paths['_'].path)
            mount_file_path = path
        else:
            return False, None, None, None
    else:
        mount_serve_path = aiopath.AsyncPath(settings.serve_paths[parts[0]].path)
        mount_file_path = str(aiopath.AsyncPath(*parts[1:]))
        if mount_file_path == '.':
            mount_file_path = ''
    base_path = await aiopath.AsyncPath(mount_serve_path).resolve()  # base serve path
    full_path = await aiopath.AsyncPath(base_path).joinpath(str(mount_file_path).lstrip('/')).resolve()  # file path
    check = bool(str(full_path).startswith(str(base_path)) or not await full_path.exists())
    if not check:  # check is if the file path starts with the base path and if the file actually exists
        return check, None, None, None
    actual_path = path
    return check, mount, full_path, actual_path  # this is basically to manage directories and prevent traversal via 404


async def generate_breadcrumb(path: aiopath.AsyncPath):
    html = '<ol class="breadcrumb">\n'
    html += '    <li>Index of</li>'
    base_path = ("/" if settings.file_server.base_path == "/" else settings.file_server.base_path + '/')
    if path != '/':
        html += f'    <li><a href="{base_path}">{base_path}</a></li>\n'
        paths = list(filter(None, path.parts))
        overall = base_path
        for _path in paths:
            overall += f'{_path}/'
            if _path == paths[-1]:  # check for last path
                html += f'    <li class="active">{_path}</li>\n'
            else:
                html += f'    <li><a href="{overall}">{_path}</a></li>\n'
    else:
        html += f'    <li class="active">{base_path}</li>\n'
    html += '</ol>'
    return html


def _render_script(path: aiopath.AsyncPath, file: str):
    py_obj = SourceFileLoader('render', os.path.join(path, file)).load_module()
    data = py_obj.render()
    return data


def _thumb_image(img: Image, tiny: bool = False):
    if tiny:
        img = ImageOps.fit(img, (32, 32), Image.LANCZOS)
    else:
        img.thumbnail((512, 512))
    with BytesIO() as bio:
        img.save(bio, format='JPEG')
        bio.seek(0)
        i = bio.read()
    return i


def _get_image_thumb(path: str, tiny: bool = False):
    img = Image.open(path).convert('RGB')
    return _thumb_image(img, tiny)


def _get_video_thumb(path: str, tiny: bool = False):
    vid = cv2.VideoCapture(path)
    vid.set(cv2.CAP_PROP_POS_FRAMES, (int(vid.get(cv2.CAP_PROP_FRAME_COUNT)) // 3) - 1)
    ret, frame = vid.read()
    if not ret:
        raise RuntimeError('failed to read video frame')
    img = Image.frombytes('RGB', (frame.shape[1], frame.shape[0]), cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    return _thumb_image(img, tiny)


@app.route('/_/static/<path:actual_path>')
async def serve_static(actual_path):
    resp = await make_response(
        await send_from_directory(aiopath.AsyncPath(__file__).parent.joinpath('static'), actual_path)
    )
    resp.headers['Cache-Control'] = 'max-age=604800, must-revalidate'  # static files can change between updates
    return resp


@app.route('/_/assets/<path:actual_path>')
async def serve_assets(actual_path):
    resp = await make_response(
        await send_from_directory(aiopath.AsyncPath(__file__).parent.joinpath(settings.file_server.theme)
                                  .joinpath('assets'), actual_path)
    )
    resp.headers['Cache-Control'] = 'max-age=604800'  # assets don't really change much
    if aiopath.AsyncPath(actual_path).suffix.lstrip('.') in ['css', 'js']:  # unless they're used for styling
        resp.headers['Cache-Control'] += ', must-revalidate'  # in which case you want that being fresh if "stale"
    return resp


@app.route('/_/thumbnailer')
async def thumbnailer():
    loop = asyncio.get_running_loop()
    # FIXME: page_thumbnail needs to somehow be shoehorned in here
    if not settings.file_server.enable_thumbnailer:
        await abort(404)
    thumbimage_cache_dir = aiopath.AsyncPath(settings.file_server.thumbimage_cache_dir)
    await thumbimage_cache_dir.mkdir(parents=True, exist_ok=True)

    scale = request.args.get('scale', False, type=lambda v: v.lower() == 'true')
    actual_path = request.args.get('path', None)
    if not actual_path:
        await abort(500)
    x, mount, full_path, actual_path = await verify_path(actual_path)
    if not x or not await full_path.exists() or await full_path.is_dir():
        await abort(404)
    file_type = mimetypes.guess_type(str(full_path))[0].split('/')[0]
    if file_type not in ['image', 'video']:
        await abort(404)

    fn = base64.urlsafe_b64encode(str(actual_path).encode()).decode().lstrip('==')
    if scale:
        fn += '_scale'
    fn = thumbimage_cache_dir.joinpath(fn)

    if await fn.exists():
        fh = await aiofiles.open(fn, 'rb')
        i = await fh.read()
        await fh.close()
    else:
        with concurrent.futures.ProcessPoolExecutor() as pool:
            if file_type == 'image':
                if not settings.file_server.enable_image_thumbnail:
                    await abort(404)
                func = _get_image_thumb
            elif file_type == 'video':
                if not settings.file_server.enable_video_thumbnail:
                    await abort(404)
                func = _get_video_thumb
            else:
                await abort(500)
            try:
                i = await loop.run_in_executor(pool, functools.partial(func, path=str(full_path), tiny=scale))
            except RuntimeError:
                abort(500)
        fh = await aiofiles.open(fn, 'wb')
        await fh.write(i)
        await fh.close()
    return await make_response(i, 200, {'Content-Type': 'image/jpeg'})


@app.route('/_/page_thumbnail')
async def page_thumbnail():
    await abort(404)
    if not settings.file_server.enable_page_thumbnail:
        await abort(404)
    if not os.path.exists(settings.file_server.thumbimage_cache_dir):
        os.makedirs(settings.file_server.thumbimage_cache_dir, exist_ok=True)
    elif not os.path.exists(settings.file_server.wkhtmltoimage_cache_dir):
        os.makedirs(settings.file_server.wkhtmltoimage_cache_dir, exist_ok=True)

    actual_path = request.args.get('path', None)
    if not actual_path:
        await abort(500)
    elif actual_path != '/' and not actual_path.endswith('/'):
        return redirect(os.path.join(settings.file_server.server_url, f'_/page_thumbnail?path={actual_path}/'), 302)
    x, full_path, actual_path = await verify_path(actual_path)
    if not x or not os.path.exists(full_path) or os.path.isfile(full_path) or \
            os.path.isfile(os.path.join(full_path, 'index.htm')) or \
            os.path.isfile(os.path.join(full_path, 'index.html')):
        await abort(404)

    fn = os.path.join(settings.file_server.thumbimage_cache_dir,
                      base64.urlsafe_b64encode(actual_path.encode()).decode())
    if os.path.exists(fn):
        fh = open(fn, 'rb')
        i = fh.read()
        fh.close()
    else:
        # wxhtmltoimage chokes on objects that fail to load
        url = os.path.join(settings.file_server.server_url + f'/{actual_path.strip("/")}/') + '?thumbs=false'
        try:
            i = imgkit.from_url(url, False, options={
                'cache-dir': settings.file_server.wkhtmltoimage_cache_dir, 'format': 'jpg', 'disable-javascript': '',
                'enable-local-file-access': '', 'height': 550, 'log-level': 'error', 'width': 980, 'quiet': '',
                'load-media-error-handling': 'ignore', 'load-error-handling': 'ignore'
            })
        except UnicodeDecodeError as err:  # https://github.com/jarrekk/imgkit/issues/82#issuecomment-1167242672
            i = err.args[1]
        fh = open(fn, 'wb')
        fh.write(i)
        fh.close()
    return await make_response(i, 200, {'Content-Type': 'image/jpeg'})


@app.route('/')
async def root_directory():
    _, mount, full_path, actual_path = await verify_path('/')
    return await serve_dir(full_path, actual_path)


@app.route('/<path:actual_path>')
async def serve(actual_path):
    x, mount, full_path, actual_path = await verify_path(actual_path)
    if not x or not await full_path.exists():
        await abort(404)
    elif await full_path.is_file():  # handle file
        if full_path.name == '.header.py' or full_path.name == '.footer.py' or request.path.endswith('/'):
            await abort(404)
        return await send_from_directory(full_path.parent, actual_path.name)
    elif await full_path.is_dir() and not request.path.endswith('/'):  # handle directory-without-a-trailing-slash
        return redirect('/' + str(actual_path) + '/', 302)
    else:  # serve the directory listing
        return await serve_dir(full_path, actual_path)


async def serve_dir(full_path, actual_path):
    if await aiopath.AsyncPath(full_path).joinpath('index.htm').is_file():
        return await send_from_directory(full_path, 'index.htm')
    elif await aiopath.AsyncPath(full_path).joinpath('index.html').is_file():
        return await send_from_directory(full_path, 'index.html')
    header_html = None
    footer_html = None
    if settings.file_server.enable_header_files:
        search_paths = ['.header', '.header.md', '.header.htm', '.header.html', '.header.txt', '_h5ai.header.html',
                        '.footer', '.footer.md', '.footer.htm', '.footer.html', '.header.txt', '_h5ai.footer.html']
        if settings.file_server.enable_header_scripts:
            search_paths.insert(6, '.header.py')
            search_paths.insert(-1, '.footer.py')
        for file in search_paths:
            if not await aiopath.AsyncPath(full_path).joinpath(file).is_file() \
                    or file.find('header') > -1 and header_html or file.find('footer') > -1 and footer_html:
                continue
            fh = await aiofiles.open(full_path.joinpath(file), 'r')
            data = await fh.read()
            if file.endswith('.html') or file.endswith('.htm') or file.startswith('_h5ai'):
                pass
            elif file.endswith('.md'):
                # Code without a language needs to be marked as having no language, so it stylizes properly.
                # CommonMark does this with the <pre> tag which PrismJS does not like.
                data = commonmark.commonmark(data).replace('<code>', '<code class="language-none">')
            elif file.endswith('.txt') or file == '.header' or file == '.footer':
                data = f'<p>{markupsafe.escape(data)}</p>'
            elif file.endswith('.py'):
                if settings.file_server.enable_header_scripts:
                    with concurrent.futures.ProcessPoolExecutor() as pool:
                        data = await asyncio.get_running_loop() \
                            .run_in_executor(pool, functools.partial(_render_script, path=full_path, file=file))
            if file.find('header') > -1:
                header_html = data.strip()
            elif file.find('footer') > -1:
                footer_html = data
    files = await dir_walk(actual_path, full_path)
    resp = await make_response(
        await render_template(
            'base.html',
            relative_path=(f'/{actual_path}' if actual_path != '/' else '/'),
            modified_time=datetime.utcfromtimestamp((await aiopath.AsyncPath(full_path).stat()).st_mtime)
            .strftime('%Y-%m-%dT%H:%M:%S+00:00'), files=files, page='listing',
            breadcrumb=(await generate_breadcrumb(actual_path)
                        if settings.file_server.use_interactive_breadcrumb else ''),
            header=header_html, footer=footer_html,
            enable_thumbnails=request.args.get('thumbs', True, type=lambda v: v.lower() == 'true')
        )
    )
    # Wed, 05 Jul 2023 06:43:12 GMT for /public
    resp.date = datetime.utcfromtimestamp((await aiopath.AsyncPath(full_path).stat()).st_mtime)
    return resp


if __name__ == '__main__':
    hypercorn_config = Config()
    hypercorn_config.access_log_format = "%(h)s %(r)s %(s)s %(b)s %(D)s"
    hypercorn_config.accesslog = "-"
    hypercorn_config.bind = ['127.0.0.1:5000']
    hypercorn_config.errorlog = hypercorn_config.accesslog
    hypercorn_config.include_date_header = False
    print(hypercorn_config.include_date_header)
    asyncio.run(hyperserve(app, hypercorn_config))
