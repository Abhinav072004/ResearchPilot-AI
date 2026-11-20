import hashlib
import secrets
from time import time
from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import Cookie, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import db_session
from app.models import Login, Membership, Project, User

hasher = PasswordHasher()
dummy_hash = hasher.hash(secrets.token_hex())
cookie_name = "rp_session"
Db = Annotated[Session, Depends(db_session)]


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def login(db: Session, user: User, response: Response, previous_token: str | None):
    token = secrets.token_urlsafe(32)
    ttl = 86400
    if previous_token and (previous := db.get(Login, digest(previous_token))):
        db.delete(previous)
    db.add(Login(token_hash=digest(token), user_id=user.id, expires=time() + ttl))
    db.commit()
    response.set_cookie(cookie_name, token, max_age=ttl, httponly=True,
                        secure=settings().secure_cookie, samesite="strict")


def verify_password(user: User | None, password: str) -> bool:
    try:
        return hasher.verify(user.password if user else dummy_hash, password) and user is not None
    except VerificationError:
        return False


def current_user(db: Db, rp_session: Annotated[str | None, Cookie()] = None) -> User:
    session = db.get(Login, digest(rp_session)) if rp_session else None
    if session is None or session.expires <= time():
        raise HTTPException(401, "Sign in to continue")
    return db.get(User, session.user_id)


CurrentUser = Annotated[User, Depends(current_user)]


def projects_for(user: User):
    return select(Project).join(Membership, Membership.organization_id == Project.organization_id).where(
        Membership.user_id == user.id, Project.pending_deletion.is_(False)
    )


def require_project(db: Session, user: User, project_id: str, *, write: bool = False) -> Project:
    query = projects_for(user).where(Project.id == project_id)
    if write:
        query = query.where(Membership.role.in_(("owner", "editor"))).with_for_update(of=Project)
    project = db.scalar(query)
    if project is None:
        raise HTTPException(404, "Project not found")
    return project
