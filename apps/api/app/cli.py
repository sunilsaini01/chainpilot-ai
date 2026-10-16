"""Command-line tools. Used to create the first admin, before anyone can log in.

Example (inside Docker, prompts for the password without echoing it):
    docker compose run --rm api python -m app.cli create-user \\
        --email admin@example.com --full-name "Demo Admin" --role admin

Synthetic demo data (refuses to run twice):
    docker compose run --rm api python -m app.cli seed --products 200 --warehouses 4 --seed 42

Demand forecasts from the ML pipeline (M5 public data):
    python -m app.cli import-forecasts ../../data/processed/forecasts/m5_lightgbm_weekly_2016-04-24

Delivery-risk scores from the ML pipeline (Olist public data):
    python -m app.cli import-delivery-risk ../../data/processed/delivery_risk/<run folder>

Demo link from SYN- products to M5 demand (after import-forecasts and seed):
    python -m app.cli link-demand-profiles

Policy documents for the AI copilot (default folder: apps/api/policies):
    python -m app.cli load-policies

AI copilot (needs OPENAI_API_KEY and OPENAI_MODEL; each question costs a little):
    python -m app.cli investigate "Which suppliers are at risk?"

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
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app.audit import record_event
from app.copilot.service import CopilotNotConfiguredError, configured_model, run_and_save
from app.database import get_engine
from app.delivery_risk_import import DeliveryRiskImportError, import_delivery_risk
from app.forecast_import import ForecastImportError, import_forecasts
from app.login_throttle import delete_old_attempts
from app.models import Role
from app.policies_service import DEFAULT_FOLDER as POLICY_FOLDER
from app.policies_service import PolicyError, sync_policies
from app.replenishment_service import NoForecastRunError, link_demand_profiles
from app.seed import AlreadySeededError, build_plan, load_plan
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


def seed_command(args: argparse.Namespace) -> int:
    """Load deterministic synthetic warehouses, products, stock, suppliers and orders.

    Today's date is the demo's "as of" date: order history ends today and orders
    not yet delivered are open. The same seed on the same day gives the same data.
    """
    try:
        plan = build_plan(
            seed=args.seed,
            n_products=args.products,
            n_warehouses=args.warehouses,
            as_of=datetime.now(UTC).date(),
        )
        with Session(get_engine()) as session:
            summary = load_plan(session, plan)
            session.commit()
    except (ValueError, AlreadySeededError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    print(
        f"Loaded SYNTHETIC data (seed {args.seed}): {summary['warehouses']} warehouses, "
        f"{summary['products']} products, {summary['opening_movements']} opening stock "
        f"movements, {summary['units']} units, {summary['suppliers']} suppliers, "
        f"{summary['purchase_orders']} purchase orders ({summary['open_purchase_orders']} open)"
    )
    return 0


def import_forecasts_command(args: argparse.Namespace) -> int:
    """Load a forecast folder (forecasts.csv + manifest.json) into the database."""
    try:
        with Session(get_engine()) as session:
            run = import_forecasts(session, args.folder)
            record_event(
                session,
                "forecast_run.imported",
                "forecast_run",
                run.id,
                actor=None,  # a command-line import has no logged-in user
                details={"run_key": run.run_key, "rows": run.row_count, "name": run.name},
            )
            session.commit()
            print(
                f"Imported forecast run id={run.id} ({run.row_count} rows, "
                f"{run.forecast_start} to {run.forecast_end})"
            )
    except ForecastImportError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


def link_demand_profiles_command(args: argparse.Namespace) -> int:
    """Link SYN- products and warehouses to M5 forecast profiles (demo link, D-044)."""
    try:
        with Session(get_engine()) as session:
            summary = link_demand_profiles(session)
            record_event(
                session,
                "demand_profiles.linked",
                "demand_profile",
                None,
                actor=None,
                details=summary,
            )
            session.commit()
    except NoForecastRunError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    print(
        f"Linked {summary['products']} SYN- products and {summary['warehouses']} SYN- warehouses "
        f"to forecast run {summary['forecast_run_id']} (borrowed M5 demand profiles)"
    )
    return 0


def investigate_command(args: argparse.Namespace) -> int:
    """Ask the AI copilot one question (calls OpenAI) and print the answer."""
    try:
        model = configured_model()
        with Session(get_engine()) as session:
            run = run_and_save(session, model, args.question, actor=None)
            session.commit()
            # Printed while the session is open: the run's fields are reloaded after commit.
            answer = run.answer or {}
            print(f"Run {run.id}: {run.status}, grounded={answer.get('grounded')}")
            print(answer.get("answer") or run.error or "(no answer)")
            print(f"Citations: {', '.join(answer.get('citations', [])) or 'none'}")
            if answer.get("unsupported_citations"):
                removed = ", ".join(answer["unsupported_citations"])
                print(f"Removed (not supported by the tools): {removed}")
            print(
                f"Model {run.model}: {run.model_calls} calls, {run.tool_calls} tool calls, "
                f"{run.prompt_tokens} + {run.completion_tokens} tokens, "
                f"{run.duration_ms / 1000:.1f} s"
            )
            completed = run.status == "completed"
    except (CopilotNotConfiguredError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0 if completed else 1


def load_policies_command(args: argparse.Namespace) -> int:
    """Make the policy table match the policy folder (added, updated, removed documents)."""
    try:
        with Session(get_engine()) as session:
            result = sync_policies(session, args.folder)
            record_event(session, "policies.loaded", "policy", None, actor=None, details=result)
            session.commit()
    except PolicyError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    counts = ", ".join(f"{len(names)} {kind}" for kind, names in result.items())
    print(f"Policies: {counts}")
    for kind in ("added", "updated", "removed"):
        for name in result[kind]:
            print(f"  {kind}: {name}")
    return 0


def import_delivery_risk_command(args: argparse.Namespace) -> int:
    """Load a delivery-risk scoring folder (scores.csv + manifest.json) into the database."""
    try:
        with Session(get_engine()) as session:
            run = import_delivery_risk(session, args.folder)
            record_event(
                session,
                "delivery_risk_run.imported",
                "delivery_risk_run",
                run.id,
                actor=None,  # a command-line import has no logged-in user
                details={"run_key": run.run_key, "rows": run.row_count, "name": run.name},
            )
            session.commit()
            print(
                f"Imported delivery-risk run id={run.id} ({run.row_count} orders, "
                f"{run.period_start} to {run.period_end})"
            )
    except DeliveryRiskImportError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
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

    seed = commands.add_parser("seed", help="Load synthetic demo data (SYN- codes)")
    seed.add_argument("--products", type=int, default=200, help="100 to 500")
    seed.add_argument("--warehouses", type=int, default=4, help="3 to 5")
    seed.add_argument("--seed", type=int, default=42, help="same seed, same data")
    seed.set_defaults(handler=seed_command)

    forecasts = commands.add_parser(
        "import-forecasts", help="Import a forecast folder from ml/demand_forecasting/publish.py"
    )
    forecasts.add_argument("folder", type=Path)
    forecasts.set_defaults(handler=import_forecasts_command)

    risk = commands.add_parser(
        "import-delivery-risk", help="Import a scoring folder from ml/delivery_risk/scoring.py"
    )
    risk.add_argument("folder", type=Path)
    risk.set_defaults(handler=import_delivery_risk_command)

    link = commands.add_parser(
        "link-demand-profiles",
        help="Give SYN- products and warehouses borrowed M5 demand (after import-forecasts)",
    )
    link.set_defaults(handler=link_demand_profiles_command)

    policies = commands.add_parser(
        "load-policies", help="Load the policy documents for the AI copilot"
    )
    policies.add_argument("folder", type=Path, nargs="?", default=POLICY_FOLDER)
    policies.set_defaults(handler=load_policies_command)

    ask = commands.add_parser(
        "investigate", help="Ask the AI copilot a question (calls OpenAI; costs money)"
    )
    ask.add_argument("question")
    ask.set_defaults(handler=investigate_command)

    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
