import os
from pathlib import Path


class Settings:
    panel_domain = os.getenv("PANEL_DOMAIN", "panel.localhost")
    admin_username = os.getenv("ADMIN_USERNAME", "admin")
    admin_password = os.getenv("ADMIN_PASSWORD", "admin")
    session_secret = os.getenv("SESSION_SECRET", "change-me")
    session_idle_timeout_seconds = int(os.getenv("SESSION_IDLE_TIMEOUT_SECONDS", "1800"))
    host_home_root = Path(os.getenv("HOST_HOME_ROOT", "/home"))
    container_home_root = Path("/host-home")
    project_root = Path(os.getenv("HOST_PROJECT_ROOT", "/opt/docker-hosting-panel"))
    public_network = os.getenv("PUBLIC_NETWORK", "hosting-public")
    sftp_port = int(os.getenv("SFTP_PORT", "2222"))
    data_dir = Path("/app/data")
    templates_dir = Path("/app/templates-compose")


settings = Settings()
