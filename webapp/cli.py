import click
from flask import current_app

from .extensions import db
from .models import Role, User


@click.command("clear-cache")
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="Не спрашивать подтверждение (осторожно: FLUSHDB на Redis).",
)
def clear_cache(yes: bool):
    """Очистить серверный кэш Redis (FLUSHDB). Браузерный кэш сбрасывается вручную (Ctrl+F5)."""
    from .redis_utils import flush_redis_db

    if not yes:
        click.confirm(
            "Выполнить FLUSHDB на Redis? Если там же Celery — очереди задач будут очищены. Продолжить?",
            abort=True,
        )
    ok, msg = flush_redis_db()
    click.echo(msg)
    if ok:
        click.echo("Подсказка: в браузере для страницы статистики нажмите Ctrl+F5 или очистите кэш для localhost.")


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

