from functools import wraps

from flask import session, redirect, url_for
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def require_roles(*roles):
    """
    Декоратор для перевірки прав доступу.
    Якщо користувач не авторизований – редірект на /login.
    Якщо роль не підходить – редірект на /forbidden.
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            login = session.get("login")
            access = session.get("access_right")

            if not login:
                return redirect(url_for("login"))

            if roles and access not in roles:
                return redirect(url_for("forbidden"))

            return view_func(*args, **kwargs)

        return wrapper

    return decorator
