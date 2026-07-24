"""数据库连接、会话和开发环境引导数据。"""
from collections.abc import Generator
from datetime import timedelta

from sqlmodel import Session, SQLModel, create_engine, select

from config import settings
from db.models import Membership, User, Workspace, now_utc

LEGACY_BOOTSTRAP_ADMIN_EMAIL = "admin@futureagent.local"
DEVELOPMENT_BOOTSTRAP_ADMIN_EMAIL = "admin@futureagent.dev"


engine_options: dict = {"pool_pre_ping": True}
if settings.database_url.startswith("sqlite"):
    engine_options["connect_args"] = {"check_same_thread": False}

engine = create_engine(settings.database_url, **engine_options)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    _migrate_legacy_development_admin()
    _seed_development_admin()


def _development_bootstrap_email() -> str:
    """Return a login-compatible development administrator email.

    Older checkouts seeded ``admin@futureagent.local``.  The API deliberately
    validates login addresses using ``EmailStr``, which rejects special-use
    ``.local`` domains, so that account could never sign in through the UI.
    Keep this compatibility shim strictly in development and leave production
    account management to the deployment owner.
    """
    configured = settings.bootstrap_admin_email.lower()
    return DEVELOPMENT_BOOTSTRAP_ADMIN_EMAIL if configured == LEGACY_BOOTSTRAP_ADMIN_EMAIL else configured


def _migrate_legacy_development_admin() -> None:
    """Repair only the legacy local bootstrap account, never production data."""
    if settings.environment.lower() == "production":
        return
    with Session(engine) as session:
        legacy = session.exec(select(User).where(User.email == LEGACY_BOOTSTRAP_ADMIN_EMAIL)).first()
        target_email = _development_bootstrap_email()
        if not legacy or target_email == LEGACY_BOOTSTRAP_ADMIN_EMAIL:
            return
        if session.exec(select(User.id).where(User.email == target_email)).first():
            return
        legacy.email = target_email
        legacy.updated_at = now_utc()
        session.add(legacy)
        session.commit()


def _seed_development_admin() -> None:
    """仅在没有任何用户时创建本地开发管理员。"""
    from db.security import hash_password

    with Session(engine) as session:
        if session.exec(select(User.id).limit(1)).first():
            return
        if settings.environment.lower() == "production":
            return

        admin = User(
            email=_development_bootstrap_email(),
            display_name="Workspace Admin",
            password_hash=hash_password(settings.bootstrap_admin_password),
            is_platform_admin=True,
        )
        session.add(admin)
        session.flush()
        workspace = Workspace(
            name="My Workspace",
            slug="my-workspace",
            owner_id=admin.id,
        )
        session.add(workspace)
        session.flush()
        session.add(Membership(workspace_id=workspace.id, user_id=admin.id, role="owner"))
        session.commit()
