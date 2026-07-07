import io
import os
import re
import shlex
import secrets
import string
import subprocess
import tarfile
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from shutil import copyfileobj, rmtree

import yaml
from jinja2 import Environment, FileSystemLoader

from . import docker_manager
from .config import settings
from .database import execute, query_all, query_one
from .sftp_manager import render_users_conf


USERNAME_RE = re.compile(r"^[a-z][a-z0-9_-]{2,31}$")
DOMAIN_RE = re.compile(r"^[a-z0-9.-]+\.[a-z]{2,}$")
IMAGE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,255}$")
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


def validate_custom_image(custom_image: str = "") -> str:
    image = custom_image.strip()
    if image and not IMAGE_REF_RE.match(image):
        raise ValueError("Custom image tidak valid. Gunakan format seperti registry/user/image:tag.")
    return image


def validate_options(
    php_version: str,
    php_ini_preset: str,
    resource_preset: str,
    cms_app: str = "none",
    custom_image: str = "",
) -> None:
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
    validate_custom_image(custom_image)


def apply_runtime_options(site: dict) -> dict:
    php_version = site.get("php_version") or "8.3"
    php_ini_preset = site.get("php_ini_preset") or "standard"
    resource_preset = site.get("resource_preset") or "medium"
    cms_app = site.get("cms_app") or "none"
    custom_image = validate_custom_image(site.get("custom_image") or "")
    validate_options(php_version, php_ini_preset, resource_preset, cms_app, custom_image)
    site.update(PHP_PRESETS[php_ini_preset])
    site["php_image"] = custom_image or CMS_IMAGES.get(cms_app, {}).get(php_version, PHP_IMAGES[php_version])
    if cms_app == "drupal" and not custom_image:
        site["nginx_document_root"] = "/var/www/html/web"
        site["php_mount_target"] = "/var/www/drupal"
        site["php_document_root"] = "/var/www/drupal/web"
    else:
        site["nginx_document_root"] = "/var/www/html"
        site["php_mount_target"] = "/var/www/html"
        site["php_document_root"] = "/var/www/html"
    site["resources"] = RESOURCE_PRESETS[resource_preset]
    site["cms_label"] = CMS_OPTIONS[cms_app]["label"]
    site["custom_image"] = custom_image
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
CUSTOM_CERT_CONTAINER_DIR = "/custom-certs"
GOACCESS_BIN = Path("/usr/bin/goaccess")


def custom_cert_host_dir(username: str) -> Path:
    return settings.project_root / "data" / "custom-certs" / username


def custom_cert_container_path(username: str, filename: str) -> str:
    return f"{CUSTOM_CERT_CONTAINER_DIR}/{username}/{filename}"


def traefik_dir() -> Path:
    """Path to traefik/dynamic in the project root.

    Both dashboard container (RW) and Traefik container (RO via docker-compose volume mount)
    access this dir. Uses $HOST_PROJECT_ROOT when running inside container so writes
    land in the bind-mounted project root, falling back to file-relative path when
    running on host for tests/CI.
    """
    env_root = os.environ.get("HOST_PROJECT_ROOT")
    if env_root:
        out = Path(env_root) / "traefik" / "dynamic"
    else:
        project_root = Path(__file__).resolve().parent.parent
        out = project_root / "traefik" / "dynamic"
    out.mkdir(parents=True, exist_ok=True)
    return out


def custom_cert_dynamic_path() -> Path:
    return settings.project_root / "traefik" / "dynamic" / "custom-certs.yml"


def has_custom_certificate(username: str) -> bool:
    cert_dir = custom_cert_host_dir(username)
    return (cert_dir / "fullchain.pem").is_file() and (cert_dir / "privkey.pem").is_file()


def render_custom_certificates() -> None:
    lines = [
        "# Generated by Docker Hosting Panel. Do not edit manually.",
        "tls:",
        "  certificates:",
    ]
    count = 0
    for row in query_all("SELECT username FROM sites ORDER BY username"):
        username = row["username"]
        if not has_custom_certificate(username):
            continue
        lines.extend(
            [
                f"    - certFile: {custom_cert_container_path(username, 'fullchain.pem')}",
                f"      keyFile: {custom_cert_container_path(username, 'privkey.pem')}",
                "      stores:",
                "        - default",
            ]
        )
        count += 1

    if count == 0:
        lines = ["# Generated by Docker Hosting Panel.", "# No custom TLS certificates uploaded."]

    dynamic_file = custom_cert_dynamic_path()
    dynamic_file.parent.mkdir(parents=True, exist_ok=True)
    dynamic_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


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
        "goaccess",
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


def recreate_nginx_only(site: dict) -> None:
    """Re-render compose + recreate nginx container only (so new Traefik labels load)."""
    render_site_files(site)
    docker_manager.recreate_compose_service(home_path(site["username"]) / "compose", "nginx")


def render_traefik_waf() -> None:
    """Generate /traefik/dynamic/site-wafs.yml with one Coraza middleware per WAF-enabled site.

    Each enabled site gets a chain of middlewares referenced via labels on the site router:
        ratelimit-{username}@file (if rate_limit > 0) -> waf-{username}@file
    """
    import yaml as _yaml
    out = traefik_dir() / "site-wafs.yml"
    sites = list_sites()

    middlewares = {}

    for site in sites:
        username = site["username"]
        waf_on = bool(site.get("waf_enabled"))
        if not waf_on:
            continue

        rate = int(site.get("waf_rate_limit_rps") or 0)
        sqli = bool(site.get("waf_sqli"))
        path_trav = bool(site.get("waf_path_traversal"))
        owasp = bool(site.get("waf_owasp_crs"))

        directives = [
            "SecRuleEngine On",
            "SecRequestBodyAccess On",
            "SecResponseBodyAccess On",
            "SecDebugLog /dev/stdout",
            "SecDebugLogLevel 3",
            'SecRule REQUEST_HEADERS:Content-Type "@rx text/xml" "id:9001,phase:1,log,pass,nolog,ctl:requestBodyProcessor=XML"',
        ]
        rid = 9100
        if sqli:
            rid += 1
            directives.append(
                'SecRule ARGS|ARGS_NAMES|REQUEST_URI|REQUEST_BODY "@rx (?i)(\\bor\\b\\s+\\d+|union\\s+select|sleep\\(|benchmark\\(|extractvalue\\(|load_file\\(|0x[0-9a-f]+)" '
                f'"id:{rid},phase:2,log,deny,status:403,msg:\"SQLi attempt blocked\""'
            )
        if path_trav:
            rid += 1
            directives.append(
                'SecRule ARGS|ARGS_NAMES|REQUEST_URI "@rx (\\.\\./|/etc/passwd|/etc/shadow|php://|file://|expect://|data:)" '
                f'"id:{rid},phase:2,log,deny,status:403,msg:\"Path traversal / LFI blocked\""'
            )
        if owasp:
            rid += 1
            directives.append(
                'SecRule REQUEST_HEADERS:User-Agent "@rx (?i)(nikto|sqlmap|nmap|masscan|acunetix|wfuzz|gobuster|dirsearch|hydra)" '
                f'"id:{rid},phase:1,log,deny,status:403,msg:\"Scanner blocked (OWASP)\"'
            )
            rid += 1
            directives.append(
                'SecRule ARGS|REQUEST_URI "@rx <\\s*/?\\s*(script|iframe|object|embed)" '
                f'"id:{rid},phase:2,log,deny,status:403,msg:\"XSS attempt blocked\""'
            )
            rid += 1
            directives.append(
                'SecRule REQUEST_METHOD "!@pm GET POST HEAD" '
                f'"id:{rid},phase:1,log,deny,status:405,msg:\"HTTP method not allowed\""'
            )

        middlewares[f"waf-{username}"] = {
            "plugin": {"coraza": {"directives": directives}}
        }

        if rate > 0:
            middlewares[f"ratelimit-{username}"] = {
                "rateLimit": {
                    "average": rate,
                    "burst": rate,  # burst == average, so any extra triggers limit immediately
                    "period": "1s",
                }
            }

    payload = {"http": {"middlewares": middlewares or {"waf-empty": {}}}}
    out.write_text("# Auto-generated per-site WAF middlewares (do not edit)\n", encoding="utf-8")
    with out.open("a", encoding="utf-8") as fh:
        _yaml.safe_dump(payload, fh, default_flow_style=False, sort_keys=False, allow_unicode=True)



def render_site_files(site: dict) -> None:
    env = Environment(loader=FileSystemLoader(settings.templates_dir / "php-nginx-mysql"), autoescape=False)
    site = apply_runtime_options(dict(site))
    site["custom_certificate"] = has_custom_certificate(site["username"])
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
    render_custom_certificates()


def goaccess_report_path(site: dict) -> Path:
    return home_path(site["username"]) / "goaccess" / "index.html"


def goaccess_status(site: dict) -> dict:
    report = goaccess_report_path(site)
    if not report.is_file():
        return {"ready": False, "updated_at": None}
    updated = datetime.fromtimestamp(report.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    return {"ready": True, "updated_at": updated}


def generate_goaccess_report(site: dict) -> str:
    log_file = home_path(site["username"]) / "logs" / "access.log"
    report_dir = home_path(site["username"]) / "goaccess"
    report_dir.mkdir(parents=True, exist_ok=True)
    if not log_file.is_file():
        return "GoAccess belum bisa dibuat karena access.log site belum ada."
    if not GOACCESS_BIN.is_file():
        return "GoAccess belum terpasang di container dashboard. Rebuild dashboard untuk mengaktifkan paket goaccess."

    report = goaccess_report_path(site)
    cmd = [
        str(GOACCESS_BIN),
        str(log_file),
        "--log-format=COMBINED",
        "--html-report-title",
        f"Traffic report - {site['domain']}",
        "--no-global-config",
        "--ignore-crawlers",
        "-o",
        str(report),
    ]
    result = subprocess.run(cmd, check=False, text=True, capture_output=True)
    if result.returncode != 0:
        return result.stdout + result.stderr
    docker_manager.recreate_compose_service(home_path(site["username"]) / "compose", "nginx")
    return f"GoAccess report selesai: https://{site['domain']}/goaccess/"


def awstats_status(site: dict) -> dict:
    return goaccess_status(site)


def generate_awstats_report(site: dict) -> str:
    return generate_goaccess_report(site)


def create_site(
    username: str,
    domain: str,
    php_version: str,
    db_engine: str,
    waf_enabled: bool = False,
    waf_rate_limit_rps: int = 0,
    waf_sqli: bool = False,
    waf_path_traversal: bool = False,
    waf_owasp_crs: bool = False,
    php_ini_preset: str = "standard",
    resource_preset: str = "medium",
    cms_app: str = "none",
    custom_image: str = "",
) -> dict:
    validate_site(username, domain)
    custom_image = validate_custom_image(custom_image)
    validate_options(php_version, php_ini_preset, resource_preset, cms_app, custom_image)
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
        "waf_rate_limit_rps": int(waf_rate_limit_rps or 0),
        "waf_sqli": bool(waf_sqli),
        "waf_path_traversal": bool(waf_path_traversal),
        "waf_owasp_crs": bool(waf_owasp_crs),
        "php_ini_preset": php_ini_preset,
        "resource_preset": resource_preset,
        "cms_app": cms_app,
        "custom_image": custom_image,
        "host_home": str(host_home_path(username)),
    }
    render_site_files(site)
    execute(
        """
        INSERT INTO sites (
            username, domain, php_version, db_engine, db_name, db_user, db_password,
            sftp_password, sftp_port, waf_enabled, waf_rate_limit_rps, waf_sqli, waf_path_traversal, waf_owasp_crs,
            php_ini_preset, resource_preset, cms_app, custom_image
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            int(waf_rate_limit_rps or 0),
            int(bool(waf_sqli)),
            int(bool(waf_path_traversal)),
            int(bool(waf_owasp_crs)),
            php_ini_preset,
            resource_preset,
            cms_app,
            custom_image,
        ),
    )
    render_users_conf()
    render_traefik_waf()
    return site


def update_site_options(
    site: dict,
    domain: str,
    php_version: str,
    db_engine: str,
    waf_enabled: bool = False,
    waf_rate_limit_rps: int = 0,
    waf_sqli: bool = False,
    waf_path_traversal: bool = False,
    waf_owasp_crs: bool = False,
    php_ini_preset: str = "standard",
    resource_preset: str = "medium",
    cms_app: str = "none",
    custom_image: str = "",
) -> dict:
    domain = domain.strip().lower()
    validate_site(site["username"], domain)
    custom_image = validate_custom_image(custom_image)
    validate_options(php_version, php_ini_preset, resource_preset, cms_app, custom_image)
    duplicate = query_one("SELECT id FROM sites WHERE domain = ? AND id != ?", (domain, site["id"]))
    if duplicate:
        raise ValueError("Domain sudah dipakai site lain.")

    updated = dict(site)
    updated.update(
        {
            "domain": domain,
            "php_version": php_version,
            "db_engine": db_engine,
            "waf_enabled": waf_enabled,
            "waf_rate_limit_rps": int(waf_rate_limit_rps or 0),
            "waf_sqli": bool(waf_sqli),
            "waf_path_traversal": bool(waf_path_traversal),
            "waf_owasp_crs": bool(waf_owasp_crs),
            "php_ini_preset": php_ini_preset,
            "resource_preset": resource_preset,
            "cms_app": cms_app,
            "custom_image": custom_image,
            "host_home": str(host_home_path(site["username"])),
        }
    )
    ensure_home(site["username"], cms_app)
    render_site_files(updated)
    execute(
        """
        UPDATE sites
        SET domain = ?, php_version = ?, db_engine = ?, waf_enabled = ?,
            waf_rate_limit_rps = ?, waf_sqli = ?, waf_path_traversal = ?, waf_owasp_crs = ?,
            php_ini_preset = ?, resource_preset = ?, cms_app = ?, custom_image = ?
        WHERE id = ?
        """,
        (
            domain,
            php_version,
            db_engine,
            int(waf_enabled),
            int(waf_rate_limit_rps or 0),
            int(bool(waf_sqli)),
            int(bool(waf_path_traversal)),
            int(bool(waf_owasp_crs)),
            php_ini_preset,
            resource_preset,
            cms_app,
            custom_image,
            site["id"],
        ),
    )
    render_traefik_waf()
    return updated


def delete_site(site: dict) -> str:
    output = docker_manager.remove_stack(compose_path(site["username"]))
    cert_dir = custom_cert_host_dir(site["username"])
    if cert_dir.exists():
        rmtree(cert_dir)
    home = home_path(site["username"])
    if home.exists():
        rmtree(home)
    execute("DELETE FROM sites WHERE id = ?", (site["id"],))
    render_users_conf()
    render_custom_certificates()
    return output


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
    site["custom_certificate"] = has_custom_certificate(site["username"])
    site["goaccess"] = goaccess_status(site)
    site["awstats"] = site["goaccess"]
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


def read_upload_text(upload_file, label: str) -> str:
    content = upload_file.read()
    if not content:
        raise ValueError(f"{label} kosong.")
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{label} harus berupa file PEM text.") from exc


def validate_certificate_pair(certificate_text: str, private_key_text: str) -> None:
    if "-----BEGIN CERTIFICATE-----" not in certificate_text or "-----END CERTIFICATE-----" not in certificate_text:
        raise ValueError("File sertifikat harus berformat PEM dan berisi blok CERTIFICATE.")
    if "-----BEGIN " not in private_key_text or "PRIVATE KEY-----" not in private_key_text:
        raise ValueError("File private key harus berformat PEM dan berisi blok PRIVATE KEY.")
    if "-----END " not in private_key_text or "PRIVATE KEY-----" not in private_key_text:
        raise ValueError("File private key tidak lengkap.")


def upload_custom_certificate(site: dict, certificate_file, private_key_file) -> str:
    certificate_text = read_upload_text(certificate_file, "File sertifikat")
    private_key_text = read_upload_text(private_key_file, "File private key")
    validate_certificate_pair(certificate_text, private_key_text)

    cert_dir = custom_cert_host_dir(site["username"])
    cert_dir.mkdir(parents=True, exist_ok=True)
    cert_file = cert_dir / "fullchain.pem"
    key_file = cert_dir / "privkey.pem"
    cert_file.write_text(certificate_text, encoding="utf-8")
    key_file.write_text(private_key_text, encoding="utf-8")
    cert_file.chmod(0o644)
    key_file.chmod(0o600)
    render_site_files(site)
    output = docker_manager.compose(compose_path(site["username"]), "up")
    return (
        "Sertifikat HTTPS custom berhasil disimpan dan diterapkan. "
        "Traefik akan memakai sertifikat ini untuk domain site.\n\n"
        f"{output}"
    )


def remove_custom_certificate(site: dict) -> str:
    cert_dir = custom_cert_host_dir(site["username"])
    for filename in ["fullchain.pem", "privkey.pem"]:
        with suppress(FileNotFoundError):
            (cert_dir / filename).unlink()
    render_site_files(site)
    output = docker_manager.compose(compose_path(site["username"]), "up")
    return f"Sertifikat HTTPS custom dihapus. Site kembali memakai Let's Encrypt otomatis.\n\n{output}"
