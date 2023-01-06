import base64
import imgkit
import logging
import jinja2
import json
import math
import mimetypes
import os
import pathlib
import urllib.parse
import yaml
from configparser import Settings
from datetime import datetime
from flask import Flask, abort, send_from_directory, render_template, redirect, request, make_response
from typing import Union

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

# Config
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


# Flask
class PrefixMiddleware(object):  # https://stackoverflow.com/a/36033627
    def __init__(self, app, prefix=''):
        self.app = app
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
            if _file.name.startswith('.'):
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
            if file['extension'].lower() in icon_db:
                file['icon'] = file['extension'].lower()
            else:
                mimetype = mimetypes.guess_type(os.path.join(full_path, _file.name))
                if not mimetype[0]:
                    file['icon'] = 'bin'
                else:
                    match mimetype[0].split('/')[0]:
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
        print(overall)
    else:
        html += '    <li class="active">/</li>\n'
    html += '</ol>'
    return html


@app.route('/_/image_render')
def page_render():
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
        return redirect(os.path.join(settings.file_server.server_url, f'_/image_render?path={actual_path}/'), 302)
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
        url = os.path.join(settings.file_server.server_url + f'/{actual_path.strip("/")}/')
        try:
            i = imgkit.from_url(url, False, options={
                'cache-dir': settings.file_server.wkhtmltoimage_cache_dir, 'format': 'jpg', 'disable-javascript': '',
                'enable-local-file-access': '', 'height': 550, 'log-level': 'error', 'width': 980, 'quiet': ''
            })
        except UnicodeDecodeError as err:  # https://github.com/jarrekk/imgkit/issues/82#issuecomment-1167242672
            i = err.args[1]
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
    return render_template('base.html',
                           relative_path=(f'/{actual_path}' if actual_path != '/' else '/'),
                           modified_time=datetime.fromtimestamp(os.stat(full_path).st_mtime)
                           .strftime('%Y-%m-%dT%H:%M:%S+00:00'),
                           files=dir_walk(actual_path, full_path), page='listing',
                           breadcrumb=(generate_breadcrumb(actual_path)
                                       if settings.file_server.use_interactive_breadcrumb else ''))


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
