import io
import os
import re
import shlex
import secrets
import string
import subprocess
import tarfile
from contextlib import suppress
from pathlib import Path
from shutil import copyfileobj

from jinja2 import Environment, FileSystemLoader

from . import docker_manager
from .config import settings
from .database import execute, query_all, query_one
from .sftp_manager import render_users_conf


USERNAME_RE = re.compile(r"^[a-z][a-z0-9_-]{2,31}$")
DOMAIN_RE = re.compile(r"^[a-z0-9.-]+\.[a-z]{2,}$")
PHP_IMAGES = {
    "5.6": "php:5.6-fpm",
    "7.0": "php:7.0-fpm",
    "7.1": "php:7.1-fpm",
    "7.2": "php:7.2-fpm",
    "7.3": "php:7.3-fpm",
    "7.4": "php:7.4-fpm",
    "8.0": "php:8.0-fpm-alpine",
    "8.1": "php:8.1-fpm-alpine",
    "8.2": "php:8.2-fpm-alpine",
    "8.3": "php:8.3-fpm-alpine",
    "8.4": "php:8.4-fpm-alpine",
}
PHP_PRESETS = {
    "standard": {
        "upload_max_filesize": "64M",
        "post_max_size": "72M",
        "php_memory_limit": "256M",
        "max_execution_time": "120",
        "max_input_time": "120",
        "max_file_uploads": "20",
        "client_max_body_size": "72M",
    },
    "large_upload": {
        "upload_max_filesize": "256M",
        "post_max_size": "288M",
        "php_memory_limit": "512M",
        "max_execution_time": "300",
        "max_input_time": "300",
        "max_file_uploads": "50",
        "client_max_body_size": "288M",
    },
    "very_large_upload": {
        "upload_max_filesize": "1024M",
        "post_max_size": "1100M",
        "php_memory_limit": "1024M",
        "max_execution_time": "600",
        "max_input_time": "600",
        "max_file_uploads": "100",
        "client_max_body_size": "1100M",
    },
}
RESOURCE_PRESETS = {
    "small": {
        "nginx": {"cpus": "0.25", "memory": "128M"},
        "php": {"cpus": "0.50", "memory": "512M"},
        "db": {"cpus": "0.50", "memory": "512M"},
    },
    "medium": {
        "nginx": {"cpus": "0.50", "memory": "256M"},
        "php": {"cpus": "1.00", "memory": "1024M"},
        "db": {"cpus": "1.00", "memory": "1024M"},
    },
    "large": {
        "nginx": {"cpus": "1.00", "memory": "512M"},
        "php": {"cpus": "2.00", "memory": "2048M"},
        "db": {"cpus": "2.00", "memory": "2048M"},
    },
}
CMS_OPTIONS = {
    "none": {"label": "Blank PHP site"},
    "wordpress": {"label": "WordPress"},
    "joomla": {"label": "Joomla"},
    "drupal": {"label": "Drupal"},
}
CMS_IMAGES = {
    "wordpress": {
        "8.1": "wordpress:php8.1-fpm-alpine",
        "8.2": "wordpress:php8.2-fpm-alpine",
        "8.3": "wordpress:php8.3-fpm-alpine",
        "8.4": "wordpress:php8.4-fpm-alpine",
    },
    "joomla": {
        "8.1": "joomla:php8.1-fpm-alpine",
        "8.2": "joomla:php8.2-fpm-alpine",
        "8.3": "joomla:php8.3-fpm-alpine",
        "8.4": "joomla:php8.4-fpm-alpine",
    },
    "drupal": {
        "8.1": "drupal:php8.1-fpm-alpine",
        "8.2": "drupal:php8.2-fpm-alpine",
        "8.3": "drupal:php8.3-fpm-alpine",
        "8.4": "drupal:php8.4-fpm-alpine",
    },
}


def random_password(length: int = 24) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def validate_site(username: str, domain: str) -> None:
    if not USERNAME_RE.match(username):
        raise ValueError("Username harus diawali huruf, 3-32 karakter, hanya lowercase, angka, _, atau -.")
    if not DOMAIN_RE.match(domain):
        raise ValueError("Domain tidak valid.")


def validate_options(php_version: str, php_ini_preset: str, resource_preset: str, cms_app: str = "none") -> None:
    if php_version not in PHP_IMAGES:
        raise ValueError("Versi PHP tidak tersedia.")
    if php_ini_preset not in PHP_PRESETS:
        raise ValueError("Preset php.ini tidak tersedia.")
    if resource_preset not in RESOURCE_PRESETS:
        raise ValueError("Preset resource tidak tersedia.")
    if cms_app not in CMS_OPTIONS:
        raise ValueError("Pilihan CMS tidak tersedia.")
    if cms_app != "none" and php_version not in CMS_IMAGES[cms_app]:
        raise ValueError("CMS populer saat ini tersedia untuk PHP 8.1 sampai 8.4.")


def apply_runtime_options(site: dict) -> dict:
    php_version = site.get("php_version") or "8.3"
    php_ini_preset = site.get("php_ini_preset") or "standard"
    resource_preset = site.get("resource_preset") or "medium"
    cms_app = site.get("cms_app") or "none"
    validate_options(php_version, php_ini_preset, resource_preset, cms_app)
    site.update(PHP_PRESETS[php_ini_preset])
    site["php_image"] = CMS_IMAGES.get(cms_app, {}).get(php_version, PHP_IMAGES[php_version])
    site["resources"] = RESOURCE_PRESETS[resource_preset]
    site["cms_label"] = CMS_OPTIONS[cms_app]["label"]
    return site


def home_path(username: str) -> Path:
    return settings.container_home_root / username


def host_home_path(username: str) -> Path:
    return settings.host_home_root / username


def compose_path(username: str) -> Path:
    return home_path(username) / "compose" / "docker-compose.yml"


WEB_UID = 82
WEB_GID = 82
SFTP_PORT_START = 22000
SFTP_PORT_END = 22999


def ensure_tree_owner(path: Path, uid: int = WEB_UID, gid: int = WEB_GID) -> None:
    for item in [path, *path.rglob("*")]:
        with suppress(PermissionError, FileNotFoundError):
            os.chown(item, uid, gid)
        with suppress(PermissionError, FileNotFoundError):
            item.chmod(0o755 if item.is_dir() else 0o644)


def ensure_home(username: str, cms_app: str = "none") -> None:
    base = home_path(username)
    for child in [
        "public_html",
        "logs",
        "awstats",
        "backups/database",
        "backups/files",
        "tmp",
        "ssl",
        "config",
        "compose",
    ]:
        (base / child).mkdir(parents=True, exist_ok=True)

    index = base / "public_html" / "index.php"
    if cms_app == "none" and not index.exists():
        index.write_text(
            f"<?php\nphpinfo();\n",
            encoding="utf-8",
        )
    elif cms_app != "none" and index.exists() and index.read_text(encoding="utf-8").strip() == "<?php\nphpinfo();":
        index.unlink()

    ensure_tree_owner(base / "public_html")
    ensure_tree_owner(base / "tmp")


def render_site_files(site: dict) -> None:
    env = Environment(loader=FileSystemLoader(settings.templates_dir / "php-nginx-mysql"), autoescape=False)
    site = apply_runtime_options(dict(site))
    base = home_path(site["username"])

    nginx_conf = env.get_template("nginx.conf.j2").render(**site)
    php_ini = env.get_template("php.ini.j2").render(**site)
    (base / "config" / "nginx.conf").write_text(nginx_conf, encoding="utf-8")
    (base / "config" / "php.ini").write_text(php_ini, encoding="utf-8")

    output = env.get_template("docker-compose.yml.j2").render(
        **site,
        public_network=settings.public_network,
        project_root=str(settings.project_root),
    )
    compose_file = compose_path(site["username"])
    compose_file.parent.mkdir(parents=True, exist_ok=True)
    compose_file.write_text(output, encoding="utf-8")


def create_site(
    username: str,
    domain: str,
    php_version: str,
    db_engine: str,
    waf_enabled: bool = False,
    php_ini_preset: str = "standard",
    resource_preset: str = "medium",
    cms_app: str = "none",
) -> dict:
    validate_site(username, domain)
    validate_options(php_version, php_ini_preset, resource_preset, cms_app)
    if query_one("SELECT id FROM sites WHERE username = ? OR domain = ?", (username, domain)):
        raise ValueError("Username atau domain sudah ada.")

    db_name = f"{username}_db".replace("-", "_")
    db_user = f"{username}_user".replace("-", "_")
    db_password = random_password()
    sftp_password = random_password(18)
    sftp_port = allocate_sftp_port()

    ensure_home(username, cms_app)
    site = {
        "username": username,
        "domain": domain,
        "php_version": php_version,
        "db_engine": db_engine,
        "db_name": db_name,
        "db_user": db_user,
        "db_password": db_password,
        "sftp_password": sftp_password,
        "sftp_port": sftp_port,
        "waf_enabled": waf_enabled,
        "php_ini_preset": php_ini_preset,
        "resource_preset": resource_preset,
        "cms_app": cms_app,
        "host_home": str(host_home_path(username)),
    }
    render_site_files(site)
    execute(
        """
        INSERT INTO sites (
            username, domain, php_version, db_engine, db_name, db_user, db_password,
            sftp_password, sftp_port, waf_enabled, php_ini_preset, resource_preset, cms_app
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            username,
            domain,
            php_version,
            db_engine,
            db_name,
            db_user,
            db_password,
            sftp_password,
            sftp_port,
            int(waf_enabled),
            php_ini_preset,
            resource_preset,
            cms_app,
        ),
    )
    render_users_conf()
    return site


def allocate_sftp_port() -> int:
    used = {
        int(row["sftp_port"])
        for row in query_all("SELECT sftp_port FROM sites WHERE sftp_port > 0")
    }
    for port in range(SFTP_PORT_START, SFTP_PORT_END + 1):
        if port not in used:
            return port
    raise ValueError("Port SFTP site sudah penuh.")


def list_sites() -> list[dict]:
    sites = []
    for row in query_all("SELECT * FROM sites ORDER BY created_at DESC"):
        site = dict(row)
        site["containers"] = docker_manager.container_status(f"site-{site['username']}-")
        sites.append(site)
    return sites


def get_site(site_id: int) -> dict | None:
    row = query_one("SELECT * FROM sites WHERE id = ?", (site_id,))
    if not row:
        return None
    site = dict(row)
    site["host_home"] = str(host_home_path(site["username"]))
    if not site.get("sftp_port"):
        site["sftp_port"] = allocate_sftp_port()
        execute("UPDATE sites SET sftp_port = ? WHERE id = ?", (site["sftp_port"], site["id"]))
        render_site_files(site)
    site["home"] = str(host_home_path(site["username"]))
    site["compose"] = str(host_home_path(site["username"]) / "compose" / "docker-compose.yml")
    site["containers"] = docker_manager.container_status(f"site-{site['username']}-")
    return site


def site_action(site: dict, action: str) -> str:
    if action in {"up", "restart"}:
        ensure_home(site["username"], site.get("cms_app") or "none")
        render_site_files(site)
    output = docker_manager.compose(compose_path(site["username"]), action)
    status = {"up": "running", "down": "stopped", "restart": "running"}.get(action)
    if status:
        execute("UPDATE sites SET status = ? WHERE id = ?", (status, site["id"]))
    return output


def backup_database(site: dict) -> str:
    backup_dir = home_path(site["username"]) / "backups" / "database"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_file = backup_dir / f"{site['db_name']}.sql"
    service = f"site-{site['username']}-db"
    cmd = [
        "docker",
        "exec",
        service,
        "sh",
        "-c",
        f"mariadb-dump -u{site['db_user']} -p{site['db_password']} {site['db_name']}",
    ]
    with backup_file.open("w", encoding="utf-8") as fh:
        result = subprocess.run(cmd, stdout=fh, stderr=subprocess.PIPE, text=True, check=False)
    if result.returncode != 0:
        return result.stderr
    return f"Backup database dibuat: {backup_file}"


def safe_sql_filename(filename: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(filename).name).strip(".-")
    return safe or "backup.sql"


def restore_database(site: dict, upload_file, filename: str) -> str:
    backup_dir = home_path(site["username"]) / "backups" / "database"
    backup_dir.mkdir(parents=True, exist_ok=True)
    restore_file = backup_dir / f"restore-{safe_sql_filename(filename)}"
    with restore_file.open("wb") as fh:
        copyfileobj(upload_file, fh)

    service = f"site-{site['username']}-db"
    container = docker_manager.client().containers.get(service)
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as tar:
        tar.add(restore_file, arcname="restore.sql")
    archive.seek(0)
    container.put_archive("/tmp", archive.getvalue())

    cmd = (
        f"mariadb -u{shlex.quote(site['db_user'])} "
        f"-p{shlex.quote(site['db_password'])} "
        f"{shlex.quote(site['db_name'])} < /tmp/restore.sql; "
        "status=$?; rm -f /tmp/restore.sql; exit $status"
    )
    result = container.exec_run(["sh", "-c", cmd])
    if result.exit_code != 0:
        return result.output.decode("utf-8", errors="replace") or "Restore database gagal."
    return f"Restore database selesai dari file: {restore_file}"
