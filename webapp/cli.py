import click
from flask import current_app

from .extensions import db
from .models import Role, User


@click.command("create-superadmin")
@click.argument("username")
@click.argument("password")
def create_superadmin(username: str, password: str):
    """Create a superadmin user."""
    u = User.query.filter_by(username=username).first()
    if u:
        click.echo("User already exists.")
        return
    u = User(username=username, full_name=username, role=Role.SUPERADMIN.value, school_id=None, is_active=True)
    u.set_password(password)
    db.session.add(u)
    db.session.commit()
    click.echo("Superadmin created.")

