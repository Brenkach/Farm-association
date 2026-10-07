from functools import wraps

from flask import redirect, session, url_for


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "login" not in session:
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper
