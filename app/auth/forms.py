from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Length


class _BaseLoginForm(FlaskForm):
    username = StringField(
        'Ulanyjy ady',
        validators=[DataRequired(message='Ulanyjy ady giriziň'), Length(max=50)],
        render_kw={'placeholder': 'Ulanyjy ady giriziň', 'autofocus': True},
    )
    password = PasswordField(
        'Gizlin belgi',
        validators=[DataRequired(message='Gizlin belgini giriziň')],
        render_kw={'placeholder': 'Gizlin belgini giriziň'},
    )
    remember_me = BooleanField('Meni ýatda sakla')
    submit = SubmitField('Ulgama girmek')


class AdminLoginForm(_BaseLoginForm):
    pass


class LoginForm(_BaseLoginForm):
    pass
