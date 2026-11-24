import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from ...config import BACKEND_DIR, settings
from ...db import Base, engine
from .seed import demo_day, demo_report, seed_demo

REPORT_PATH = BACKEND_DIR.parent / "docs" / "DEMO_DATA.md"


def reset_database(report_path: Path | None = None) -> None:
    """Reconstruye la base y publica el inventario de la misma ejecución."""
    anchor = demo_day()
    with engine.begin() as connection:
        if connection.dialect.name == "sqlite":
            connection.execute(text("BEGIN IMMEDIATE"))
        Base.metadata.drop_all(bind=connection)
        Base.metadata.create_all(bind=connection)
        with Session(bind=connection, autoflush=False) as session:
            seed_demo(session, anchor)
            session.flush()
    report_path = report_path if report_path is not None else REPORT_PATH
    body = demo_report(anchor)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(body, encoding="utf-8")
    print(body)


def main() -> int:
    if not settings.demo_mode:
        print("Activa DEMO_MODE=true para reconstruir la base de demo.", file=sys.stderr)
        return 1
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    reset_database()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
