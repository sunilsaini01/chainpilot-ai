"""Command-line tools. Used to create the first admin, before anyone can log in.

Example (inside Docker, prompts for the password without echoing it):
    docker compose run --rm api python -m app.cli create-user \\
        --email admin@example.com --full-name "Demo Admin" --role admin

Housekeeping (safe to run daily, e.g. from cron):
    docker compose run --rm api python -m app.cli cleanup --days 30

For scripts, the password can come from CHAINPILOT_NEW_USER_PASSWORD instead of
the prompt. It is never accepted as a command-line argument, because arguments
end up in shell history and process lists.
"""

import argparse
import getpass
import os
import sys
from datetime import timedelta

from sqlalchemy.orm import Session

from app.database import get_engine
from app.login_throttle import delete_old_attempts
from app.models import Role
from app.users_service import UserAlreadyExistsError, create_user, delete_stale_tokens

PASSWORD_ENV_VAR = "CHAINPILOT_NEW_USER_PASSWORD"


def read_password() -> str:
    """Password from the environment variable, or typed twice at a hidden prompt."""
    from_env = os.environ.get(PASSWORD_ENV_VAR)
    if from_env:
        return from_env
    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Repeat password: "):
        raise ValueError("Passwords do not match")
    return password


def create_user_command(args: argparse.Namespace) -> int:
    try:
        password = read_password()
        with Session(get_engine()) as session:
            user = create_user(session, args.email, args.full_name, Role(args.role), password)
            session.commit()
            print(f"Created user id={user.id} email={user.email} role={user.role}")
    except (ValueError, UserAlreadyExistsError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


def cleanup_command(args: argparse.Namespace) -> int:
    """Delete old expired/revoked tokens and old login attempts."""
    if args.days < 1:
        print("Error: --days must be at least 1", file=sys.stderr)
        return 1
    older_than = timedelta(days=args.days)
    with Session(get_engine()) as session:
        tokens = delete_stale_tokens(session, older_than)
        attempts = delete_old_attempts(session, older_than)
        session.commit()
    print(f"Deleted {tokens} stale tokens and {attempts} old login attempts")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="ChainPilot admin tools")
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create-user", help="Create a user account")
    create.add_argument("--email", required=True)
    create.add_argument("--full-name", required=True)
    create.add_argument("--role", required=True, choices=[role.value for role in Role])
    create.set_defaults(handler=create_user_command)

    cleanup = commands.add_parser("cleanup", help="Delete old tokens and login attempts")
    # Must stay longer than the login-throttle window (15 minutes); 30 days keeps a
    # month of login history for investigations.
    cleanup.add_argument("--days", type=int, default=30)
    cleanup.set_defaults(handler=cleanup_command)

    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
