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
  - MariaDB or PostgreSQL
  - isolated SFTP container
- Traefik reverse proxy with HTTPS labels.
- HTTP to HTTPS redirect for the panel and all hosted sites.
- Automatic Let's Encrypt certificates with optional custom certificate upload per site.
- Global fallback 404 service for unknown hostnames.
- Optional Coraza WAF middleware per site.
- PHP version selector.
- CMS starter selector for WordPress, Joomla, and Drupal.
- Database selector with MariaDB 11.4 and PostgreSQL 14-18 major/current-minor options.
- Custom PHP/CMS image override per site.
- Edit site runtime options after creation, including CMS/image choice.
- Delete site action from the panel, including compose stack, database volume, and site files.
- `php.ini` upload presets.
- CPU/RAM resource presets.
- Detail page with SFTP and database credentials.
- `.sql` upload and restore into the site's MariaDB or PostgreSQL container.
- Database backup action from the panel.

WordPress and Joomla official starter images expect MySQL/MariaDB. PostgreSQL is available for Drupal, blank PHP sites, or custom images that support PostgreSQL.

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

Drupal is handled specially because the official image stores the full project in `/opt/drupal` and exposes the web directory through `/var/www/html`. On first start, the site stack copies `/opt/drupal` into `/home/<username>/public_html` when `composer.json` is missing, then Nginx serves `/home/<username>/public_html/web`.

## SFTP Rules

- Legacy/global SFTP port `2222` is a placeholder only.
- Real site access uses one isolated SFTP container per site.
- Site SFTP ports are allocated sequentially from `22000`.
- Example:
  - first site: `22000`
  - second site: `22001`
  - third site: `22002`

This is easier to support than random ports and avoids multiple users sharing one SFTP daemon.

## HTTPS Rules

- HTTP traffic on port `80` redirects to HTTPS for the dashboard and every hosted site.
- If no custom certificate is uploaded, Traefik uses Let's Encrypt automatically.
- If a user uploads a paid/custom certificate, it is stored in `data/custom-certs/<username>/`.
- Traefik reads custom certificates from `traefik/dynamic/custom-certs.yml`.
- Removing the custom certificate returns the site to Let's Encrypt fallback.
- Let's Encrypt requires public DNS pointing to the VPS and open inbound ports `80` and `443`.

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
