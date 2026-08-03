def seed_admin():
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.email == settings.admin_email).first()

        if admin is None:
            admin = User(
                email=settings.admin_email,
                name="관리자",
                password_hash=hash_password(settings.admin_password),
            )
            db.add(admin)
        else:
            admin.password_hash = hash_password(settings.admin_password)

        db.commit()
    finally:
        db.close()
