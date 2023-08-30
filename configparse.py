import os
from typing import Optional, Dict
from pydantic import BaseModel, field_validator
from pydantic_settings import BaseSettings

app_path = os.path.realpath(os.path.dirname(__file__))


# noinspection PyMethodParameters
class WebServer(BaseModel):
    base_path: Optional[str] = ""
    use_forwarded: Optional[bool] = False
    forwarded_for_depth: Optional[int] = 1

    @field_validator('base_path')
    def base_path_validate(cls, path):
        if path.endswith('/'):
            return path.rstrip('/')
        return path


# noinspection PyMethodParameters
class FileServer(BaseModel):
    theme: Optional[str] = os.path.join(app_path, 'themes', 'default')
    show_dot_files: Optional[bool] = False
    use_interactive_breadcrumb: Optional[bool] = True
    enable_header_files: Optional[bool] = True
    enable_header_scripts: Optional[bool] = False
    enable_dlbox: Optional[bool] = False
    enable_thumbnailer: Optional[bool] = False
    enable_page_thumbnail: Optional[bool] = False
    page_thumbnail_backend: Optional[str] = 'wkhtmltoimage'
    enable_image_thumbnail: Optional[bool] = False
    enable_video_remux: Optional[bool] = False
    enable_video_thumbnail: Optional[bool] = False
    thumbimage_cache_dir: Optional[str] = os.path.join(app_path, 'cache', 'thumbimage')
    wkhtmltoimage_cache_dir: Optional[str] = os.path.join(app_path, 'cache', 'wkhtmltoimage')

    @field_validator('theme')
    def theme_exists(cls, path):
        base_path = os.path.join(os.path.realpath(os.path.dirname(__file__)), 'themes', path)
        if not os.path.exists(base_path):
            raise ValueError(f'Path {base_path} does not exist')
        elif not os.path.exists(os.path.join(base_path, 'assets')):
            raise ValueError(f'Path {os.path.join(base_path, "assets")} does not exist')
        return base_path

    @field_validator('page_thumbnail_backend')
    def validate_page_thumbnail_backend(cls, backend):
        if backend in ['wkhtmltoimage', 'qtwebengine5']:
            return backend
        else:
            raise ValueError(f'Invalid backend for page thumbnail generation: {backend}\n'
                             'Available backends are: "wkhtmltoimage", "qtwebengine5"')


# noinspection PyMethodParameters
class Mountpoint(BaseModel):
    path: str
    type: Optional[str] = 'listing'

    @field_validator('path')
    def serve_path_exists(cls, path):
        if not os.path.exists(path):
            raise ValueError(f'Path {path} does not exist')
        return path

    # noinspection PyShadowingBuiltins
    @field_validator('type')
    def validate_type(cls, type):
        if type not in ['listing', 'static']:
            raise ValueError(f'Invalid mount type `{type}`. Use either `listing` or `static`.')
        return type


class Settings(BaseSettings):
    web_server: WebServer
    file_server: FileServer
    serve_paths: Dict[str, Mountpoint]
