import subprocess
from pathlib import Path
from shutil import which

import docker


def client():
    return docker.from_env()


def compose_project_name(site_compose: Path) -> str:
    username = site_compose.parent.parent.name
    default_project = f"site-{username}"
    container_prefix = f"site-{username}-"

    try:
        for container in client().containers.list(all=True, filters={"name": container_prefix}):
            if not container.name.startswith(container_prefix):
                continue
            labels = container.attrs.get("Config", {}).get("Labels") or {}
            project = labels.get("com.docker.compose.project")
            if project:
                return project
    except Exception:
        pass

    return default_project


def compose(site_compose: Path, action: str) -> str:
    allowed = {"up", "down", "restart", "logs"}
    if action not in allowed:
        raise ValueError(f"Unsupported compose action: {action}")

    project_name = compose_project_name(site_compose)
    if which("docker"):
        cmd = ["docker", "compose", "-p", project_name, "-f", str(site_compose)]
    elif which("docker-compose"):
        cmd = ["docker-compose", "-p", project_name, "-f", str(site_compose)]
    else:
        return "Docker CLI tidak ditemukan di container dashboard."

    if action == "up":
        cmd += ["up", "-d"]
    elif action == "down":
        cmd += ["down"]
    elif action == "restart":
        cmd += ["restart"]
    elif action == "logs":
        cmd += ["logs", "--tail", "200"]

    result = subprocess.run(cmd, check=False, text=True, capture_output=True)
    if result.returncode != 0 and cmd[:2] == ["docker", "compose"] and which("docker-compose"):
        fallback = ["docker-compose", "-p", project_name, "-f", str(site_compose)] + cmd[6:]
        result = subprocess.run(fallback, check=False, text=True, capture_output=True)
    return result.stdout + result.stderr


def remove_stack(site_compose: Path) -> str:
    project_name = compose_project_name(site_compose)
    if which("docker"):
        cmd = ["docker", "compose", "-p", project_name, "-f", str(site_compose), "down", "-v", "--remove-orphans"]
    elif which("docker-compose"):
        cmd = ["docker-compose", "-p", project_name, "-f", str(site_compose), "down", "-v", "--remove-orphans"]
    else:
        return "Docker CLI tidak ditemukan di container dashboard."

    result = subprocess.run(cmd, check=False, text=True, capture_output=True)
    if result.returncode != 0 and cmd[:2] == ["docker", "compose"] and which("docker-compose"):
        fallback = ["docker-compose", "-p", project_name, "-f", str(site_compose), "down", "-v", "--remove-orphans"]
        result = subprocess.run(fallback, check=False, text=True, capture_output=True)
    return result.stdout + result.stderr


def restart_container(name: str) -> None:
    try:
        client().containers.get(name).restart()
    except Exception:
        pass


def recreate_compose_service(project_dir: Path, service: str) -> None:
    project_name = compose_project_name(project_dir / "docker-compose.yml")
    if which("docker"):
        cmd = ["docker", "compose", "-p", project_name, "up", "-d", "--force-recreate", "--no-deps", service]
    elif which("docker-compose"):
        cmd = ["docker-compose", "-p", project_name, "up", "-d", "--force-recreate", "--no-deps", service]
    else:
        return

    result = subprocess.run(cmd, cwd=project_dir, check=False, text=True, capture_output=True)
    if result.returncode != 0 and cmd[:2] == ["docker", "compose"] and which("docker-compose"):
        subprocess.run(
            ["docker-compose", "-p", project_name, "up", "-d", "--force-recreate", "--no-deps", service],
            cwd=project_dir,
            check=False,
            text=True,
            capture_output=True,
        )


def container_status(prefix: str) -> list[dict]:
    rows = []
    for container in client().containers.list(all=True):
        if container.name.startswith(prefix):
            rows.append(
                {
                    "name": container.name,
                    "status": container.status,
                    "image": container.image.tags[0] if container.image.tags else container.image.short_id,
                }
            )
    return rows
