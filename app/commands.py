import click
from flask.cli import with_appcontext
from app.extensions import db
from app.models import User


@click.command('create-admin')
@click.option('--username', prompt='Ulanyjy ady', help='Dolandyryjynyň ulanyjy ady ')
@click.option('--full-name', prompt='FAA', help='Dolandyryjynyň doly ady')
@click.option('--phone', prompt='Telefon belgisi', help='Telefon belgisi')
@click.option('--password', prompt=True, hide_input=True, confirmation_prompt=True, help='Gizlin belgi')
@with_appcontext
def create_admin(username, full_name, phone, password):
    """Создать учётную запись администратора."""
    if User.query.filter_by(username=username).first():
        click.echo(f'Ýalňyşlyk: bu "{username}" atly ulanyjy eýýäm hasaba alnan.')
        return

    admin = User(
        username=username,
        full_name=full_name,
        role='administrator',
        phone_number=phone,
        is_active=True,
    )
    admin.set_password(password)
    db.session.add(admin)
    db.session.commit()
    click.echo(f'Dolandyryjy "{username}" döredilen.')
