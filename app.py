import logging
import math
import os
import pathlib
import urllib.parse
import yaml
from configparser import Settings
from datetime import datetime
from flask import Flask, abort, send_from_directory, render_template, redirect
from typing import Union

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

app = Flask(__name__, static_url_path='/_/assets', static_folder=os.path.join(settings.file_server.theme, 'assets'),
            root_path=settings.file_server.base_path, instance_relative_config=False)


def dir_walk(relative_path: str, full_path: Union[str, os.PathLike]):
    folders = list()
    files = list()
    for _file in os.scandir(full_path):
        if not settings.file_server.show_dot_files:
            if _file.name.startswith('.'):
                pass
        file = dict()
        file['name'] = _file.name
        file['is_file'] = _file.is_file()
        file['path'] = urllib.parse.quote(os.path.join('/', relative_path, _file.name))
        file['modified_at_raw'] = _file.stat().st_mtime
        file['modified_at'] = datetime.fromtimestamp(_file.stat().st_mtime).strftime('%-m/%-d/%Y %-I:%M:%S %p')
        if int(_file.stat().st_size) == 0:
            file['size'] = '0 B'
        else:
            dec = int(math.floor(math.log(int(_file.stat().st_size), 1024)))
            i = ('B', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB', 'YB')[dec]
            s = round(int(_file.stat().st_size) / math.pow(1024, dec), 2)
            file['size'] = '%s %s' % (s, i)
        if _file.is_file():
            file['extension'] = pathlib.Path(os.path.join(full_path, _file.name)).suffix.lstrip('.')
            files.append(file)
        else:
            file['extension'] = 'folder'
            file['path'] += '/'
            folders.append(file)
    return sorted(folders, key=lambda _i: _i['name'].lower()) + sorted(files, key=lambda _i: _i['name'].lower())


def verify_path(actual_path: str):
    if actual_path == '/':
        return True, '/', settings.file_server.serve_path, '/'
    base_path = os.path.abspath(settings.file_server.serve_path)
    full_path = os.path.abspath(os.path.join(base_path, actual_path))
    check = bool(full_path.startswith(base_path) or not os.path.exists(full_path))
    if not check:
        return False, None, None, None
    return check, base_path, full_path, f'/{actual_path}/'


@app.route('/')
def root_directory():
    return serve_dir('/')


@app.route('/<path:actual_path>/')
def serve_dir(actual_path):
    x, base_path, full_path, actual_path = verify_path(actual_path)
    if not x or not os.path.isdir(full_path):
        abort(404)
    if os.path.isfile(os.path.join(full_path, 'index.htm')):
        return send_from_directory(base_path, os.path.join(actual_path, 'index.htm'))
    elif os.path.isfile(os.path.join(full_path, 'index.html')):
        return send_from_directory(base_path, os.path.join(actual_path, 'index.html'))
    return render_template('base.html',
                           relative_path=actual_path, files=dir_walk(actual_path, full_path), page='listing')


@app.route('/<path:actual_path>')
def serve_file(actual_path):
    x, base_path, full_path, actual_path = verify_path(actual_path)
    if not x:
        abort(404)
    elif os.path.isdir(full_path):
        return redirect(actual_path, 302)
    return send_from_directory(base_path, actual_path)


if __name__ == '__main__':
    app.run()