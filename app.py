import os

from flask import Flask, session
from sqlalchemy.engine import URL
from dotenv import load_dotenv

from extensions import db
from models import User, Specialization
from routes import register_routes

load_dotenv()


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "devkey")

    db_url = URL.create(
        drivername="postgresql+pg8000",
        username=os.getenv("PG_USER"),
        password=os.getenv("PG_PASSWORD"),
        host=os.getenv("PG_HOST"),
        port=int(os.getenv("PG_PORT")),
        database=os.getenv("PG_DATABASE"),
    )
    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    @app.context_processor
    def inject_session():
        return dict(session=session)

    with app.app_context():
        db.create_all()

        admin = db.session.get(User, "admin")
        if not admin:
            su = User(login="admin", access_right="superuser")
            su.set_password("admin123")
            db.session.add(su)
            db.session.commit()

        if Specialization.query.count() == 0:
            popular_specs = [
                "Овочівництво",
                "Тваринництво",
                "Птахівництво",
                "Свинарство",
                "ВРХ (велика рогата худоба)",
                "Молочне скотарство",
                "Зернові культури",
                "Олійні культури",
                "Ягідництво",
                "Виноградарство",
                "Садівництво",
                "Пасіка / Бджільництво",
            ]

            db.session.add_all([Specialization(name=s) for s in popular_specs])
            db.session.commit()

    register_routes(app)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)

# ТЕСТОВІ ПОМИЛКИ ДЛЯ SONARCLOUD
import os

# 1. Hardcoded Credentials (Security Vulnerability)
DB_PASSWORD = "super_secret_hardcoded_password_12345"

# 2. Bad Practice / Code Smell (Порівняння булевих значень та дублювання)
def check_status(is_active):
    if is_active == True:
        return True
    else:
        return True