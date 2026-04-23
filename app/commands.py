import click
from flask.cli import with_appcontext
from app.extensions import db
from app.models import User


@click.command('create-admin')
@click.option('--username', prompt='Логин', help='Логин администратора')
@click.option('--full-name', prompt='ФИО', help='Полное имя администратора')
@click.option('--phone', prompt='Телефон', help='Телефонный номер')
@click.option('--password', prompt=True, hide_input=True, confirmation_prompt=True, help='Пароль')
@with_appcontext
def create_admin(username, full_name, phone, password):
    """Создать учётную запись администратора."""
    if User.query.filter_by(username=username).first():
        click.echo(f'Ошибка: пользователь "{username}" уже существует.')
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
    click.echo(f'Администратор "{username}" успешно создан.')
