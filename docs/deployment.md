# Deployment (DigitalOcean)

The live site runs on one DigitalOcean Droplet with Docker. Every push to `main` that passes CI deploys itself, so
development carries on as usual and only tested changes reach customers.

```
GitHub: push to main ──► CI (tests, lint, build) ──► Deploy workflow: build images ──► Droplet: pull, migrate, restart
```

On the Droplet (`/opt/lintech`, from `deploy/docker-compose.yml`):

| Container | What it does |
|---|---|
| `web` | Caddy: serves the React app, gets and renews the HTTPS certificate, passes `/api`, `/platform-admin`, `/media`, `/static` and `/healthz` to the app |
| `app` | Django under Gunicorn. Applies new migrations each time it starts |
| `db` | PostgreSQL 17. Data in the `db` volume |
| `backup` | A compressed database copy every night at 02:00, the last 14 kept in the `backups` volume |

Uploaded logos and product photos live in the `media` volume, so they survive every deploy.

## Going live: once

### 1. The Droplet and the domain

1. In DigitalOcean create a Droplet: **Ubuntu 24.04**, **Basic, 2 GB RAM** (about $12/month; 1 GB is too small for
   the AI chat and image uploads together), region **Frankfurt** or **London** (closest to Kenya), with your SSH key.
   Turn on **weekly backups** in the Droplet settings: a second safety net besides the nightly database copies.
2. At your domain's DNS, add an **A record** for the site (e.g. `app.example.co.ke`) pointing to the Droplet's IP.
3. From this computer, set the server up (Docker, firewall, swap, the `deploy` user):

   ```bash
   ssh root@DROPLET_IP 'bash -s' < deploy/server-setup.sh
   ```

### 2. The live settings

1. Make the secrets (run each and keep the output):

   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(50))"       # SECRET_KEY, DB_PASSWORD, MPESA_CALLBACK_TOKEN
   python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"   # FIELD_ENCRYPTION_KEY
   ```

2. Copy `deploy/.env.production.example` to the server as `/opt/lintech/.env`, fill it in, and lock it down:

   ```bash
   scp deploy/.env.production.example deploy@DROPLET_IP:/opt/lintech/.env
   ssh deploy@DROPLET_IP 'chmod 600 /opt/lintech/.env && nano /opt/lintech/.env'
   ```

   `SITE_DOMAIN` is the one address that matters: allowed hosts, trusted origins, receipt links and the M-Pesa
   callback address all follow from it. Keep `FIELD_ENCRYPTION_KEY` safe and never change it: it encrypts each
   business's saved M-Pesa keys.

### 3. Let GitHub deploy

1. Make a key pair just for deploying (no passphrase), and let it into the server:

   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/lintech_deploy -N "" -C "github-deploy"
   ssh-copy-id -i ~/.ssh/lintech_deploy.pub deploy@DROPLET_IP
   ```

2. In GitHub → the repository → **Settings → Secrets and variables → Actions**, add:
   - `DEPLOY_HOST`: the Droplet's IP
   - `DEPLOY_USER`: `deploy`
   - `DEPLOY_SSH_KEY`: the whole content of `~/.ssh/lintech_deploy` (the private key)
3. Push to `main` (or **Actions → Deploy → Run workflow**). The first run takes a few minutes; it ends with
   `Live: <commit>`. Open `https://SITE_DOMAIN`.

### 4. The platform owner account, and your existing records

- **Starting empty:** make the platform owner account:

  ```bash
  ssh deploy@DROPLET_IP 'cd /opt/lintech && docker compose exec app python manage.py createsuperuser'
  ```

- **Bringing the records kept on this computer** (businesses, products, sales, chama, uploaded photos): after the
  first deploy, run once. It replaces the live database, and asks first:

  ```bash
  deploy/copy-local-data.sh deploy@DROPLET_IP
  ```

  Your accounts and passwords come with it. Businesses' saved M-Pesa keys only carry over if the server uses the same
  encryption key as this computer; otherwise owners enter them again in Settings → M-Pesa payments.

### 5. M-Pesa and email

- **M-Pesa callbacks** go to `https://SITE_DOMAIN/...` automatically (subscriptions, and each business's prompts at
  the till). Safaricom needs https on a real domain, so this works once step 1's DNS and certificate are in place.
- **Subscriptions by M-Pesa:** fill in the platform's own Daraja keys in `.env` and set `MPESA_MODE=production`.
- **Email** (password resets, emailed receipts): fill in the SMTP settings in `.env` (e.g. Zoho Mail, Brevo,
  Mailgun or Gmail with an app password). After any change to `.env`:

  ```bash
  ssh deploy@DROPLET_IP 'cd /opt/lintech && docker compose up -d'
  ```

## Developing while live

Work exactly as now. The rules that keep the live site safe:

1. **Work on a branch for anything big**, push it, and open a pull request: CI runs on it without deploying. Merge to
   `main` when it is green. Small, safe fixes can go straight to `main`; CI still has to pass before they deploy.
2. **Run the tests before pushing** (`cd server && venv/bin/python -m pytest`, `cd client && npm test`). A red CI never
   deploys, and the live site keeps the last good version.
3. **Migrations must work with the code already running**, because the app migrates as it starts:
   - adding a table or a nullable column, or one with a default: always fine;
   - renaming or removing a column: first deploy code that no longer uses it, then remove it in a later deploy;
   - never edit a migration that has already been deployed: add a new one.
4. **Secrets and settings live only in `/opt/lintech/.env`** on the server, never in the repository.
5. **Use your local data for development**. The live database is customers' real records: never point a local
   setup at it.

### Rolling back

**Actions → Deploy → Run workflow**, with **Commit** set to the last good commit's id (from the commit list). That
deploys that commit's code again. Migrations are not undone, so a rollback across a migration only works when the
migration was additive (rule 3).

## Running the live site

```bash
ssh deploy@DROPLET_IP
cd /opt/lintech
docker compose ps                          # what is running
docker compose logs -f --tail 100 app      # the app's log (errors show here)
docker compose logs -f web                 # requests and certificate renewals
docker compose restart app                 # restart the app
docker compose exec app python manage.py shell    # a Django shell on live data: careful
```

### Backups

Nightly copies are in the `backups` volume. List them, and copy the newest to this computer (keep copies off the
server too):

```bash
ssh deploy@DROPLET_IP 'cd /opt/lintech && docker compose exec backup ls -lh /backups'
ssh deploy@DROPLET_IP 'cd /opt/lintech && docker compose exec -T backup sh -c "cat \$(ls -1t /backups/*.dump | head -1)"' > lintech-latest.dump
```

To restore one (replaces the live database):

```bash
cd /opt/lintech && set -a && . ./.env && set +a
docker compose stop app
docker compose exec -T db dropdb -U "$DB_USER" --force "$DB_NAME"
docker compose exec -T db createdb -U "$DB_USER" "$DB_NAME"
docker compose exec -T backup pg_restore -h db -U "$DB_USER" -d "$DB_NAME" --no-owner /backups/lintech-YYYYMMDD-0200.dump
docker compose up -d app
```

### Health

`https://SITE_DOMAIN/healthz` answers `{"ok": true}` while the app is up and reaching its database. Point an uptime
monitor at it (DigitalOcean Uptime, or UptimeRobot, free) to get an email if the site goes down.
