from datetime import date, timedelta
import json

from sqlalchemy import func

from flask import request, redirect, url_for, render_template, session

from extensions import db, require_roles
from models import (
    User,
    Specialization,
    Farm,
    ProductType,
    ProductOffer,
    Employee,
    ProductAttribute,
    ProductOfferValue,
)


def register_routes(app):
    # --- Manual
    @app.route("/manual")
    def manual():
        return render_template("manual.html")

    # ---------------- AUTH ----------------

    @app.route("/login", methods=["GET", "POST"])
    def login():
        msg = None

        if request.method == "POST":
            login_val = request.form.get("login", "").strip()
            password = request.form.get("password", "")

            user = User.query.get(login_val)

            if user and user.check_password(password):
                session["login"] = user.login
                session["access_right"] = user.access_right
                session["farm_id"] = user.farm_id
                return redirect(url_for("index"))
            else:
                msg = "Невірний логін або пароль"

        return render_template("login.html", msg=msg)

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/forbidden")
    def forbidden():
        return "У вас недостатньо прав доступу", 403

    # ---------------- Registration (фермер) ----------------

    @app.route("/register", methods=["GET", "POST"])
    def register():
        msg = None

        specs = Specialization.query.order_by(Specialization.name).all()

        if request.method == "POST":
            login_val = request.form.get("login", "").strip()
            password = request.form.get("password", "")
            confirm = request.form.get("confirm", "")

            farm_name = request.form.get("farm_name")
            specialization_id = request.form.get("specialization_id", type=int)
            farmer_fullname = request.form.get("farmer_fullname")
            region = request.form.get("region")
            address = request.form.get("address")
            phone = request.form.get("phone")
            permit_issued = request.form.get("permit_issued_at")
            permit_expires = request.form.get("permit_expires_at")

            if not login_val or not password or not farm_name or not specialization_id:
                msg = "Усі поля обов'язкові."
            elif password != confirm:
                msg = "Паролі не співпадають."
            elif User.query.filter_by(login=login_val).first():
                msg = "Такий логін уже існує."
            elif not permit_issued or not permit_expires:
                msg = "Поля дат дозволу є обов'язковими."
            else:
                try:
                    issued_dt = date.fromisoformat(permit_issued)
                    expires_dt = date.fromisoformat(permit_expires)

                    if expires_dt < issued_dt:
                        msg = "Дата завершення дозволу не може бути раніше дати видачі!"
                    else:
                        farm = Farm(
                            name=farm_name,
                            specialization_id=specialization_id,
                            farmer_fullname=farmer_fullname,
                            region=region,
                            address=address,
                            phone=phone,
                            permit_issued_at=issued_dt,
                            permit_expires_at=expires_dt,
                        )
                        db.session.add(farm)
                        db.session.flush()

                        user = User(
                            login=login_val,
                            access_right="farmer",
                            farm_id=farm.farm_id,
                        )
                        user.set_password(password)

                        db.session.add(user)
                        db.session.commit()

                        session["login"] = user.login
                        session["access_right"] = user.access_right
                        session["farm_id"] = user.farm_id

                        return redirect(url_for("index"))

                except Exception as e:
                    db.session.rollback()
                    msg = f"Помилка під час реєстрації: {e}"

        return render_template("register.html", msg=msg, specs=specs)

    # ---------------- Reset password ----------------

    @app.route("/reset-password", methods=["GET", "POST"])
    def reset_password():
        msg = None
        success = None

        if request.method == "POST":
            login_val = request.form.get("login", "").strip()
            new_password = request.form.get("password", "")
            confirm = request.form.get("confirm", "")

            user = User.query.get(login_val)
            if not user:
                msg = "Користувача з таким логіном не знайдено"
            elif not new_password:
                msg = "Пароль не може бути порожнім"
            elif new_password != confirm:
                msg = "Паролі не співпадають"
            else:
                user.set_password(new_password)
                db.session.commit()
                success = "Пароль успішно змінено. Можете увійти."

        return render_template("reset_password.html", msg=msg, success=success)

    # ---------------- INDEX ----------------

    @app.route("/")
    def index():
        if "login" not in session:
            return redirect(url_for("login"))
        return redirect(url_for("farms"))

    # ---------------- FARMS ----------------

    @app.route("/farms", methods=["GET", "POST"])
    @require_roles("superuser", "farmer", "worker")
    def farms():
        role = session.get("access_right")
        msg = None

        if request.method == "POST":
            # створювати господарства може лише суперюзер
            if role != "superuser":
                return redirect(url_for("forbidden"))

            permit_issued = request.form.get("permit_issued_at")
            permit_expires = request.form.get("permit_expires_at")
            phone_val = request.form.get("phone", "").strip()

            if not permit_issued or not permit_expires:
                msg = "Поля дат дозволу є обов'язковими!"
            else:
                if phone_val and (len(phone_val) < 9 or len(phone_val) > 15):
                    msg = "Телефон повинен містити лише цифри (9–15 символів)."

                if not msg:
                    issued_dt = date.fromisoformat(permit_issued)
                    expires_dt = date.fromisoformat(permit_expires)

                    if expires_dt < issued_dt:
                        msg = "Дата завершення дозволу не може бути раніше дати видачі!"

                if not msg:
                    try:
                        f = Farm(
                            name=request.form["name"],
                            specialization_id=int(request.form["specialization_id"]),
                            farmer_fullname=request.form.get("farmer_fullname"),
                            region=request.form.get("region"),
                            address=request.form.get("address"),
                            phone=phone_val,
                            permit_issued_at=issued_dt,
                            permit_expires_at=expires_dt,
                        )
                        db.session.add(f)
                        db.session.commit()
                        return redirect(url_for("farms"))
                    except Exception as e:
                        db.session.rollback()
                        msg = f"Помилка збереження: {e}"

        specs = Specialization.query.order_by(Specialization.name).all()
        today = date.today()
        cutoff = today + timedelta(days=90)

        q = Farm.query

        if request.args.get("filter") == "expiring":
            q = q.filter(
                Farm.permit_expires_at.isnot(None),
                Farm.permit_expires_at >= today,
                Farm.permit_expires_at <= cutoff,
            )

        farms_list = q.order_by(Farm.farm_id.desc()).all()

        total_count = Farm.query.count()
        expiring_count = Farm.query.filter(
            Farm.permit_expires_at.isnot(None),
            Farm.permit_expires_at >= today,
            Farm.permit_expires_at <= cutoff,
        ).count()

        return render_template(
            "farms.html",
            farms=farms_list,
            specs=specs,
            total_count=total_count,
            expiring_count=expiring_count,
            today=today,
            cutoff=cutoff,
            msg=msg,
        )

    # ---------------- EDIT FARM ----------------

    @app.route("/farms/<int:farm_id>/edit", methods=["GET", "POST"])
    @require_roles("superuser", "farmer")
    def edit_farm(farm_id):
        f = Farm.query.get_or_404(farm_id)
        role = session.get("access_right")
        user_farm_id = session.get("farm_id")
        msg = None

        # фермер може редагувати тільки своє господарство
        if role == "farmer" and user_farm_id != f.farm_id:
            return redirect(url_for("forbidden"))

        specs = Specialization.query.order_by(Specialization.name).all()

        if request.method == "POST":
            permit_issued = request.form.get("permit_issued_at")
            permit_expires = request.form.get("permit_expires_at")
            phone_val = request.form.get("phone", "").strip()

            if not permit_issued or not permit_expires:
                msg = "Поля дат дозволу є обов'язковими!"
            else:
                if phone_val and (len(phone_val) < 9 or len(phone_val) > 15):
                    msg = "Телефон повинен містити лише цифри (9–15 символів)."

                if not msg:
                    issued_dt = date.fromisoformat(permit_issued)
                    expires_dt = date.fromisoformat(permit_expires)

                    if expires_dt < issued_dt:
                        msg = "Дата завершення дозволу не може бути раніше дати видачі!"

                if not msg:
                    try:
                        f.name = request.form["name"]
                        f.specialization_id = int(request.form["specialization_id"])
                        f.farmer_fullname = request.form.get("farmer_fullname")
                        f.region = request.form.get("region")
                        f.address = request.form.get("address")
                        f.phone = phone_val
                        f.permit_issued_at = issued_dt
                        f.permit_expires_at = expires_dt

                        db.session.commit()
                        return redirect(url_for("farms"))
                    except Exception as e:
                        db.session.rollback()
                        msg = f"Помилка оновлення: {e}"

        return render_template("farm_edit.html", f=f, specs=specs, msg=msg)

    # ---------------- DELETE FARM ----------------

    @app.get("/farms/<int:farm_id>/delete")
    @require_roles("superuser")
    def delete_farm(farm_id):
        f = Farm.query.get_or_404(farm_id)
        try:
            db.session.delete(f)
            db.session.commit()
            return redirect(url_for("farms"))
        except Exception as e:
            db.session.rollback()
            return f"Помилка видалення: {e}", 500

    # ======================================================================
    #                      PRODUCT TYPES + ATTRIBUTES
    # ======================================================================

    @app.route("/product-types", methods=["GET", "POST"])
    @require_roles("superuser", "farmer")
    def product_types():
        role = session.get("access_right")
        user_farm_id = session.get("farm_id")

        from models import ProductType, Farm, Specialization

        specs = Specialization.query.order_by(Specialization.name).all()
        msg = None

        # CREATE
        if request.method == "POST":
            try:
                if role == "superuser":
                    name = request.form.get("name", "").strip()
                    specialization_id = request.form.get("specialization_id", type=int)
                else:
                    farm = Farm.query.get_or_404(user_farm_id)
                    name = farm.name
                    specialization_id = farm.specialization_id

                product_name = request.form.get("product_name", "").strip()

                if not name or not specialization_id or not product_name:
                    msg = "Усі поля обов'язкові!"
                else:
                    new_pt = ProductType(
                        name=name,
                        specialization_id=specialization_id,
                        product_name=product_name
                    )
                    db.session.add(new_pt)
                    db.session.commit()
                    return redirect(url_for("product_types"))

            except Exception as e:
                db.session.rollback()
                msg = f"Помилка створення: {e}"

        # LIST
        if role == "superuser":
            items = ProductType.query.order_by(ProductType.product_type_id).all()
        else:
            farm = Farm.query.get_or_404(user_farm_id)
            items = ProductType.query.filter_by(name=farm.name).all()

        return render_template(
            "product_types.html",
            items=items,
            specs=specs,
            msg=msg,
            role=role
        )



    # ======================================================================
    #                   ATTRIBUTES — ONLY COLOR + WEIGHT
    # ======================================================================

    @app.route("/product-types/<int:product_type_id>/attributes", methods=["GET", "POST"])
    @require_roles("superuser", "farmer")
    def product_type_attributes(product_type_id):
        from models import ProductType, ProductAttribute, Farm

        pt = ProductType.query.get_or_404(product_type_id)
        role = session.get("access_right")
        user_farm_id = session.get("farm_id")

        msg = None

        # фермер має доступ тільки до своїх product type
        if role == "farmer":
            farm = Farm.query.get_or_404(user_farm_id)
            if pt.name != farm.name:
                return redirect(url_for("forbidden"))

        # CREATE ATTRIBUTE
        if request.method == "POST":
            color = request.form.get("color", "").strip()
            weight = request.form.get("weight", "").strip()

            if not color and not weight:
                msg = "Введіть хоча б одне поле!"
            else:
                try:
                    if color:
                        db.session.add(ProductAttribute(
                            product_type_id=product_type_id,
                            attribute_name="Колір",
                            attribute_value=color
                        ))

                    if weight:
                        db.session.add(ProductAttribute(
                            product_type_id=product_type_id,
                            attribute_name="Вага",
                            attribute_value=weight
                        ))

                    db.session.commit()
                    return redirect(url_for("product_type_attributes", product_type_id=product_type_id))

                except Exception as e:
                    db.session.rollback()
                    msg = f"Помилка: {e}"

        attrs = ProductAttribute.query.filter_by(product_type_id=product_type_id).all()

        return render_template(
            "product_type_attributes.html",
            pt=pt,
            attrs=attrs,
            msg=msg
        )

    # ======================================================================
    #                  EDIT PRODUCT TYPE  (ПОВНІСТЮ РОБОЧИЙ)
    # ======================================================================

    @app.route("/product-types/<int:product_type_id>/edit", methods=["GET", "POST"])
    @require_roles("superuser", "farmer")
    def edit_product_type(product_type_id):
        from models import ProductType, Specialization, Farm

        pt = ProductType.query.get_or_404(product_type_id)

        role = session.get("access_right")
        user_farm_id = session.get("farm_id")
        msg = None

        # фермер може редагувати лише свої
        if role == "farmer":
            farm = Farm.query.get_or_404(user_farm_id)
            if pt.name != farm.name:
                return redirect(url_for("forbidden"))

        specs = Specialization.query.order_by(Specialization.name).all()

        if request.method == "POST":
            try:
                if role == "superuser":
                    pt.name = request.form.get("name", "").strip()
                    pt.specialization_id = request.form.get("specialization_id", type=int)

                pt.product_name = request.form.get("product_name", "").strip()

                db.session.commit()
                return redirect(url_for("product_types"))

            except Exception as e:
                db.session.rollback()
                msg = f"Помилка оновлення: {e}"

        return render_template(
            "product_type_edit.html",
            pt=pt,
            specs=specs,
            role=role,
            msg=msg
        )

    # ======================================================================
    #                  DELETE PRODUCT TYPE (ПОВНІСТЮ РОБОЧИЙ)
    # ======================================================================

    @app.get("/product-types/<int:product_type_id>/delete")
    @require_roles("superuser", "farmer")
    def delete_product_type(product_type_id):
        from models import ProductType, Farm

        pt = ProductType.query.get_or_404(product_type_id)

        role = session.get("access_right")
        user_farm_id = session.get("farm_id")

        # фермер може видаляти лише свої типи продукції
        if role == "farmer":
            farm = Farm.query.get_or_404(user_farm_id)
            if pt.name != farm.name:
                return redirect(url_for("forbidden"))

        try:
            db.session.delete(pt)
            db.session.commit()
            return redirect(url_for("product_types"))
        except Exception as e:
            db.session.rollback()
            return f"Помилка видалення: {e}", 500

    # ======================================================================
    #                      DELETE ATTRIBUTE
    # ======================================================================

    @app.get("/attribute/<int:attribute_id>/delete")
    @require_roles("superuser", "farmer")
    def delete_attribute(attribute_id):
        from models import ProductAttribute, ProductType, Farm

        attr = ProductAttribute.query.get_or_404(attribute_id)
        pt = ProductType.query.get(attr.product_type_id)

        role = session.get("access_right")
        user_farm_id = session.get("farm_id")

        if role == "farmer":
            farm = Farm.query.get_or_404(user_farm_id)
            if pt.name != farm.name:
                return redirect(url_for("forbidden"))

        try:
            db.session.delete(attr)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return f"Помилка: {e}", 500

        return redirect(url_for("product_type_attributes", product_type_id=pt.product_type_id))

    # ---------------- OFFERS ----------------

    @app.route("/offers", methods=["GET", "POST"])
    @require_roles("superuser", "farmer", "worker")
    def offers():
        role = session.get("access_right")
        user_farm_id = session.get("farm_id")

        msg = None

        farms = Farm.query.order_by(Farm.name).all()
        specializations = Specialization.query.order_by(Specialization.name).all()

        current_farm = None
        if role in ("farmer", "worker") and user_farm_id:
            current_farm = Farm.query.get(user_farm_id)

        # спец для відкриття форми "Нова пропозиція"
        spec_id_add = request.args.get("spec_id_add", type=int)
        if request.method == "POST" and not spec_id_add:
            spec_id_add = request.form.get("specialization_id", type=int)

        # фермер може додавати лише в свою спец
        if role == "farmer" and current_farm and spec_id_add:
            if spec_id_add != current_farm.specialization_id:
                msg = "Ви не можете створювати пропозиції у чужій спеціалізації."
                spec_id_add = None

        # ---------- ДОДАВАННЯ ПРОПОЗИЦІЇ ----------
        if request.method == "POST" and spec_id_add:
            if role == "worker":
                return redirect(url_for("forbidden"))

            if role == "farmer":
                farm_id = user_farm_id
            else:
                farm_id = request.form.get("farm_id", type=int)

            spec_id = request.form.get("specialization_id", type=int)
            product_name = (request.form.get("product_name") or "").strip()
            uom = (request.form.get("uom") or "").strip()
            unit_price = request.form.get("unit_price", type=float)
            quantity = request.form.get("quantity_available", type=float)
            shelf_life = request.form.get("shelf_life_days", type=int)
            produced_at_str = request.form.get("produced_at")
            note = (request.form.get("note") or "").strip()

            # валідація
            if not farm_id:
                msg = "Оберіть господарство."
            elif not spec_id:
                msg = "Не вказано спеціалізацію."
            elif (
                role == "farmer"
                and current_farm
                and spec_id != current_farm.specialization_id
            ):
                msg = "Ви не можете створювати пропозиції у чужій спеціалізації."
            elif not product_name:
                msg = "Поле «Продукт» є обов'язковим."
            elif not uom:
                msg = "Одиниця виміру є обов'язковою."
            elif not produced_at_str:
                msg = "Дата виробництва є обов'язковою."
            elif unit_price is not None and unit_price < 0:
                msg = "Ціна не може бути від'ємною."
            elif quantity is not None and quantity < 0:
                msg = "Кількість не може бути від'ємною."
            elif shelf_life is not None and shelf_life < 0:
                msg = "Термін зберігання не може бути від'ємним."

            produced_at = None

            if not msg:
                try:
                    produced_at = date.fromisoformat(produced_at_str)
                except ValueError:
                    msg = "Некоректна дата виробництва."

            if not msg:
                farm_obj = Farm.query.get(farm_id)
                if not farm_obj:
                    msg = "Обране господарство не знайдене."

            if not msg:
                try:
                    # автоматичне створення ProductType (за господарством)
                    pt = (
                        ProductType.query.filter_by(
                            name=farm_obj.name,
                            specialization_id=farm_obj.specialization_id,
                            product_name=product_name,
                        )
                        .first()
                    )

                    if not pt:
                        pt = ProductType(
                            name=farm_obj.name,
                            specialization_id=farm_obj.specialization_id,
                            product_name=product_name,
                        )
                        db.session.add(pt)
                        db.session.flush()

                    offer = ProductOffer(
                        farm_id=farm_id,
                        product_type_id=pt.product_type_id,
                        uom=uom,
                        unit_price=unit_price,
                        quantity_available=quantity,
                        shelf_life_days=shelf_life,
                        produced_at=produced_at,
                        note=note,
                    )
                    db.session.add(offer)
                    db.session.flush()  # важливо: отримати offer_id

                    # ===================================================
                    #  ЗБЕРЕЖЕННЯ ДОДАТКОВИХ АТРИБУТІВ
                    # ===================================================
                    attrs = ProductAttribute.query.filter_by(
                        product_type_id=pt.product_type_id
                    ).all()

                    for attr in attrs:
                        form_key = f"attr_{attr.attribute_id}"
                        value = request.form.get(form_key)

                        if value and value.strip() != "":
                            offer_attr = ProductOfferValue(
                                offer_id=offer.offer_id,
                                attribute_id=attr.attribute_id,
                                value=value.strip(),
                            )
                            db.session.add(offer_attr)
                    # ===================================================

                    db.session.commit()
                    return redirect(url_for("offers"))

                except Exception as e:
                    db.session.rollback()
                    msg = f"Помилка збереження: {e}"

        # -------- ФІЛЬТРИ --------

        filter_spec_raw = request.args.get("specialization_id")
        filter_farm_raw = request.args.get("farm_id")

        filter_spec = (
            int(filter_spec_raw)
            if (filter_spec_raw and filter_spec_raw.isdigit())
            else None
        )
        filter_farm = (
            int(filter_farm_raw)
            if (filter_farm_raw and filter_farm_raw.isdigit())
            else None
        )

        q = ProductOffer.query.join(Farm).join(ProductType)

        if role == "worker":
            q = q.filter(ProductOffer.farm_id == user_farm_id)

        if filter_spec is not None:
            q = q.filter(ProductType.specialization_id == filter_spec)

        if filter_farm is not None:
            q = q.filter(ProductOffer.farm_id == filter_farm)

        items = q.order_by(ProductOffer.offer_id.desc()).all()

        return render_template(
            "offers.html",
            role=role,
            farms=farms,
            specializations=specializations,
            items=items,
            msg=msg,
            spec_id_add=spec_id_add,
            current_farm=current_farm,
            user_farm_id=user_farm_id,
            filter_spec=filter_spec,
            filter_farm=filter_farm,
        )

    # ---------------- DELETE OFFER ----------------

    @app.get("/offers/<int:offer_id>/delete")
    @require_roles("superuser", "farmer")
    def delete_offer(offer_id):
        role = session.get("access_right")
        user_farm_id = session.get("farm_id")

        off = ProductOffer.query.get_or_404(offer_id)

        # фермер може видалити тільки свої пропозиції
        if role == "farmer" and off.farm_id != user_farm_id:
            return redirect(url_for("forbidden"))

        try:
            db.session.delete(off)
            db.session.commit()
            return redirect(url_for("offers"))
        except Exception as e:
            db.session.rollback()
            return f"Помилка видалення: {e}", 500

    # ---------------- EDIT OFFER ----------------
    @app.route("/offers/<int:offer_id>/edit", methods=["GET", "POST"])
    @require_roles("superuser", "farmer")
    def edit_offer(offer_id):
        role = session.get("access_right")
        user_farm_id = session.get("farm_id")

        offer = ProductOffer.query.get_or_404(offer_id)

        # фермер може редагувати лише свої
        if role == "farmer" and offer.farm_id != user_farm_id:
            return redirect(url_for("forbidden"))

        msg = None

        if request.method == "POST":
            try:
                offer.uom = request.form.get("uom")
                offer.unit_price = request.form.get("unit_price", type=float)
                offer.quantity_available = request.form.get(
                    "quantity_available", type=float
                )
                offer.shelf_life_days = request.form.get(
                    "shelf_life_days", type=int
                )
                offer.note = request.form.get("note")

                produced_at = request.form.get("produced_at")
                if produced_at:
                    offer.produced_at = date.fromisoformat(produced_at)

                # (за бажанням можна додати тут оновлення додаткових атрибутів)

                db.session.commit()
                return redirect(url_for("offers"))

            except Exception as e:
                db.session.rollback()
                msg = f"Помилка: {e}"

        return render_template("offer_edit.html", offer=offer, role=role, msg=msg)

    # ---------------- EMPLOYEES ----------------
    @app.route("/employees", methods=["GET", "POST"])
    @require_roles("superuser", "farmer")
    def employees():
        role = session.get("access_right")
        current_farm_id = session.get("farm_id")

        farms = Farm.query.order_by(Farm.name).all()
        msg = None

        # ---------- POST: створення працівника ----------
        if request.method == "POST":

            farm_id = (
                request.form.get("farm_id")
                if role == "superuser"
                else current_farm_id
            )

            full_name = request.form.get("full_name")
            position = request.form.get("position")
            hire_date_str = request.form.get("hire_date")
            monthly_salary_str = request.form.get("monthly_salary")
            address = request.form.get("address")
            phone = request.form.get("phone")

            login = request.form.get("account_login")
            password = request.form.get("account_password")

            try:
                hire_date = (
                    date.fromisoformat(hire_date_str)
                    if hire_date_str
                    else None
                )
                monthly_salary = (
                    float(monthly_salary_str) if monthly_salary_str else None
                )

                # створення User
                new_user = User(
                    login=login,
                    access_right="worker",
                    farm_id=farm_id,
                )
                new_user.set_password(password)
                db.session.add(new_user)

                # працівник
                emp = Employee(
                    farm_id=farm_id,
                    full_name=full_name,
                    position=position,
                    hire_date=hire_date,
                    monthly_salary=monthly_salary,
                    address=address,
                    phone=phone,
                    user_login=login,
                )
                db.session.add(emp)

                db.session.commit()

                return render_template(
                    "employees.html",
                    farms=farms,
                    items=Employee.query.filter(
                        Employee.farm_id == farm_id
                    ).all(),
                    new_worker=emp,
                    new_password=password,
                    role=role,
                    filter_farm=farm_id,
                    current_farm=Farm.query.get(current_farm_id),
                )

            except Exception as e:
                db.session.rollback()
                msg = f"Помилка: {e}"

        # ---------- GET ----------
        filter_farm = request.args.get("farm_id", type=int)

        # фермер завжди бачить тільки своє господарство
        if role == "farmer":
            filter_farm = current_farm_id

        if filter_farm:
            items = Employee.query.filter(Employee.farm_id == filter_farm).all()
        else:
            items = Employee.query.all()

        return render_template(
            "employees.html",
            farms=farms,
            items=items,
            msg=msg,
            role=role,
            filter_farm=filter_farm,
            current_farm=Farm.query.get(current_farm_id),
        )

    # ---------------- EDIT EMPLOYEE ----------------
    @app.route("/employees/<int:employee_id>/edit", methods=["GET", "POST"])
    @require_roles("superuser", "farmer")
    def edit_employee(employee_id):
        role = session.get("access_right")
        current_farm_id = session.get("farm_id")

        emp = Employee.query.get_or_404(employee_id)

        # фермер може редагувати лише своїх працівників
        if role == "farmer" and emp.farm_id != current_farm_id:
            return redirect(url_for("forbidden"))

        msg = None

        if request.method == "POST":
            full_name = request.form.get("full_name")
            position = request.form.get("position")
            hire_date_str = request.form.get("hire_date")
            monthly_salary_str = request.form.get("monthly_salary")
            address = request.form.get("address")
            phone = request.form.get("phone")

            try:
                emp.full_name = full_name
                emp.position = position
                emp.address = address
                emp.phone = phone

                if hire_date_str:
                    emp.hire_date = date.fromisoformat(hire_date_str)

                if monthly_salary_str:
                    emp.monthly_salary = float(monthly_salary_str)
                else:
                    emp.monthly_salary = None

                db.session.commit()
                return redirect(url_for("employees"))

            except Exception as e:
                db.session.rollback()
                msg = f"Помилка: {e}"

        return render_template(
            "employee_edit.html",
            emp=emp,
            role=role,
            msg=msg,
        )

    # ---------------- DELETE EMPLOYEE ----------------
    @app.get("/employees/<int:employee_id>/delete")
    @require_roles("superuser", "farmer")
    def delete_employee(employee_id):
        role = session.get("access_right")
        current_farm_id = session.get("farm_id")

        emp = Employee.query.get_or_404(employee_id)

        if role == "farmer" and emp.farm_id != current_farm_id:
            return redirect(url_for("forbidden"))

        try:
            user = emp.user
            db.session.delete(emp)
            if user:
                db.session.delete(user)

            db.session.commit()
            return redirect(url_for("employees"))

        except Exception as e:
            db.session.rollback()
            return f"Помилка видалення: {e}", 500

    # ---------------- REPORTS DASHBOARD ----------------
    @app.get("/reports/producers")
    @require_roles("superuser", "farmer", "worker")
    def report_producers():
        role = session.get("access_right")
        user_farm_id = session.get("farm_id")

        # ---- БАЗОВІ ДОВІДНИКИ ----
        specs = Specialization.query.order_by(Specialization.name).all()

        farms_q = Farm.query.order_by(Farm.name)

        # фермер і працівник в довіднику ферм для форм бачать лише своє
        if role in ("farmer", "worker") and user_farm_id:
            farms_q = farms_q.filter(Farm.farm_id == user_farm_id)

        farms = farms_q.all()
        ptypes = ProductType.query.order_by(ProductType.product_name).all()

        # активна вкладка
        active_tab = request.args.get("tab", "q1")

        # ================== Q1 ==================
        q1_product_type_id = request.args.get("q1_product_type_id", type=int)
        q1_rows = []

        if q1_product_type_id:
            q = (
                db.session.query(Farm, ProductOffer, ProductType)
                .join(ProductOffer, ProductOffer.farm_id == Farm.farm_id)
                .join(
                    ProductType,
                    ProductOffer.product_type_id
                    == ProductType.product_type_id,
                )
                .filter(ProductOffer.product_type_id == q1_product_type_id)
            )

            # працівник бачить тільки своє
            if role == "worker" and user_farm_id:
                q = q.filter(Farm.farm_id == user_farm_id)

            # фермер, згідно початкової постановки, бачить усіх виробників для аналізу
            q1_rows = q.order_by(Farm.name).all()

        # ================== Q2 ==================
        today = date.today()
        cutoff_90 = today + timedelta(days=90)

        q2_farms_raw = (
            Farm.query.filter(
                Farm.permit_expires_at.isnot(None),
                Farm.permit_expires_at >= today,
                Farm.permit_expires_at <= cutoff_90,
            )
            .order_by(Farm.permit_expires_at)
            .all()
        )

        # працівник/фермер — тільки своє в звіті по дозволах
        if role in ("farmer", "worker") and user_farm_id:
            q2_farms = [f for f in q2_farms_raw if f.farm_id == user_farm_id]
        else:
            q2_farms = q2_farms_raw

        # ================== Q3 ==================
        q3_spec_id = request.args.get("q3_specialization_id", type=int)
        q3_farms = []

        if q3_spec_id:
            q = Farm.query.filter(Farm.specialization_id == q3_spec_id)

            if role == "worker" and user_farm_id:
                q = q.filter(Farm.farm_id == user_farm_id)

            # фермер для аналітики може бачити всі господарства обраної спец
            q3_farms = q.order_by(Farm.name).all()

        # ================== Q4 ==================
        q4_farm_id = request.args.get("q4_farm_id", type=int)
        q4_farm = None
        q4_offers = []

        if q4_farm_id:
            q4_farm = Farm.query.get(q4_farm_id)

            if q4_farm:
                q = (
                    db.session.query(ProductOffer, ProductType)
                    .join(
                        ProductType,
                        ProductOffer.product_type_id
                        == ProductType.product_type_id,
                    )
                    .filter(ProductOffer.farm_id == q4_farm_id)
                )

                if role == "worker" and user_farm_id:
                    q = q.filter(ProductOffer.farm_id == user_farm_id)

                q4_offers = q.order_by(ProductOffer.produced_at.desc()).all()

        # ================== Q5 ==================
        q5_product_type_id = request.args.get("q5_product_type_id", type=int)
        q5_rows = []
        q5_agg = None

        if q5_product_type_id:
            base = (
                db.session.query(Farm, ProductOffer, ProductType)
                .join(ProductOffer, ProductOffer.farm_id == Farm.farm_id)
                .join(
                    ProductType,
                    ProductOffer.product_type_id
                    == ProductType.product_type_id,
                )
                .filter(ProductOffer.product_type_id == q5_product_type_id)
            )

            # ---- worker → обмежуємо ----
            if role == "worker" and user_farm_id:
                base = base.filter(Farm.farm_id == user_farm_id)

            # ---- farmer → НЕ обмежуємо ----
            # (нічого не робимо, фермер бачить всі господарства)

            q5_rows = base.order_by(Farm.name).all()

            # Агрегація
            agg = (
                db.session.query(
                    func.coalesce(
                        func.sum(ProductOffer.quantity_available), 0
                    ).label("total_qty"),
                    func.avg(ProductOffer.unit_price).label("avg_price"),
                    func.coalesce(
                        func.sum(
                            ProductOffer.quantity_available
                            * ProductOffer.unit_price
                        ),
                        0,
                    ).label("total_value"),
                )
                .filter(ProductOffer.product_type_id == q5_product_type_id)
            )

            # ---- worker → обмежуємо ----
            if role == "worker" and user_farm_id:
                agg = (
                    agg.join(Farm, ProductOffer.farm_id == Farm.farm_id)
                    .filter(Farm.farm_id == user_farm_id)
                )

            # ---- farmer → НЕ обмежуємо ----

            q5_agg = agg.one()

        # ================== Q6 ==================
        q6_farm_id = request.args.get("q6_farm_id", type=int)
        q6_rows = []

        # --- ФОРМУЄМО СПИСОК ГОСПОДАРСТВ ДЛЯ SELECT ---
        # фермер і суперюзер бачать усі господарства
        # працівник бачить лише своє господарство
        if role == "worker" and user_farm_id:
            farms_for_q6 = Farm.query.filter(Farm.farm_id == user_farm_id).all()
        else:
            farms_for_q6 = Farm.query.order_by(Farm.name).all()

        # --- ЯКЩО ВИБРАНО ГОСПОДАРСТВО ---
        if q6_farm_id:
            q = (
                db.session.query(ProductType)
                .join(
                    ProductOffer,
                    ProductOffer.product_type_id
                    == ProductType.product_type_id,
                )
                .filter(ProductOffer.farm_id == q6_farm_id)
                .distinct()
            )

            # для worker фільтр повинен НЕ дозволити бачити інші господарства
            if role == "worker" and user_farm_id:
                q = q.filter(ProductOffer.farm_id == user_farm_id)

            q6_rows = q.order_by(ProductType.product_name).all()

        # ================== Q7 ==================
        q7_product_type_id = request.args.get("q7_product_type_id", type=int)
        q7_min_offer = None
        q7_offers_same_price = []

        if q7_product_type_id:
            min_price = (
                db.session.query(func.min(ProductOffer.unit_price))
                .filter(ProductOffer.product_type_id == q7_product_type_id)
                .scalar()
            )

            if min_price is not None:
                q7_offers_same_price = (
                    db.session.query(ProductOffer, Farm, ProductType)
                    .join(Farm, ProductOffer.farm_id == Farm.farm_id)
                    .join(
                        ProductType,
                        ProductOffer.product_type_id
                        == ProductType.product_type_id,
                    )
                    .filter(
                        ProductOffer.product_type_id == q7_product_type_id,
                        ProductOffer.unit_price == min_price,
                    )
                    .all()
                )

                if q7_offers_same_price:
                    q7_min_offer = q7_offers_same_price[0]

        # ================== Q8 ==================
        q8_farm_id = request.args.get("q8_farm_id", type=int)
        q8_employees = []

        if q8_farm_id:
            q = Employee.query.filter(Employee.farm_id == q8_farm_id)

            if role in ("farmer", "worker") and user_farm_id:
                q = q.filter(Employee.farm_id == user_farm_id)

            q8_employees = q.order_by(Employee.full_name).all()

        # ================== Q9 ==================
        base9 = (
            db.session.query(
                Farm.name,
                func.coalesce(
                    func.sum(ProductOffer.quantity_available), 0
                ).label("total_qty"),
                func.coalesce(
                    func.sum(
                        ProductOffer.quantity_available
                        * ProductOffer.unit_price
                    ),
                    0,
                ).label("total_value"),
            )
            .join(ProductOffer, ProductOffer.farm_id == Farm.farm_id)
            .group_by(Farm.name)
        )

        if role == "worker" and user_farm_id:
            base9 = base9.filter(Farm.farm_id == user_farm_id)

        # фермер для рейтингу бачить всі господарства
        q9_rows = base9.order_by(
            func.sum(
                ProductOffer.quantity_available * ProductOffer.unit_price
            ).desc()
        ).all()

        # ================== Q10 ==================
        one_year_ago = today - timedelta(days=365)

        base10 = (
            db.session.query(
                func.date_part("year", ProductOffer.produced_at).label("y"),
                func.date_part("quarter", ProductOffer.produced_at).label(
                    "q"
                ),
                func.sum(
                    ProductOffer.quantity_available * ProductOffer.unit_price
                ).label("total"),
            )
            .filter(ProductOffer.produced_at >= one_year_ago)
            .group_by("y", "q")
            .order_by("y", "q")
        )

        if role == "worker" and user_farm_id:
            base10 = (
                base10.join(Farm, ProductOffer.farm_id == Farm.farm_id)
                .filter(Farm.farm_id == user_farm_id)
            )

        q10_labels = []
        q10_values = []

        for y, q, total in base10.all():
            q10_labels.append(f"Q{int(q)} {int(y)}")
            q10_values.append(float(total or 0))

        # ================== Повертаємо шаблон ==================
        return render_template(
            "report_producers.html",
            role=role,
            specs=specs,
            farms=farms,
            ptypes=ptypes,
            active_tab=active_tab,
            # Q1
            q1_product_type_id=q1_product_type_id,
            q1_rows=q1_rows,
            # Q2
            q2_farms=q2_farms,
            today=today,
            cutoff_90=cutoff_90,
            # Q3
            q3_spec_id=q3_spec_id,
            q3_farms=q3_farms,
            # Q4
            q4_farm_id=q4_farm_id,
            q4_farm=q4_farm,
            q4_offers=q4_offers,
            # Q5
            q5_product_type_id=q5_product_type_id,
            q5_rows=q5_rows,
            q5_agg=q5_agg,
            # Q6
            q6_farm_id=q6_farm_id,
            q6_rows=q6_rows,
            farms_for_q6=farms_for_q6,
            # Q7
            q7_product_type_id=q7_product_type_id,
            q7_min_offer=q7_min_offer,
            q7_offers_same_price=q7_offers_same_price,
            # Q8
            q8_farm_id=q8_farm_id,
            q8_employees=q8_employees,
            # Q9
            q9_rows=q9_rows,
            # Q10
            q10_labels=q10_labels,
            q10_values=q10_values,
        )
