#!/usr/bin/env python3
# Config
import aiofiles
import aiopath
import argparse
import asyncio
import base64
import concurrent.futures
import functools
import jinja2
import json
import logging
import math
import mimetypes
import os
import pathlib
import pydantic
import string
import traceback
import urllib.parse
import uvicorn.middleware.proxy_headers
import yaml
from anyio import Path
from datetime import datetime
from hypercorn.config import Config
from hypercorn.asyncio import serve as _serve
from natsort import humansorted as natsorted
from quart import Quart, abort, send_from_directory, render_template, redirect, request, make_response
from quart.utils import run_sync
from typing import Union
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
except pydantic.ValidationError as e:
    print(f'\033[91m{e}\033[00m')
    logging.critical(config_file_message.format(message=f': \033[91m{e}\033[00m'), exc_info=True)
    exit(1)

if settings.file_server.enable_image_thumbnail or settings.file_server.enable_video_thumbnail:
    from io import BytesIO
    from PIL import Image, ImageOps
if settings.file_server.enable_header_files:
    import commonmark
    import markupsafe

    if settings.file_server.enable_header_scripts:
        from importlib.machinery import SourceFileLoader
if settings.file_server.enable_video_thumbnail:
    # noinspection PyUnresolvedReferences
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
class ASGIMiddleware(object):
    def __init__(self, asgi_app):
        self.app = asgi_app

    async def __call__(self, scope, receive, send):
        # Prefixes: https://stackoverflow.com/a/36033627
        if scope['path'].startswith(settings.web_server.base_path):
            scope['path'] = scope['path'][len(settings.web_server.base_path):]
            scope['raw_path'] = scope['path'][len(settings.web_server.base_path.encode()):]
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
            return
        if settings.web_server.use_forwarded:
            return await uvicorn.middleware.proxy_headers.ProxyHeadersMiddleware(self.app)(scope, receive, send)
        else:
            return await self.app(scope, receive, send)


app = Quart(__name__, instance_relative_config=False)
app.asgi_app = ASGIMiddleware(app.asgi_app)
app.jinja_options = {'loader': jinja2.FileSystemLoader([
    settings.file_server.theme,
    os.path.join(os.path.dirname(os.path.realpath(__file__)), 'templates')
])}
app.jinja_env.globals.update(settings=settings, os=os, version='1.0')
app.jinja_env.lstrip_blocks = True
app.jinja_env.trim_blocks = True
app.url_map.strict_slashes = False


# noinspection PyUnresolvedReferences
async def dir_walk(actual_path: str, full_path: Union[str, os.PathLike, Path]):
    # *_symbolstart is to get around natsort ignoring starting symbols when sorting
    # FIXME: This hack should be removed when this behavior can be corrected
    folders_symbolstart = list()
    folders = list()
    files_symbolstart = list()
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
        file['path'] = urllib.parse.quote(str(await Path('/').joinpath(settings.web_server.base_path)
                                              .joinpath(str(actual_path).lstrip('/')).joinpath(_file.name).resolve()))
        file['path_without_base'] = urllib.parse.quote(str(await Path('/').joinpath(str(actual_path).lstrip('/'))
                                                           .joinpath(_file.name).resolve()))
        file['modified_at_raw'] = stat.st_mtime
        if os.name != 'nt':
            file['modified_at'] = datetime.fromtimestamp(stat.st_mtime).strftime('%-m/%-d/%Y %-I:%M:%S %p')
        else:
            file['modified_at'] = datetime.fromtimestamp(stat.st_mtime).strftime('%m/%d/%Y %I:%M:%S %p')
        if not file['is_file']:
            file['size'] = -1
            file['pretty_size'] = '-'
        elif int(stat.st_size) == 0:
            file['size'] = 0
            file['pretty_size'] = '0 B'
        else:
            file['size'] = int(stat.st_size)
            dec = int(math.floor(math.log(int(stat.st_size), 1024)))
            i = ('B', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB', 'YB')[dec]
            s = round(int(stat.st_size) / math.pow(1024, dec), 2)
            file['pretty_size'] = '%s %s' % (s, i)
        if file['is_file']:
            f = Path(full_path).joinpath(_file.name)
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
            if file['name'][0] not in string.ascii_letters+string.digits:
                files_symbolstart.append(file)
            else:
                files.append(file)
        else:
            file['extension'] = ''
            file['icon'] = 'folder'
            file['path'] += '/'
            file['mimetype'] = 'text/directory'
            if file['name'][0] not in string.ascii_letters+string.digits:
                folders_symbolstart.append(file)
            else:
                folders.append(file)
    return natsorted(folders_symbolstart, key=lambda _i: _i['name'].lower()) + \
        natsorted(folders, key=lambda _i: _i['name'].lower()) + \
        natsorted(files_symbolstart, key=lambda _i: _i['name'].lower()) + \
        natsorted(files, key=lambda _i: _i['name'].lower())


async def verify_path(path: str):
    # _ is root mount
    if path == '/':
        if '_' not in settings.serve_paths.keys():  # If the root mount doesn't exist, and we're hitting the root dir,
            return False, None, None, None  # indicate a failed pull (404's in `serve`),
        return True, '_', Path(settings.serve_paths['_'].path), '/'  # otherwise return the root mount
    # If anyone knows a better way to do the following: mailto:hi@samicrusader.me
    # anyio.Path is basically the same as pathlib.Path
    path = path.lstrip('/')
    path = path.replace('/..', '')  # This is THE hack, but it should serve to boot anyone even trying to fuck around.
    path = Path(path)
    if path.parts[0] == settings.web_server.base_path.strip('/'):  # If the first bit of the URL matches the base path,
        mount = path.parts[1]  # make the mount name and parts seem like the base path was never there!
        parts = path.parts[1:]
    else:  # Otherwise,
        mount = path.parts[0]  # just leave the regular name and URL parts.
        parts = path.parts
    if mount not in settings.serve_paths.keys():
        if '_' in settings.serve_paths.keys():  # use root mount as root mount point
            mount = '_'
            mount_serve_path = Path(settings.serve_paths['_'].path)
            mount_file_path = path
        else:
            return False, None, None, None
    else:
        mount_serve_path = Path(settings.serve_paths[parts[0]].path)
        mount_file_path = str(Path(*parts[1:]))
        if mount_file_path == '.':
            mount_file_path = ''
    base_path = await Path(mount_serve_path).resolve()  # base serve path
    full_path = await Path(base_path).joinpath(str(mount_file_path).lstrip('/')).resolve()  # file path
    check = bool(str(full_path).startswith(str(base_path)) or not await full_path.exists())
    if not check:  # check is if the file path starts with the base path and if the file actually exists
        return check, None, None, None
    actual_path = path
    return check, mount, full_path, actual_path  # this is basically to manage directories and prevent traversal via 404


async def generate_breadcrumb(path: Path):
    html = '<ol class="breadcrumb">\n'
    html += '    <li>Index of</li>\n'
    base_path = ("/" if settings.web_server.base_path == "/" else settings.web_server.base_path + '/')
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


def _render_script(path: Path, file: str):
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


def _page_thumbnail(path: str, tiny: None = None):
    location, path = path.split('||', maxsplit=1)
    if settings.file_server.page_thumbnail_backend == 'qtwebengine5':
        from PySide2.QtCore import Qt, QTimer, QByteArray, QBuffer, QIODevice, QUrl
        from PySide2.QtGui import QPixmap
        from PySide2.QtWidgets import QApplication
        from PySide2.QtWebEngineWidgets import QWebEngineView, QWebEngineSettings

        class Render(QWebEngineView):
            def __init__(self, html):
                self.img = None
                self.app = QApplication(['', '--no-sandbox', '--allow-file-access-from-files',
                                         '--disable-web-security'])
                QWebEngineView.__init__(self)
                self.setAttribute(Qt.WA_DontShowOnScreen)
                self.settings().setAttribute(QWebEngineSettings.ShowScrollBars, False)
                self.loadFinished.connect(self._loadfinished)
                self.setHtml(html, QUrl.fromLocalFile('file://'+location))
                self.setGeometry(0, 0, 1000, 600)
                self.app.exec_()

            def _callable(self):
                size = self.contentsRect()
                pixmap = QPixmap(size.width(), size.height())
                self.page().view().render(pixmap)
                ba = QByteArray()
                buf = QBuffer(ba)
                buf.open(QIODevice.WriteOnly)
                pixmap.save(buf, "PNG")
                self.img = ba.data()
                buf.close()
                ba.clear()
                self.close()
                self.app.quit()

            def _loadfinished(self, result):
                self.show()
                # FIXME: Have this replaced with an event that checks when the DOM has fully loaded (including scripts)
                QTimer.singleShot(3000, lambda: self._callable())

        return Render(path).img
    elif settings.file_server.page_thumbnail_backend == 'wkhtmltoimage':
        import imgkit
        wxhtmltoimage_cache_dir = pathlib.Path(settings.file_server.wkhtmltoimage_cache_dir)
        wxhtmltoimage_cache_dir.mkdir(parents=True, exist_ok=True)
        # wkhtmltoimage chokes on objects that fail to load
        try:
            i = imgkit.from_string(path, False, options={
                'cache-dir': settings.file_server.wkhtmltoimage_cache_dir, 'format': 'jpg', 'disable-javascript': '',
                'enable-local-file-access': '', 'height': 600, 'log-level': 'info', 'width': 1000, 'quiet': '',
                'load-media-error-handling': 'ignore', 'load-error-handling': 'ignore'
            })
        except UnicodeDecodeError as err:  # https://github.com/jarrekk/imgkit/issues/82#issuecomment-1167242672
            i = err.args[1]
    else:
        return ValueError('Invalid page thumbnail generator backend')
    return i


@app.route('/_/static/<path:actual_path>')
async def serve_static(actual_path):
    resp = await make_response(
        await send_from_directory(Path(__file__).parent.joinpath('static'), actual_path)
    )
    resp.headers['Cache-Control'] = 'max-age=604800, must-revalidate'  # static files can change between updates
    return resp


@app.route('/_/assets/<path:actual_path>')
async def serve_assets(actual_path):
    resp = await make_response(
        await send_from_directory(Path(__file__).parent.joinpath(settings.file_server.theme)
                                  .joinpath('assets'), actual_path)
    )
    resp.headers['Cache-Control'] = 'max-age=604800'  # assets don't really change much
    if Path(actual_path).suffix.lstrip('.') in ['css', 'js']:  # unless they're used for styling
        resp.headers['Cache-Control'] += ', must-revalidate'  # in which case you want that being fresh if "stale"
    return resp


@app.route('/_/thumbnailer')
async def thumbnailer():
    loop = asyncio.get_running_loop()
    # FIXME: page_thumbnail needs to somehow be shoehorned in here
    if not settings.file_server.enable_thumbnailer:
        await abort(404)
    thumbimage_cache_dir = Path(settings.file_server.thumbimage_cache_dir)
    await thumbimage_cache_dir.mkdir(parents=True, exist_ok=True)

    scale = None
    actual_path = request.args.get('path', None)
    if not actual_path:
        await abort(500)
    x, mount, full_path, actual_path = await verify_path(actual_path)
    if not x or not await full_path.exists():
        await abort(404)
    elif await full_path.is_dir():
        file_type = 'page'
    else:
        file_type = mimetypes.guess_type(str(full_path))[0].split('/')[0]
        if file_type not in ['image', 'video']:
            await abort(404)
        else:
            scale = request.args.get('scale', False, type=lambda v: v.lower() == 'true')

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
            elif file_type == 'page':
                if not settings.file_server.enable_page_thumbnail or \
                        await Path(full_path).joinpath('index.htm').is_file() or \
                        await Path(full_path).joinpath('index.html').is_file():
                    await abort(404)
                elif not request.args.get('path', None).endswith('/'):  # handle directory-without-a-trailing-slash
                    return redirect('/_/thumbnailer?path=/' + str(actual_path) + '/', 302)
                page = await serve_dir(full_path, actual_path, thumbnail=True)
                page = await page.data
                func = _page_thumbnail
                full_path = str(full_path) + '||' + page.decode('utf8')  # Hack, but works.
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


@app.route('/')
async def root_directory():
    _, mount, full_path, actual_path = await verify_path('/')
    return await serve(actual_path)


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
        if await Path(full_path).joinpath('index.htm').is_file():
            return await send_from_directory(full_path, 'index.htm')
        elif await Path(full_path).joinpath('index.html').is_file():
            return await send_from_directory(full_path, 'index.html')
        elif settings.serve_paths[mount].type == 'listing':
            return await serve_dir(full_path, actual_path)
        else:
            await abort(404)


async def serve_dir(full_path, actual_path, thumbnail: bool = False):
    header_html = None
    footer_html = None
    has_markdown = False
    has_code_block = False

    if settings.file_server.enable_header_files:
        search_paths = ['.header', '.header.md', '.header.htm', '.header.html', '.header.txt', '_h5ai.header.html',
                        '.footer', '.footer.md', '.footer.htm', '.footer.html', '.header.txt', '_h5ai.footer.html']
        if settings.file_server.enable_header_scripts:
            search_paths.insert(6, '.header.py')
            search_paths.insert(-1, '.footer.py')
        for file in search_paths:
            if not await Path(full_path).joinpath(file).is_file() \
                    or file.find('header') > -1 and header_html or file.find('footer') > -1 and footer_html:
                continue
            if file.endswith('.py'):
                data = await run_sync(_render_script)(path=full_path, file=file)
            else:
                fh = await aiofiles.open(full_path.joinpath(file), 'r')
                data = await fh.read()
                if file.endswith('.html') or file.endswith('.htm') or file.startswith('_h5ai'):
                    pass
                elif file.endswith('.md'):
                    data = commonmark.commonmark(data)
                    # Code without a language needs to be marked as having no language, so it stylizes properly.
                    # CommonMark does this with the <pre> tag which PrismJS does not like.
                    data = data.replace('<code>', '<code class="language-none">')
                    # CommonMark's Python module also is very stupid regarding code blocks, ending on a newline
                    # regardless of whether there's a trailing newline in the code.
                    # This will probably get some false positive
                    data = data.replace('\n</code></pre>', '</code></pre>')
                    has_markdown = True
                elif file.endswith('.txt') or file == '.header' or file == '.footer':
                    data = f'<p>{markupsafe.escape(data)}</p>'
            if data.find('<code') > -1:
                has_code_block = True
            if file.find('header') > -1:
                header_html = data.strip()
            elif file.find('footer') > -1:
                footer_html = data
    files = await dir_walk(actual_path, full_path)
    resp = await make_response(
        await render_template(
            'base.html',
            relative_path=(f'/{actual_path}' if actual_path != '/' else '/'),
            relative_path_with_base=(f'{settings.web_server.base_path}/{actual_path}'
                                     if actual_path != '/' else f'{settings.web_server.base_path}/'),
            modified_time=datetime.utcfromtimestamp((await Path(full_path).stat()).st_mtime)
            .strftime('%Y-%m-%dT%H:%M:%S+00:00'), files=files, page='listing',
            breadcrumb=(await generate_breadcrumb(actual_path)
                        if settings.file_server.use_interactive_breadcrumb else ''),
            header=header_html, footer=footer_html,
            enable_thumbnails=request.args.get('thumbs', True, type=lambda v: v.lower() == 'true'), thumbnail=thumbnail,
            has_markdown=has_markdown, has_code_block=has_code_block, host_url=request.host_url.rstrip('/'),
            hostname=request.host
        )
    )
    # Wed, 05 Jul 2023 06:43:12 GMT for /public
    resp.date = datetime.utcfromtimestamp((await Path(full_path).stat()).st_mtime)
    return resp


if __name__ == '__main__':
    # ArgumentParser setup
    parser = argparse.ArgumentParser(
        description='Histoire',
        prog='python3 app.py'
    )
    parser.add_argument('--bind', '-b', default='127.0.0.1:5000', help='ip:port to listen on (default 127.0.0.1:5000)')
    args = parser.parse_args()
    hypercorn_config = Config()
    hypercorn_config.access_log_format = "%(h)s %(r)s %(s)s %(b)s %(D)s"
    hypercorn_config.accesslog = "-"
    hypercorn_config.bind = ['0.0.0.0:5000']
    hypercorn_config.errorlog = hypercorn_config.accesslog
    hypercorn_config.include_date_header = False
    try:
        asyncio.run(_serve(app, hypercorn_config))
    except Exception as e:
        traceback.print_exception(e)
        exit(1)
    else:
        exit(0)
