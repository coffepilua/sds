"""Демо-данные (вымышленные). Запуск: python -m app.seed"""
from sqlalchemy import func, select

from .core import SessionLocal, engine, hash_pw
from .models import *  # noqa: F403

PW = "Demo12345!"
SPECS = [("Кардиология", "cardiology"), ("Онкология", "oncology"), ("Ортопедия", "orthopedics"),
         ("Офтальмология", "ophthalmology"), ("Урология", "urology")]
CLINICS = [  # name, country, city, specialties, cloud key, status
    ("Demo Clinic Delhi", "India", "New Delhi", ["cardiology", "oncology", "orthopedics"], "clinics/demo-delhi.jpg", "verified"),
    ("Demo Clinic Gurugram", "India", "Gurugram", ["cardiology", "urology"], "clinics/demo-gurugram.jpg", "verified"),
    ("Demo Clinic Istanbul", "Turkey", "Istanbul", ["oncology", "ophthalmology", "orthopedics"], "clinics/demo-istanbul.jpg", "verified"),
    ("Demo Clinic Ankara", "Turkey", "Ankara", ["cardiology", "ophthalmology"], "clinics/demo-ankara.jpg", "verified"),
    ("Demo Clinic Izmir", "Turkey", "Izmir", ["urology"], "clinics/demo-izmir.jpg", "pending"),
]


def run():
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if db.scalar(select(func.count(User.id))):
            return
        spec = {}
        for n, s in SPECS:
            spec[s] = Specialty(name=n, slug=s)
            db.add(spec[s])
        cl = []
        for n, country, city, ss, img, st in CLINICS:
            c = Clinic(name=n, country=country, city=city, verification_status=st,
                       description="Тестовая карточка для демонстрации. Не реальная клиника.")
            db.add(c)
            db.flush()
            db.add(ClinicImage(clinic_id=c.id, url=img))
            db.add_all(ClinicSpecialty(clinic_id=c.id, specialty_id=spec[s].id) for s in ss)
            cl.append(c)
        users = {}
        for key, email, name, role in [("admin", "admin@demo.test", "Админ Демо", "admin"),
                                       ("coord", "coord@demo.test", "Координатор Демо", "coordinator"),
                                       ("patient", "patient@demo.test", "Алина Тестовая", "patient"),
                                       ("clinic1", "clinic1@demo.test", "Клиника Дели (демо)", "clinic"),
                                       ("clinic2", "clinic2@demo.test", "Клиника Стамбул (демо)", "clinic")]:
            users[key] = User(email=email, password_hash=hash_pw(PW), full_name=name, phone="+996000000000", role=role)
            db.add(users[key])
        db.flush()
        db.add(ClinicMembership(user_id=users["clinic1"].id, clinic_id=cl[0].id))
        db.add(ClinicMembership(user_id=users["clinic2"].id, clinic_id=cl[2].id))
        db.commit()


if __name__ == "__main__":
    run()
    print("Готово. Демо-пароль для всех: ", PW)
