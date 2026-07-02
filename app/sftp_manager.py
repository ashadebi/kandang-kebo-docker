from pathlib import Path

from .config import settings
from .docker_manager import recreate_compose_service


def users_file() -> Path:
    path = settings.data_dir / "sftp" / "users.conf"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(placeholder_user(), encoding="utf-8")
    return path


def placeholder_user() -> str:
    # atmoz/sftp exits if users.conf is empty, so keep a disabled-looking placeholder
    # until the first real site user is created.
    return "panel-placeholder:disabled:82:82:upload\n"


def render_users_conf() -> None:
    # Site users now get isolated SFTP containers and unique host ports from
    # their generated compose files. Keep the legacy global service inert.
    users_file().write_text(placeholder_user(), encoding="utf-8")
    recreate_compose_service(settings.project_root, "sftp")
