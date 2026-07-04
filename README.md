# Kandang Kebo Docker

Docker Hosting Panel for small VPS hosting operations. It provisions one Docker Compose stack per site, with Traefik routing, Nginx, PHP-FPM/CMS images, MariaDB, per-site SFTP, backup, and SQL restore tools.

Built for `ashadebi/kandang-kebo-docker`.

![Dashboard](docs/screenshots/dashboard.svg)

## Features

- Admin dashboard with FastAPI, Jinja, and lightweight HTMX-ready templates.
- Create sites under `/home/<username>`.
- Generate one `docker-compose.yml` per site.
- Per-site containers:
  - Nginx
  - PHP-FPM or CMS image
  - MariaDB
  - isolated SFTP container
- Traefik reverse proxy with HTTPS labels.
- HTTP to HTTPS redirect for the panel and every hosted site.
- Automatic Let's Encrypt certificates, with optional custom certificate upload per site.
- Global fallback 404 page for unknown hostnames.
- Optional Coraza WAF middleware per site.
- PHP version selector from legacy PHP 5.6 up to PHP 8.4.
- CMS starters for WordPress, Joomla, and Drupal.
- `php.ini` presets for normal, large, and very large uploads.
- CPU/RAM resource presets.
- Detail page with generated SFTP and MySQL credentials.
- Upload `backup.sql` and restore directly into the site's MariaDB container.
- Database backup action.
- Permission rules for CMS and SFTP compatibility.
- Footer link: [teer.id/ashadebi](https://teer.id/ashadebi).

![Site Detail](docs/screenshots/site-detail.svg)

## Architecture

```text
internet
  |
  v
Traefik :80/:443
  |
  +-- hosting-dashboard
  +-- hosting-notfound
  +-- site-client1-nginx
        |
        +-- site-client1-php
        +-- site-client1-db
        +-- site-client1-sftp :22000
```

Each site has its own internal Docker network. Only Nginx joins the public Traefik network. PHP-FPM, MariaDB, and SFTP stay isolated inside the site stack.

## Directory Layout

When a site is created, the panel creates:

```text
/home/<username>/
  public_html/
  logs/
  goaccess/
  backups/
    database/
    files/
  tmp/
  ssl/
  config/
  compose/
```

## Requirements

- Debian 12 or compatible Linux VPS.
- Root SSH access.
- Docker and Docker Compose, or let the deploy script install them.
- DNS pointed to the VPS for panel and hosted domains.

## Quick Start

Copy `.env.example`:

```bash
cp .env.example .env
```

Edit these values:

```env
PANEL_DOMAIN=panel.example.com
LETSENCRYPT_EMAIL=admin@example.com
ADMIN_USERNAME=admin
ADMIN_PASSWORD=change-this-password
SESSION_SECRET=change-this-long-random-secret
HOST_HOME_ROOT=/home
HOST_PROJECT_ROOT=/opt/docker-hosting-panel
PUBLIC_NETWORK=hosting-public
SFTP_PORT=2222
FALLBACK_HOST_REGEXP=.+
```

Generate SFTP host keys:

```bash
mkdir -p data/sftp
ssh-keygen -t ed25519 -N "" -f data/sftp/ssh_host_ed25519_key
ssh-keygen -t rsa -b 4096 -N "" -f data/sftp/ssh_host_rsa_key
chmod 600 data/sftp/ssh_host_*_key
```

Start the panel:

```bash
docker compose up -d --build
```

Open:

```text
https://PANEL_DOMAIN
```

## One-command VPS Deploy

From your local copy:

```bash
./scripts/deploy-vps.sh root@SERVER_IP SSH_PORT
```

Example:

```bash
./scripts/deploy-vps.sh root@203.0.113.10 22
```

For non-interactive deploys:

```bash
export PANEL_DOMAIN=panel.example.com
export LETSENCRYPT_EMAIL=admin@example.com
export ADMIN_USERNAME=admin
export ADMIN_PASSWORD='change-this-to-a-strong-password'
export SESSION_SECRET='long-random-secret'
export HOST_HOME_ROOT=/home
export HOST_PROJECT_ROOT=/opt/docker-hosting-panel
export FALLBACK_HOST_REGEXP='.+\\.example\\.com'
./scripts/deploy-vps.sh root@SERVER_IP SSH_PORT
```

The script will install host packages, upload the project, write `.env`, generate SFTP host keys, and start the Docker stack.

## SFTP Model

The global `2222` service is only a placeholder. Real users get isolated SFTP services per site.

Port allocation:

```text
first site   -> 22000
second site  -> 22001
third site   -> 22002
```

The site detail page shows the exact SFTP port, username, and password.

## Database Restore

Open a site detail page and use **Restore Database** to upload a `.sql` file. The panel stores the uploaded file under the site's backup directory and restores it into the site's MariaDB container.

The detail page also shows:

- DB host: `db`
- database name
- database user
- database password

## HTTPS Certificates

Every panel and hosted site HTTP request redirects to HTTPS automatically.

Default behavior:

- Traefik requests and renews Let's Encrypt certificates with the HTTP-01 challenge.
- Make sure DNS points to the VPS and ports `80` and `443` are reachable from the public internet.

Custom certificate behavior:

- Open the site detail page.
- Upload a PEM certificate/fullchain file and a PEM private key.
- Files are stored under `data/custom-certs/<username>/`.
- Traefik loads them through the dynamic file provider.
- Removing the custom certificate returns the site to automatic Let's Encrypt.

## Permission Rules

Writable web paths:

```text
/home/<username>/public_html
/home/<username>/tmp
```

Rules:

- owner UID/GID: `82:82`
- directory mode: `755`
- file mode: `644`
- applied during create, start, and restart

CMS starters do not receive a default `phpinfo()` index file, so official CMS images can copy their core files into an empty `public_html`.

## Coraza WAF

Traefik loads the Coraza plugin and a file middleware named:

```text
coraza-waf@file
```

Enable the WAF checkbox during site creation to attach that middleware to the site's Traefik router.

Rules live in:

```text
traefik/dynamic/coraza-waf.yml
```

The included rules are a lightweight starter. Review and tune before production use.

## Security Notes

This panel controls Docker and should be treated like root access.

- Use HTTPS.
- Use a strong admin password.
- Keep `.env` private.
- Keep `data/panel.sqlite` private.
- Do not commit generated SFTP host keys.
- Restrict panel access by firewall or VPN if possible.
- Patch the host OS and CMS plugins regularly.

## Do Not Commit

The `.gitignore` excludes:

- `.env`
- `data/panel.sqlite`
- `data/letsencrypt/`
- `data/custom-certs/`
- generated SFTP host keys
- Python caches
- logs

## Project Notes

More operational notes are in:

```text
PROJECT_DOCKER_HOSTING.md
```

## License

MIT. See `LICENSE`.

---

[teer.id/ashadebi](https://teer.id/ashadebi)
