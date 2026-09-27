"""Safe command-line account recovery for a self-hosted SolvAI workspace."""

import argparse
import getpass

from engine import auth


def _password(prompt="Password: "):
    first = getpass.getpass(prompt)
    second = getpass.getpass("Confirm password: ")
    if first != second:
        raise auth.AuthError("Passwords do not match.", "password_mismatch")
    return first


def main():
    parser = argparse.ArgumentParser(description="Manage SolvAI accounts without exposing passwords.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="List safe account metadata")
    create = commands.add_parser("create-admin", help="Create or promote an administrator")
    create.add_argument("email")
    create.add_argument("--name", default="Workspace Admin")
    reset = commands.add_parser("reset-password", help="Reset an account password")
    reset.add_argument("email")
    args = parser.parse_args()

    auth.init_auth_db()
    try:
        if args.command == "list":
            users = auth.list_users()
            if not users:
                print("No users registered.")
            for user in users:
                print(f"{user['email']} | {user['display_name']} | {user['role']} | {'active' if user['is_active'] else 'inactive'} | logins={user['login_count']}")
        elif args.command == "create-admin":
            password = _password()
            try:
                user = auth.create_user(args.email, password, args.name, role="admin")
            except auth.AuthError as exc:
                if exc.code != "email_exists":
                    raise
                auth.set_password(args.email, password)
                user = auth.set_role(args.email, "admin")
            print(f"Administrator ready: {user['email']}")
        elif args.command == "reset-password":
            user = auth.set_password(args.email, _password("New password: "))
            print(f"Password reset: {user['email']}")
    except auth.AuthError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
