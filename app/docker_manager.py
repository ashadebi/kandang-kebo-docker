import subprocess
from pathlib import Path
from shutil import which

import docker


def client():
    return docker.from_env()


def compose(site_compose: Path, action: str) -> str:
    allowed = {"up", "down", "restart", "logs"}
    if action not in allowed:
        raise ValueError(f"Unsupported compose action: {action}")

    if which("docker"):
        cmd = ["docker", "compose", "-f", str(site_compose)]
    elif which("docker-compose"):
        cmd = ["docker-compose", "-f", str(site_compose)]
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
        fallback = ["docker-compose", "-f", str(site_compose)] + cmd[4:]
        result = subprocess.run(fallback, check=False, text=True, capture_output=True)
    return result.stdout + result.stderr


def restart_container(name: str) -> None:
    try:
        client().containers.get(name).restart()
    except Exception:
        pass


def recreate_compose_service(project_dir: Path, service: str) -> None:
    if which("docker"):
        cmd = ["docker", "compose", "up", "-d", "--force-recreate", service]
    elif which("docker-compose"):
        cmd = ["docker-compose", "up", "-d", "--force-recreate", service]
    else:
        return

    result = subprocess.run(cmd, cwd=project_dir, check=False, text=True, capture_output=True)
    if result.returncode != 0 and cmd[:2] == ["docker", "compose"] and which("docker-compose"):
        subprocess.run(
            ["docker-compose", "up", "-d", "--force-recreate", service],
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
