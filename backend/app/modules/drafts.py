from datetime import timedelta

from sqlalchemy import select

from ..models import Draft
from .identity.service import new_id, utc_now


def owned_draft(session, identity):
    return session.scalar(select(Draft).where(Draft.identity_id == identity.id))


def save_draft_record(session, identity, data):
    draft = owned_draft(session, identity)
    now = utc_now()
    if draft is None:
        draft = Draft(id=new_id("D"), identity_id=identity.id, version=1)
        session.add(draft)
    else:
        draft.version += 1
    email = (data.get("requester") or {}).get("email") or ""
    email = email.strip().lower()
    draft.email = email if "@" in email and all(email.split("@", 1)) else None
    draft.data = data
    draft.updated_at = now
    draft.expires_at = now + timedelta(minutes=30)


def discard_draft_record(session, identity):
    draft = owned_draft(session, identity)
    if draft is not None:
        session.delete(draft)
