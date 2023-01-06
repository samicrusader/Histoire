import os
from typing import Optional
from pydantic import BaseModel, BaseSettings, validator

app_path = os.path.realpath(os.path.dirname(__file__))


class FileServer(BaseModel):
    serve_path: str
    base_path: Optional[str] = None
    theme: Optional[str] = os.path.join(app_path, 'themes', 'default')
    show_dot_files: Optional[bool] = False

    @validator('serve_path', allow_reuse=True)
    def serve_path_exists(cls, path):
        if not os.path.exists(path):
            raise ValueError(f'Path {path} does not exist')
        return path

    @validator('theme')
    def theme_exists(cls, path):
        base_path = os.path.join(os.path.realpath(os.path.dirname(__file__)), 'themes', path)
        if not os.path.exists(base_path):
            raise ValueError(f'Path {base_path} does not exist')
        elif not os.path.exists(os.path.join(base_path, 'assets')):
            raise ValueError(f'Path {os.path.join(base_path, "assets")} does not exist')
        return base_path


class Settings(BaseSettings):
    file_server: FileServer
