from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import User
from ...security import hash_password


DEMO_USERS = (
    {"id": "U-0001", "username": "asesor", "password": "Asesor#2026", "role": "asesor"},
    {"id": "U-0002", "username": "admin", "password": "Admin#2026", "role": "admin"},
)


def seed_demo(session: Session) -> None:
    """Carga el seed mínimo de S0 sin duplicar usuarios existentes."""
    for demo_user in DEMO_USERS:
        exists = session.scalar(select(User).where(User.username == demo_user["username"]))
        if exists is None:
            session.add(
                User(
                    id=demo_user["id"],
                    username=demo_user["username"],
                    password_hash=hash_password(demo_user["password"]),
                    role=demo_user["role"],
                    person_id=None,
                )
            )
    session.commit()

