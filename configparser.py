import os
import yurl
from typing import Optional
from pydantic import BaseModel, BaseSettings, validator

app_path = os.path.realpath(os.path.dirname(__file__))


class FileServer(BaseModel):
    serve_path: str
    base_path: Optional[str] = None
    theme: Optional[str] = os.path.join(app_path, 'themes', 'default')
    show_dot_files: Optional[bool] = False
    enable_page_thumbnail: Optional[bool] = False
    server_url: Optional[str] = 'http://127.0.0.1:5000'
    thumbimage_cache_dir: Optional[str] = os.path.join(app_path, 'cache', 'thumbimage')
    wkhtmltoimage_cache_dir: Optional[str] = os.path.join(app_path, 'cache', 'wkhtmltoimage')

    @validator('serve_path', allow_reuse=True)
    def serve_path_exists(cls, path):
        if not os.path.exists(path):
            raise ValueError(f'Path {path} does not exist')
        return path

    @validator('base_path')
    def base_path_validate(cls, path):
        if path.endswith('/'):
            return path.rstrip('/')

    @validator('theme')
    def theme_exists(cls, path):
        base_path = os.path.join(os.path.realpath(os.path.dirname(__file__)), 'themes', path)
        if not os.path.exists(base_path):
            raise ValueError(f'Path {base_path} does not exist')
        elif not os.path.exists(os.path.join(base_path, 'assets')):
            raise ValueError(f'Path {os.path.join(base_path, "assets")} does not exist')
        return base_path

    @validator('server_url')
    def server_url_validate(cls, url):
        if url.endswith('/'):
            url = url.rstrip('/')
        return str(yurl.URL(url) + yurl.URL(cls.base_path))


class Settings(BaseSettings):
    file_server: FileServer
