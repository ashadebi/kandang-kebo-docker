from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exception_handlers import http_exception_handler as default_http_exception_handler
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from .auth import require_login, verify_admin
from .config import settings
from .database import init_db
from . import site_manager
from . import monitoring


app = FastAPI(title="Docker Hosting Panel")
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        return templates.TemplateResponse("404.html", {"request": request}, status_code=404)
    return await default_http_exception_handler(request, exc)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if verify_admin(username, password):
        request.session["admin"] = username
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "error": "Login gagal."})


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    require_login(request)
    return templates.TemplateResponse("dashboard.html", {"request": request, "sites": site_manager.list_sites()})


@app.get("/security", response_class=HTMLResponse)
def security_dashboard(request: Request):
    require_login(request)
    return templates.TemplateResponse("security.html", {"request": request, "security": monitoring.coraza_summary()})


@app.get("/sites/new", response_class=HTMLResponse)
def new_site(request: Request):
    require_login(request)
    return templates.TemplateResponse("site_form.html", {"request": request, "error": None})


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
):
    require_login(request)
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
        )
    except Exception as exc:
        return templates.TemplateResponse("site_form.html", {"request": request, "error": str(exc)})
    return RedirectResponse("/", status_code=303)


@app.get("/sites/{site_id}", response_class=HTMLResponse)
def site_detail(request: Request, site_id: int):
    require_login(request)
    site = site_manager.get_site(site_id)
    if not site:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse("site_detail.html", {"request": request, "site": site, "output": None})


@app.post("/sites/{site_id}/restore-db", response_class=HTMLResponse)
def restore_database(request: Request, site_id: int, backup_file: UploadFile = File(...)):
    require_login(request)
    site = site_manager.get_site(site_id)
    if not site:
        raise HTTPException(status_code=404)
    if not backup_file.filename.endswith(".sql"):
        output = "Upload ditolak. File restore harus berekstensi .sql."
    else:
        output = site_manager.restore_database(site, backup_file.file, backup_file.filename)
    site = site_manager.get_site(site_id)
    return templates.TemplateResponse("site_detail.html", {"request": request, "site": site, "output": output})


@app.post("/sites/{site_id}/awstats/update", response_class=HTMLResponse)
def update_awstats(request: Request, site_id: int):
    require_login(request)
    site = site_manager.get_site(site_id)
    if not site:
        raise HTTPException(status_code=404)
    output = site_manager.generate_awstats_report(site)
    site = site_manager.get_site(site_id)
    return templates.TemplateResponse("site_detail.html", {"request": request, "site": site, "output": output})


@app.post("/sites/{site_id}/upload-certificate", response_class=HTMLResponse)
def upload_certificate(
    request: Request,
    site_id: int,
    certificate_file: UploadFile = File(...),
    private_key_file: UploadFile = File(...),
):
    require_login(request)
    site = site_manager.get_site(site_id)
    if not site:
        raise HTTPException(status_code=404)
    try:
        output = site_manager.upload_custom_certificate(site, certificate_file.file, private_key_file.file)
    except Exception as exc:
        output = f"Upload sertifikat gagal: {exc}"
    site = site_manager.get_site(site_id)
    return templates.TemplateResponse("site_detail.html", {"request": request, "site": site, "output": output})


@app.post("/sites/{site_id}/remove-certificate", response_class=HTMLResponse)
def remove_certificate(request: Request, site_id: int):
    require_login(request)
    site = site_manager.get_site(site_id)
    if not site:
        raise HTTPException(status_code=404)
    output = site_manager.remove_custom_certificate(site)
    site = site_manager.get_site(site_id)
    return templates.TemplateResponse("site_detail.html", {"request": request, "site": site, "output": output})


@app.post("/sites/{site_id}/{action}", response_class=HTMLResponse)
def site_action(request: Request, site_id: int, action: str):
    require_login(request)
    site = site_manager.get_site(site_id)
    if not site:
        raise HTTPException(status_code=404)
    if action == "backup-db":
        output = site_manager.backup_database(site)
    else:
        output = site_manager.site_action(site, action)
    site = site_manager.get_site(site_id)
    return templates.TemplateResponse("site_detail.html", {"request": request, "site": site, "output": output})


@app.get("/healthz")
def healthz():
    return PlainTextResponse("ok")
