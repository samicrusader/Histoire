# Config
import logging
import os
import yaml
from configparser import Settings

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
    settings = Settings.parse_obj(yaml.safe_load(open(config_file)))
except yaml.YAMLError as e:
    logging.critical(config_file_message.format(message=': ' + str(e)), exc_info=True)
    exit(1)

import base64
import jinja2
import json
import math
import mimetypes
import pathlib
import urllib.parse
from datetime import datetime
from flask import Flask, abort, send_from_directory, render_template, redirect, request, make_response, send_file
from typing import Union

if settings.file_server.enable_image_thumbnail or settings.file_server.enable_video_thumbnail:
    from io import BytesIO
    from PIL import Image, ImageOps
if settings.file_server.enable_header_files:
    import commonmark
    import markupsafe
if settings.file_server.enable_page_thumbnail:
    import imgkit
if settings.file_server.enable_video_remux:
    import av
if settings.file_server.enable_video_thumbnail:
    import cv2
    import random

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


# Flask
class PrefixMiddleware(object):  # https://stackoverflow.com/a/36033627
    def __init__(self, wsgi_app, prefix=''):
        self.app = wsgi_app
        self.prefix = prefix

    def __call__(self, environ, start_response):
        if environ['PATH_INFO'].startswith(self.prefix):
            environ['PATH_INFO'] = environ['PATH_INFO'][len(self.prefix):]
            environ['SCRIPT_NAME'] = self.prefix
            return self.app(environ, start_response)
        else:
            start_response('404', [('Content-Type', 'text/plain')])
            return ['404 Not Found'.encode()]


app = Flask(__name__, static_url_path='/_/assets', static_folder=os.path.join(settings.file_server.theme, 'assets'),
            instance_relative_config=False)
app.wsgi_app = PrefixMiddleware(app.wsgi_app, prefix=settings.file_server.base_path)
app.jinja_loader = jinja2.ChoiceLoader([
    app.jinja_loader,
    jinja2.FileSystemLoader([
        settings.file_server.theme,
        os.path.join(os.path.dirname(os.path.realpath(__file__)), 'templates'),
    ])
])
app.jinja_env.globals.update(settings=settings, os=os, version='1.0')


def dir_walk(relative_path: str, full_path: Union[str, os.PathLike]):
    folders = list()
    files = list()
    for _file in os.scandir(full_path):
        if not settings.file_server.show_dot_files:
            if _file.name.startswith('.') or _file.name.startswith('_h5ai'):
                continue
        try:
            stat = _file.stat()  # Query the file stats before doing any parsing as broken symlinks will kill it.
        except FileNotFoundError:
            continue
        file = dict()
        file['name'] = _file.name
        file['is_file'] = _file.is_file()
        file['path'] = urllib.parse.quote(os.path.join('/', settings.file_server.base_path, relative_path.lstrip('/'),
                                                       _file.name))
        file['modified_at_raw'] = stat.st_mtime
        file['modified_at'] = datetime.fromtimestamp(stat.st_mtime).strftime('%-m/%-d/%Y %-I:%M:%S %p')
        if int(stat.st_size) == 0:
            file['size'] = '0 B'
        else:
            dec = int(math.floor(math.log(int(stat.st_size), 1024)))
            i = ('B', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB', 'YB')[dec]
            s = round(int(stat.st_size) / math.pow(1024, dec), 2)
            file['size'] = '%s %s' % (s, i)
        if _file.is_file():
            file['extension'] = pathlib.Path(os.path.join(full_path, _file.name)).suffix.lstrip('.')
            mimetype = mimetypes.guess_type(os.path.join(full_path, _file.name))
            if not mimetype[0]:
                file['icon'] = 'bin'
                file['mimetype'] = 'application/octet-stream'
            else:
                file['mimetype'] = mimetype[0]

            if file['extension'].lower() in icon_db:
                file['icon'] = file['extension'].lower()
            else:
                match file['mimetype'].split('/')[0]:
                    case 'application': file['icon'] = 'bin'
                    case 'text': file['icon'] = 'txt'
                    case 'video': file['icon'] = 'mp4'
                    case 'image': file['icon'] = 'png'
                    case 'audio': file['icon'] = '3ga'
                    case 'message': file['icon'] = 'txt'
                    case 'font': file['icon'] = 'otf'
                    case _: file['icon'] = 'bin'
            files.append(file)
        else:
            file['extension'] = ''
            file['icon'] = 'folder'
            file['path'] += '/'
            file['mimetype'] = 'text/directory'
            folders.append(file)
    return sorted(folders, key=lambda _i: _i['name'].lower()) + sorted(files, key=lambda _i: _i['name'].lower())


def verify_path(path: str):
    if path == '/':
        return True, settings.file_server.serve_path, '/'
    else:
        path = path.lstrip('/')
    base_path = os.path.abspath(settings.file_server.serve_path)
    full_path = os.path.abspath(os.path.join(base_path, path.lstrip('/')))
    check = bool(full_path.startswith(base_path) or not os.path.exists(full_path))
    if not check:
        return False, None, None
    actual_path = (path+'/' if os.path.isdir(full_path) else path)
    return check, full_path, actual_path


def generate_breadcrumb(path: str):
    html = '<ol class="breadcrumb">\n'
    html += '    <li>Index of</li>'
    if path != '/':
        html += f'    <li><a href="{settings.file_server.base_path}/">/</a></li>\n'
        paths = list(filter(None, path.split('/')))
        overall = settings.file_server.base_path+'/'
        for _path in paths:
            overall += f'{_path}/'
            if _path == paths[-1]:  # check for last path
                html += f'    <li class="active">{_path}</li>\n'
            else:
                html += f'    <li><a href="{overall}">{_path}</a></li>\n'
    else:
        html += '    <li class="active">/</li>\n'
    html += '</ol>'
    return html


@app.route('/_/page_thumbnail')
def page_thumbnail():
    if not settings.file_server.enable_page_thumbnail:
        abort(404)
    if not os.path.exists(settings.file_server.thumbimage_cache_dir):
        os.makedirs(settings.file_server.thumbimage_cache_dir, exist_ok=True)
    elif not os.path.exists(settings.file_server.wkhtmltoimage_cache_dir):
        os.makedirs(settings.file_server.wkhtmltoimage_cache_dir, exist_ok=True)

    actual_path = request.args.get('path', None)
    if not actual_path:
        abort(500)
    elif actual_path != '/' and not actual_path.endswith('/'):
        return redirect(os.path.join(settings.file_server.server_url, f'_/page_thumbnail?path={actual_path}/'), 302)
    x, full_path, actual_path = verify_path(actual_path)
    if not x or not os.path.exists(full_path) or os.path.isfile(full_path) or \
            os.path.isfile(os.path.join(full_path, 'index.htm')) or \
            os.path.isfile(os.path.join(full_path, 'index.html')):
        abort(404)

    fn = os.path.join(settings.file_server.thumbimage_cache_dir,
                      base64.urlsafe_b64encode(actual_path.encode()).decode())
    if os.path.exists(fn):
        fh = open(fn, 'rb')
        i = fh.read()
        fh.close()
    else:
        # wxhtmltoimage chokes on objects that fail to load
        url = os.path.join(settings.file_server.server_url + f'/{actual_path.strip("/")}/')+'?thumbs=false'
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
    return make_response(i, 200, {'Content-Type': 'image/jpeg'})


@app.route('/_/video_thumbnail')
def video_thumbnail():
    if not settings.file_server.enable_video_thumbnail:
        abort(404)
    if not os.path.exists(settings.file_server.thumbimage_cache_dir):
        os.makedirs(settings.file_server.thumbimage_cache_dir, exist_ok=True)

    actual_path = request.args.get('path', None)
    scale = request.args.get('scale', False, type=lambda v: v.lower() == 'true')
    if not actual_path:
        abort(500)
    x, full_path, actual_path = verify_path(actual_path)
    if not x or not os.path.exists(full_path) or os.path.isdir(full_path) or \
            not mimetypes.guess_type(full_path)[0].split('/')[0] == 'video':
        abort(404)

    fn = os.path.join(settings.file_server.thumbimage_cache_dir,
                      base64.urlsafe_b64encode(actual_path.encode()).decode())
    if scale:
        fn += '_scale'

    if os.path.exists(fn):
        i = open(fn, 'rb').read()
    else:
        vid = cv2.VideoCapture(full_path)
        vid.set(cv2.CAP_PROP_POS_FRAMES, (int(vid.get(cv2.CAP_PROP_FRAME_COUNT)) // 3) - 1)
        ret, frame = vid.read()
        if not ret:
            abort(500)
        img = Image.frombytes('RGB', (frame.shape[1], frame.shape[0]), cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        if scale:
            img = ImageOps.fit(img, (32, 32), Image.ANTIALIAS)
        else:
            img.thumbnail((512, 512))
        with BytesIO() as bio:
            img.save(bio, format='JPEG')
            bio.seek(0)
            i = bio.read()
        fh = open(fn, 'wb')
        fh.write(i)
        fh.close()
    return make_response(i, 200, {'Content-Type': 'image/jpeg'})


@app.route('/_/image_thumbnail')
def image_thumbnail():
    if not settings.file_server.enable_image_thumbnail:
        abort(404)
    if not os.path.exists(settings.file_server.thumbimage_cache_dir):
        os.makedirs(settings.file_server.thumbimage_cache_dir, exist_ok=True)

    actual_path = request.args.get('path', None)
    scale = request.args.get('scale', False, type=lambda v: v.lower() == 'true')
    if not actual_path:
        abort(500)
    x, full_path, actual_path = verify_path(actual_path)
    if not x or not os.path.exists(full_path) or os.path.isdir(full_path) or \
            not mimetypes.guess_type(full_path)[0].split('/')[0] == 'image':
        abort(404)

    fn = os.path.join(settings.file_server.thumbimage_cache_dir,
                      base64.urlsafe_b64encode(actual_path.encode()).decode())
    if scale:
        fn += '_scale'

    if os.path.exists(fn):
        i = open(fn, 'rb').read()
    else:
        img = Image.open(full_path).convert('RGB')
        if scale:
            img = ImageOps.fit(img, (32, 32), Image.ANTIALIAS)
        else:
            img.thumbnail((512, 512))
        with BytesIO() as bio:
            img.save(bio, format='JPEG')
            bio.seek(0)
            i = bio.read()
        fh = open(fn, 'wb')
        fh.write(i)
        fh.close()
    return make_response(i, 200, {'Content-Type': 'image/jpeg'})


@app.route('/')
def root_directory():
    return serve_dir('/')


@app.route('/<path:actual_path>/')
def serve_dir(actual_path):
    x, full_path, actual_path = verify_path(actual_path)
    if not x or not os.path.isdir(full_path):
        abort(404)
    if os.path.isfile(os.path.join(full_path, 'index.htm')):
        return send_from_directory(full_path, 'index.htm')
    elif os.path.isfile(os.path.join(full_path, 'index.html')):
        return send_from_directory(full_path, 'index.html')
    header_html = None
    footer_html = None
    if settings.file_server.enable_header_files:
        for file in ['.header', '.header.md', '.header.htm', '.header.html', '.header.txt', '_h5ai.header.html',
                     '.footer', '.footer.md', '.footer.htm', '.footer.html', '.header.txt', '_h5ai.footer.html']:
            if not os.path.isfile(os.path.join(full_path, file))\
                    or file.find('header') > -1 and header_html or file.find('footer') > -1 and footer_html:
                continue
            data = open(os.path.join(full_path, file), 'r').read()
            if file.endswith('.html') or file.endswith('.htm') or file.startswith('_h5ai'):
                pass
            elif file.endswith('.md'):
                # Code without a language needs to be marked as having no language, so it stylizes properly.
                # CommonMark does this with the <pre> tag which PrismJS does not like.
                data = commonmark.commonmark(data).replace('<code>', '<code class="language-none">')
            elif file.endswith('.txt') or file == '.header' or file == '.footer':
                data = f'<p>{markupsafe.escape(data)}</p>'
            if file.find('header') > -1:
                header_html = data.strip()
            elif file.find('footer') > -1:
                footer_html = data
    return render_template('base.html',
                           relative_path=(f'/{actual_path}' if actual_path != '/' else '/'),
                           modified_time=datetime.fromtimestamp(os.stat(full_path).st_mtime)
                           .strftime('%Y-%m-%dT%H:%M:%S+00:00'),
                           files=dir_walk(actual_path, full_path), page='listing',
                           breadcrumb=(generate_breadcrumb(actual_path)
                                       if settings.file_server.use_interactive_breadcrumb else ''), header=header_html,
                           footer=footer_html,
                           enable_thumbnails=request.args.get('thumbs', True, type=lambda v: v.lower() == 'true'))


@app.route('/<path:actual_path>')
def serve_file(actual_path):
    x, full_path, actual_path = verify_path(actual_path)
    if not x:
        abort(404)
    elif os.path.isdir(full_path):
        return redirect(actual_path, 302)

    return send_from_directory(settings.file_server.serve_path, actual_path)


if __name__ == '__main__':
    app.run()
