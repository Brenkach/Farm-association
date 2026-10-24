import os
from consent import register_consent_routes
from personal_data import register_export_routes
from anonymization import register_anonymization_routes
from flask import Flask, session
from sqlalchemy.engine import URL
from dotenv import load_dotenv
from privacy_logging import setup_privacy_logging
from extensions import db
from models import User, Specialization
from routes import register_routes

load_dotenv()


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "devkey")
    setup_privacy_logging(app)


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
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "connect_args": {"timeout": 2}
    }

    db.init_app(app)

    @app.context_processor
    def inject_session():
        return dict(session=session)

    with app.app_context():
        db.create_all()

        admin = db.session.get(User, "admin")
        if not admin:
            admin_password = os.getenv("ADMIN_PASSWORD")
            if not admin_password:
                raise RuntimeError("ADMIN_PASSWORD не задано в .env")
            su = User(login="admin", access_right="superuser")
            su.set_password(admin_password)
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
    register_consent_routes(app)
    register_export_routes(app)
    register_anonymization_routes(app)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG") == "1")
