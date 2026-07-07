from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exception_handlers import http_exception_handler as default_http_exception_handler
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware
from time import time
import os
import shutil
import subprocess

from .auth import require_admin, require_login, require_owner_or_admin, verify_credentials, verify_admin
from .config import settings
from .database import init_db, list_sites_for_user, query_all
from . import site_manager
from . import monitoring


def _read_meminfo() -> dict:
    info = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                parts = line.split(":", 1)
                if len(parts) == 2:
                    key = parts[0].strip()
                    val = parts[1].strip().split()[0]
                    info[key] = int(val)
    except Exception:
        pass
    return info


def _read_loadavg() -> tuple:
    try:
        with open("/proc/loadavg") as f:
            parts = f.read().split()
            return float(parts[0]), float(parts[1]), float(parts[2])
    except Exception:
        return (0.0, 0.0, 0.0)


def get_system_stats() -> dict:
    """CPU / RAM / Disk / container counts for dashboard stat cards."""
    cpu_count = os.cpu_count() or 1
    load1, load5, load15 = _read_loadavg()
    cpu_pct = min(100, round((load1 / cpu_count) * 100))

    mem = _read_meminfo()
    mem_total = mem.get("MemTotal", 1)
    mem_avail = mem.get("MemAvailable", mem.get("MemFree", 0))
    mem_used = mem_total - mem_avail
    mem_pct = round((mem_used / mem_total) * 100) if mem_total else 0

    disk_total, disk_used, disk_pct = 0, 0, 0
    try:
        u = shutil.disk_usage("/")
        disk_total = u.total // (1024 ** 3)
        disk_used = u.used // (1024 ** 3)
        disk_pct = round((u.used / u.total) * 100) if u.total else 0
    except Exception:
        pass

    container_up = 0
    container_total = 0
    try:
        out = subprocess.check_output(
            ["docker", "ps", "-q"], stderr=subprocess.DEVNULL, timeout=3
        ).decode().strip().split()
        container_up = len(out)
        out_all = subprocess.check_output(
            ["docker", "ps", "-aq"], stderr=subprocess.DEVNULL, timeout=3
        ).decode().strip().split()
        container_total = len(out_all)
    except Exception:
        pass

    return {
        "cpu": {"pct": cpu_pct, "load1": load1, "load5": load5, "load15": load15, "count": cpu_count},
        "memory": {"pct": mem_pct, "used_mb": mem_used // 1024, "total_mb": mem_total // 1024},
        "disk": {"pct": disk_pct, "used_gb": disk_used, "total_gb": disk_total},
        "containers": {"up": container_up, "total": container_total},
    }


app = FastAPI(title="Docker Hosting Panel")
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")





def _context(request: Request, extra: dict) -> dict:
    """Build template context with auto-injected session_user from session."""
    ctx = {"request": request, "session_user": request.session.get("user")}
    ctx.update(extra)
    return ctx


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        return templates.TemplateResponse("404.html", _context(request, {}), status_code=404)
    return await default_http_exception_handler(request, exc)


# --- Auth -----------------------------------------------------------------

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    error = "Sesi admin berakhir karena tidak ada aktivitas." if request.query_params.get("expired") else None
    return templates.TemplateResponse("login.html", _context(request, {"error": error}))


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    user = verify_credentials(username, password)
    if not user:
        return templates.TemplateResponse(
            "login.html", _context(request, {"error": "Login gagal."})
        )
    request.session["user"] = user
    request.session["last_activity"] = int(time())
    if user["role"] == "admin":
        return RedirectResponse("/", status_code=303)
    return RedirectResponse(f"/u/{user['username']}", status_code=303)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# --- Admin pages ----------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    user = require_login(request)
    if user["role"] != "admin":
        return RedirectResponse(f"/u/{user['username']}", status_code=303)
    sites = site_manager.list_sites()
    active_sites = sum(1 for s in sites if s["status"] == "running")
    user_count = len(query_all("SELECT id FROM users WHERE role = 'user'"))
    db_count = len(query_all("SELECT id FROM sites WHERE db_name IS NOT NULL AND db_name != ''"))
    return templates.TemplateResponse(
        "dashboard.html",
        _context(request, {
            "sites": sites,
            "active_sites": active_sites,
            "user_count": user_count,
            "db_count": db_count,
            "sys_stats": get_system_stats(),
            "current_user": user,
            "title": "Dashboard",
        }),
    )


# --- User pages -----------------------------------------------------------

@app.get("/u/{username}", response_class=HTMLResponse)
def user_dashboard(request: Request, username: str):
    user = require_login(request)
    if user["role"] != "admin" and user["username"] != username:
        raise HTTPException(status_code=403, detail="Anda hanya dapat mengakses panel Anda sendiri.")
    sites = list_sites_for_user(username)
    active_sites = sum(1 for s in sites if s["status"] == "running")
    db_count = len([s for s in sites if s["db_name"]])
    return templates.TemplateResponse(
        "user_dashboard.html",
        _context(request, {
            "sites": sites,
            "active_sites": active_sites,
            "db_count": db_count,
            "sys_stats": get_system_stats(),
            "current_user": user,
            "username": username,
            "title": f"Sites Saya - {username}",
        }),
    )


# --- Sites (admin-only for create / delete; admin OR owner for the rest) -

@app.get("/sites/new", response_class=HTMLResponse)
def new_site(request: Request):
    require_admin(request)
    return templates.TemplateResponse("site_form.html", _context(request, {"error": None, "site": None}))


@app.post("/sites")
def create_site(
    request: Request,
    username: str = Form(...),
    domain: str = Form(...),
    php_version: str = Form("8.3"),
    db_engine: str = Form("mariadb"),
    waf_enabled: bool = Form(False),
    php_ini_preset: str = Form("standard"),
    resource_preset: str = Form("medium"),
    cms_app: str = Form("none"),
    custom_image: str = Form(""),
):
    require_admin(request)
    try:
        site_manager.create_site(
            username.strip(),
            domain.strip().lower(),
            php_version,
            db_engine,
            waf_enabled,
            php_ini_preset,
            resource_preset,
            cms_app,
            custom_image,
        )
    except Exception as exc:
        site = {
            "username": username,
            "domain": domain,
            "php_version": php_version,
            "db_engine": db_engine,
            "waf_enabled": waf_enabled,
            "php_ini_preset": php_ini_preset,
            "resource_preset": resource_preset,
            "cms_app": cms_app,
            "custom_image": custom_image,
        }
        return templates.TemplateResponse("site_form.html", _context(request, {"error": str(exc), "site": site}))
    return RedirectResponse("/", status_code=303)


@app.get("/sites/{site_id}/edit", response_class=HTMLResponse)
def edit_site(request: Request, site_id: int):
    site = site_manager.get_site(site_id)
    if not site:
        raise HTTPException(status_code=404)
    require_owner_or_admin(request, site)
    return templates.TemplateResponse("site_form.html", _context(request, {"error": None, "site": site}))


@app.post("/sites/{site_id}/edit", response_class=HTMLResponse)
def update_site(
    request: Request,
    site_id: int,
    domain: str = Form(...),
    php_version: str = Form("8.3"),
    db_engine: str = Form("mariadb"),
    waf_enabled: bool = Form(False),
    php_ini_preset: str = Form("standard"),
    resource_preset: str = Form("medium"),
    cms_app: str = Form("none"),
    custom_image: str = Form(""),
):
    site = site_manager.get_site(site_id)
    if not site:
        raise HTTPException(status_code=404)
    require_owner_or_admin(request, site)
    try:
        site_manager.update_site_options(
            site,
            domain,
            php_version,
            db_engine,
            waf_enabled,
            php_ini_preset,
            resource_preset,
            cms_app,
            custom_image,
        )
    except Exception as exc:
        site.update(
            {
                "domain": domain,
                "php_version": php_version,
                "db_engine": db_engine,
                "waf_enabled": waf_enabled,
                "php_ini_preset": php_ini_preset,
                "resource_preset": resource_preset,
                "cms_app": cms_app,
                "custom_image": custom_image,
            }
        )
        return templates.TemplateResponse("site_form.html", _context(request, {"error": str(exc), "site": site}))
    return RedirectResponse(f"/sites/{site_id}", status_code=303)


@app.post("/sites/{site_id}/delete")
def delete_site(request: Request, site_id: int):
    require_admin(request)  # destructive — admin only
    site = site_manager.get_site(site_id)
    if not site:
        raise HTTPException(status_code=404)
    site_manager.delete_site(site)
    return RedirectResponse("/", status_code=303)


@app.get("/sites/{site_id}", response_class=HTMLResponse)
def site_detail(request: Request, site_id: int):
    site = site_manager.get_site(site_id)
    if not site:
        raise HTTPException(status_code=404)
    require_owner_or_admin(request, site)
    return templates.TemplateResponse(
        "site_detail.html",
        _context(request, {"site": site, "output": None, "current_user": request.session.get("user")}),
    )


@app.post("/sites/{site_id}/restore-db", response_class=HTMLResponse)
def restore_database(request: Request, site_id: int, backup_file: UploadFile = File(...)):
    site = site_manager.get_site(site_id)
    if not site:
        raise HTTPException(status_code=404)
    require_owner_or_admin(request, site)
    if not backup_file.filename.endswith(".sql"):
        output = "Upload ditolak. File restore harus berekstensi .sql."
    else:
        output = site_manager.restore_database(site, backup_file.file, backup_file.filename)
    site = site_manager.get_site(site_id)
    return templates.TemplateResponse(
        "site_detail.html",
        _context(request, {"site": site, "output": output, "current_user": request.session.get("user")}),
    )


@app.post("/sites/{site_id}/goaccess/update", response_class=HTMLResponse)
def update_goaccess(request: Request, site_id: int):
    site = site_manager.get_site(site_id)
    if not site:
        raise HTTPException(status_code=404)
    require_owner_or_admin(request, site)
    output = site_manager.generate_goaccess_report(site)
    site = site_manager.get_site(site_id)
    return templates.TemplateResponse(
        "site_detail.html",
        _context(request, {"site": site, "output": output, "current_user": request.session.get("user")}),
    )


@app.post("/sites/{site_id}/awstats/update", response_class=HTMLResponse)
def update_awstats(request: Request, site_id: int):
    return update_goaccess(request, site_id)


@app.post("/sites/{site_id}/upload-certificate", response_class=HTMLResponse)
def upload_certificate(
    request: Request,
    site_id: int,
    certificate_file: UploadFile = File(...),
    private_key_file: UploadFile = File(...),
):
    site = site_manager.get_site(site_id)
    if not site:
        raise HTTPException(status_code=404)
    require_owner_or_admin(request, site)
    try:
        output = site_manager.upload_custom_certificate(site, certificate_file.file, private_key_file.file)
    except Exception as exc:
        output = f"Upload sertifikat gagal: {exc}"
    site = site_manager.get_site(site_id)
    return templates.TemplateResponse(
        "site_detail.html",
        _context(request, {"site": site, "output": output, "current_user": request.session.get("user")}),
    )


@app.post("/sites/{site_id}/remove-certificate", response_class=HTMLResponse)
def remove_certificate(request: Request, site_id: int):
    site = site_manager.get_site(site_id)
    if not site:
        raise HTTPException(status_code=404)
    require_owner_or_admin(request, site)
    output = site_manager.remove_custom_certificate(site)
    site = site_manager.get_site(site_id)
    return templates.TemplateResponse(
        "site_detail.html",
        _context(request, {"site": site, "output": output, "current_user": request.session.get("user")}),
    )


@app.post("/sites/{site_id}/{action}", response_class=HTMLResponse)
def site_action(request: Request, site_id: int, action: str):
    site = site_manager.get_site(site_id)
    if not site:
        raise HTTPException(status_code=404)
    require_owner_or_admin(request, site)
    if action == "delete":
        require_admin(request)
    if action == "backup-db":
        output = site_manager.backup_database(site)
    else:
        output = site_manager.site_action(site, action)
    site = site_manager.get_site(site_id)
    return templates.TemplateResponse(
        "site_detail.html",
        _context(request, {"site": site, "output": output, "current_user": request.session.get("user")}),
    )


@app.get("/security", response_class=HTMLResponse)
def security_dashboard(request: Request):
    require_login(request)
    return templates.TemplateResponse(
        "security.html",
        _context(request, {"security": monitoring.coraza_summary()}),
    )


@app.get("/healthz")
def healthz():
    return PlainTextResponse("ok")