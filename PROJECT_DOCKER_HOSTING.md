# Project: Docker Hosting

Docker Hosting is a lightweight hosting control panel built with FastAPI, Docker Compose, Traefik, and per-site containers. This document keeps the project easy to continue, deploy, and extend.

## Project Identity

- Project name: Docker Hosting
- Repository target: `ashadebi/kandang-kebo-docker`
- Default install path: `/opt/docker-hosting-panel`
- Default site home root: `/home`
- Main deploy script: `scripts/deploy-vps.sh`

## Core Features

- Admin dashboard with FastAPI and Jinja templates.
- Site provisioning under `/home/<username>`.
- Per-site Docker Compose stack:
  - Nginx
  - PHP-FPM or CMS image
  - MariaDB
  - isolated SFTP container
- Traefik reverse proxy with HTTPS labels.
- Global fallback 404 service for unknown hostnames.
- Optional Coraza WAF middleware per site.
- PHP version selector.
- CMS starter selector for WordPress, Joomla, and Drupal.
- `php.ini` upload presets.
- CPU/RAM resource presets.
- Detail page with SFTP and MySQL credentials.
- `.sql` upload and restore into the site's MariaDB container.
- Database backup action from the panel.

## Permission Rules

Writable web paths:

- `/home/<username>/public_html`
- `/home/<username>/tmp`

Rules:

- owner UID/GID: `82:82`
- directory mode: `755`
- file mode: `644`
- applied during site creation
- re-applied before Start/Restart actions

CMS sites do not receive the default `phpinfo()` index file. This lets official CMS images copy their application files into an empty `public_html`.

## SFTP Rules

- Legacy/global SFTP port `2222` is a placeholder only.
- Real site access uses one isolated SFTP container per site.
- Site SFTP ports are allocated sequentially from `22000`.
- Example:
  - first site: `22000`
  - second site: `22001`
  - third site: `22002`

This is easier to support than random ports and avoids multiple users sharing one SFTP daemon.

## Fast VPS Deploy

Run from the project directory:

```bash
./scripts/deploy-vps.sh root@SERVER_IP SSH_PORT
```

Example:

```bash
./scripts/deploy-vps.sh root@203.0.113.10 22
```

For non-interactive deploys, export environment values first:

```bash
export PANEL_DOMAIN=panel.example.com
export LETSENCRYPT_EMAIL=admin@example.com
export ADMIN_USERNAME=admin
export ADMIN_PASSWORD='change-me-to-a-strong-password'
export SESSION_SECRET='long-random-secret'
export HOST_HOME_ROOT=/home
export HOST_PROJECT_ROOT=/opt/docker-hosting-panel
export FALLBACK_HOST_REGEXP='.+\\.example\\.com'
```

The deploy script installs host requirements, uploads the project, writes `.env`, generates SFTP host keys, and starts the Docker stack.

## GitHub Notes

This project is intended for the public repository:

```text
ashadebi/kandang-kebo-docker
```

Do not commit real `.env`, database files, TLS account files, private keys, or generated SFTP host keys.
