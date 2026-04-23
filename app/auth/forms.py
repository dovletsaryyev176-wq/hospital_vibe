from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Length


class _BaseLoginForm(FlaskForm):
    username = StringField(
        'Логин',
        validators=[DataRequired(message='Введите логин'), Length(max=50)],
        render_kw={'placeholder': 'Введите логин', 'autofocus': True},
    )
    password = PasswordField(
        'Пароль',
        validators=[DataRequired(message='Введите пароль')],
        render_kw={'placeholder': 'Введите пароль'},
    )
    remember_me = BooleanField('Запомнить меня')
    submit = SubmitField('Войти')


class AdminLoginForm(_BaseLoginForm):
    pass


class LoginForm(_BaseLoginForm):
    pass
