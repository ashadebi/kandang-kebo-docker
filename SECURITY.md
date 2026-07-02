# Security Policy

## Production Notes

Kandang Kebo Docker controls Docker and can create containers, volumes, and networks. Treat dashboard access as privileged server access.

Recommended baseline:

- Use HTTPS for the panel.
- Use a strong admin password.
- Keep `.env` private.
- Keep `data/panel.sqlite` private.
- Never commit SFTP host keys.
- Restrict dashboard access with firewall rules or VPN when possible.
- Keep the host OS, Docker, CMS images, and CMS plugins updated.
- Review Coraza WAF rules before enabling for production sites.

## Sensitive Files

Do not publish:

```text
.env
data/panel.sqlite
data/letsencrypt/
data/sftp/ssh_host_*_key
data/sftp/ssh_host_*_key.pub
```

## Reporting

If you find a security issue, open a private report to the maintainer instead of publishing exploit details.

---

https://teer.id/ashadebi
