# Data Retention

What ChainPilot AI stores about people, why, and for how long. All operational data in this project is synthetic or from public datasets; the personal data below is only about the people who use the application (analysts, managers, admins).

| Data | Where | Why it is kept | How long | How it is removed |
|---|---|---|---|---|
| Name, email, role, active flag | `users` | Login and access control | While the account exists | Accounts are **deactivated**, not deleted, because stock movements and audit events must keep pointing at who acted. |
| Password | `users.password_hash` | Login | While the account exists | Only a scrypt hash is stored; the password itself is never stored or logged. |
| Login tokens | `auth_tokens` | Keeping a user logged in | Until expiry (8 h by default) or logout, then up to **30 days** | `python -m app.cli cleanup --days 30` deletes tokens that expired or were revoked more than 30 days ago. Only SHA-256 hashes of tokens are stored. |
| Login attempts: email as typed (possibly mistyped), client IP, success flag, time | `login_attempts` | Rate limiting against password guessing (15-minute window), and investigating attacks | **30 days** | Same `cleanup` command. Only the last 15 minutes affect rate limiting; the rest is kept for investigations. |
| Audit events: acting user id, action, changed values | `audit_events` | Accountability: who changed users, master data and stock, and when | **Kept** (business record) | Not deleted by `cleanup`. Details never contain passwords, tokens or hashes. |
| Application logs: user ids, request lines, client IPs | stdout / CloudWatch (later) | Operations and debugging | Local: until the container is removed. AWS (P8): set a CloudWatch retention period (e.g. 30 days). | Logs never contain passwords, tokens, or the emails used in failed logins. |

## Running the cleanup

Run it daily, for example from cron or a scheduled task:

```bash
docker compose run --rm api python -m app.cli cleanup --days 30
```

`--days` must be at least 1, which keeps the 15-minute rate-limit window intact. In AWS (P8) this becomes a scheduled ECS task.

## Changing these periods

If a real organisation adopted this system, its data-protection policy would set the periods. The values here are sensible defaults for a portfolio demo, not legal advice.
