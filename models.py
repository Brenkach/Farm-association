from datetime import date, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db


# ---------------- USERS ----------------

class User(db.Model):
    __tablename__ = "users"

    login = db.Column(db.String(50), primary_key=True)
    password_hash = db.Column(db.String(200))  # хеш пароля
    access_right = db.Column(db.String(20), nullable=False)
    farm_id = db.Column(db.Integer, db.ForeignKey("farms.farm_id"))

    # зв’язок з господарством
    farm = db.relationship("Farm", back_populates="users")

    # методи роботи з паролем
    def set_password(self, raw_password: str):
        self.password_hash = generate_password_hash(raw_password, method='pbkdf2:sha256')

    def check_password(self, raw_password: str) -> bool:
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, raw_password)


# ---------------- SPECIALIZATIONS ----------------

class Specialization(db.Model):
    __tablename__ = "specializations"

    specialization_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), unique=True, nullable=False)

    farms = db.relationship("Farm", back_populates="specialization")
    product_types = db.relationship(
        "ProductType",
        back_populates="specialization",
        cascade="all, delete-orphan",
    )


# ---------------- FARMS ----------------

class Farm(db.Model):
    __tablename__ = "farms"

    farm_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)

    specialization_id = db.Column(
        db.Integer,
        db.ForeignKey("specializations.specialization_id"),
        nullable=False,
    )

    farmer_fullname = db.Column(db.String(200))
    region = db.Column(db.String(100))
    address = db.Column(db.String(255))
    phone = db.Column(db.String(50))

    permit_issued_at = db.Column(db.Date)
    permit_expires_at = db.Column(db.Date)

    # зв’язки
    specialization = db.relationship("Specialization", back_populates="farms")

    users = db.relationship(
        "User",
        back_populates="farm",
        cascade="all, delete-orphan",
    )

    offers = db.relationship(
        "ProductOffer",
        back_populates="farm",
        cascade="all, delete-orphan",
    )

    employees = db.relationship(
        "Employee",
        back_populates="farm",
        cascade="all, delete-orphan",
    )


# ---------------- PRODUCT TYPES ----------------

class ProductType(db.Model):
    __tablename__ = "product_types"

    product_type_id = db.Column(db.Integer, primary_key=True)

    # назва господарства
    name = db.Column(db.String(200), nullable=False)

    # назва продукту
    product_name = db.Column(db.String(200), nullable=False)

    specialization_id = db.Column(
        db.Integer,
        db.ForeignKey("specializations.specialization_id"),
        nullable=False,
    )

    specialization = db.relationship(
        "Specialization",
        back_populates="product_types",
    )

    offers = db.relationship(
        "ProductOffer",
        back_populates="product_type",
        cascade="all, delete-orphan",
    )

    attributes = db.relationship(
        "ProductAttribute",
        back_populates="product_type",
        cascade="all, delete-orphan",
    )
    attributes = db.relationship(
        "ProductAttribute",
        back_populates="product_type",
        cascade="all, delete-orphan",
    )


# ---------------- PRODUCT OFFERS ----------------

class ProductOffer(db.Model):
    __tablename__ = "product_offers"

    offer_id = db.Column(db.Integer, primary_key=True)
    farm_id = db.Column(db.Integer, db.ForeignKey("farms.farm_id"), nullable=False)
    product_type_id = db.Column(
        db.Integer,
        db.ForeignKey("product_types.product_type_id"),
        nullable=False,
    )

    uom = db.Column(db.String(50), nullable=False)
    unit_price = db.Column(db.Float)
    quantity_available = db.Column(db.Float)
    shelf_life_days = db.Column(db.Integer)
    produced_at = db.Column(db.Date, default=date.today, nullable=False)

    note = db.Column(db.Text)

    farm = db.relationship("Farm", back_populates="offers")
    product_type = db.relationship("ProductType", back_populates="offers")

    attribute_values = db.relationship(
        "ProductOfferValue",
        back_populates="offer",
        cascade="all, delete-orphan",
    )

    @property
    def total_value(self):
        if self.unit_price is not None and self.quantity_available is not None:
            return self.unit_price * self.quantity_available
        return None

    @property
    def best_before(self):
        if self.produced_at and self.shelf_life_days:
            return self.produced_at + timedelta(days=self.shelf_life_days)
        return None


# ---------------- EMPLOYEES ----------------

class Employee(db.Model):
    __tablename__ = "employees"

    employee_id = db.Column(db.Integer, primary_key=True)
    farm_id = db.Column(db.Integer, db.ForeignKey("farms.farm_id"), nullable=False)

    full_name = db.Column(db.String(200), nullable=False)
    position = db.Column(db.String(100), nullable=False)
    hire_date = db.Column(db.Date, nullable=False)
    monthly_salary = db.Column(db.Float)
    address = db.Column(db.String(255))
    phone = db.Column(db.String(50))

    # FK → users.login
    user_login = db.Column(db.String(50), db.ForeignKey("users.login"))

    user = db.relationship("User", backref="employee")
    farm = db.relationship("Farm", back_populates="employees")


# ---------------- PRODUCT ATTRIBUTES ----------------

# ---------------- PRODUCT ATTRIBUTES ----------------

class ProductAttribute(db.Model):
    __tablename__ = "product_attributes"

    attribute_id = db.Column(db.Integer, primary_key=True)

    # FK → product_types.product_type_id
    product_type_id = db.Column(
        db.Integer,
        db.ForeignKey("product_types.product_type_id"),
        nullable=False
    )

    # Назва атрибута (Колір / Вага)
    attribute_name = db.Column(db.String(255), nullable=False)

    # Значення атрибута (Жовтий / 12 кг)
    attribute_value = db.Column(db.String(255), nullable=False)

    # Зв’язок із ProductType
    product_type = db.relationship("ProductType", back_populates="attributes")


# ---------------- PRODUCT OFFER VALUES ----------------

class ProductOfferValue(db.Model):
    __tablename__ = "product_offer_values"

    id = db.Column(db.Integer, primary_key=True)
    offer_id = db.Column(
        db.Integer,
        db.ForeignKey("product_offers.offer_id"),
        nullable=False,
    )
    attribute_id = db.Column(
        db.Integer,
        db.ForeignKey("product_attributes.attribute_id"),
        nullable=False,
    )

    value = db.Column(db.String(255), nullable=False)

    offer = db.relationship("ProductOffer", back_populates="attribute_values")
    attribute = db.relationship("ProductAttribute")
