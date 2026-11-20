from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Cookie, HTTPException, Response
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.auth import CurrentUser, Db, cookie_name, digest, hasher, login, projects_for, require_project, verify_password
from app.models import AuditEvent, Conversation, Job, Login, Membership, Message, Organization, Project, User
from app.schemas import AccountResponse, ConversationResponse, MessageResponse, NamedResponse

router = APIRouter()
CleanTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]


class Credentials(BaseModel):
    email: Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")]
    password: str = Field(min_length=12, max_length=128)


class Title(BaseModel):
    title: CleanTitle


class MessageBody(BaseModel):
    body: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20000)]


def named(item):
    return {"id": item.id, "title": item.title}


@router.post("/auth/register", status_code=201, response_model=AccountResponse)
def register(body: Credentials, db: Db, response: Response, rp_session: Annotated[str | None, Cookie()] = None):
    user = User(email=body.email, password=hasher.hash(body.password))
    org = Organization(name="Personal workspace")
    db.add_all((user, org))
    try:
        db.flush()
        db.add(Membership(organization_id=org.id, user_id=user.id, role="owner"))
        login(db, user, response, rp_session)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "An account with this email already exists") from exc
    return {"id": user.id, "email": user.email}


@router.post("/auth/login", response_model=AccountResponse)
def sign_in(body: Credentials, db: Db, response: Response, rp_session: Annotated[str | None, Cookie()] = None):
    user = db.scalar(select(User).where(User.email == body.email))
    if not verify_password(user, body.password):
        raise HTTPException(401, "Invalid email or password")
    login(db, user, response, rp_session)
    return {"id": user.id, "email": user.email}


@router.get("/auth/me", response_model=AccountResponse)
def me(user: CurrentUser):
    return {"id": user.id, "email": user.email}


@router.post("/auth/logout", status_code=204)
def logout(db: Db, rp_session: Annotated[str | None, Cookie()] = None):
    if rp_session and (session := db.get(Login, digest(rp_session))):
        db.delete(session)
        db.commit()
    response = Response(status_code=204)
    response.delete_cookie(cookie_name)
    return response


@router.get("/projects", response_model=list[NamedResponse])
def projects(db: Db, user: CurrentUser, offset: int = 0):
    return [named(p) for p in db.scalars(projects_for(user).order_by(Project.title, Project.id).offset(max(offset, 0)).limit(100))]


@router.post("/projects", status_code=201, response_model=NamedResponse)
def create_project(body: Title, db: Db, user: CurrentUser):
    org = db.scalar(select(Membership.organization_id).where(Membership.user_id == user.id, Membership.role == "owner").limit(1))
    if org is None:
        raise HTTPException(403, "Project creation requires a workspace owner")
    project = Project(title=body.title, organization_id=org)
    db.add(project)
    db.commit()
    return named(project)


@router.get("/projects/{project_id}", response_model=NamedResponse)
def project(project_id: str, db: Db, user: CurrentUser):
    return named(require_project(db, user, project_id))


@router.patch("/projects/{project_id}", response_model=NamedResponse)
def update_project(project_id: str, body: Title, db: Db, user: CurrentUser):
    item = require_project(db, user, project_id, write=True)
    item.title = body.title
    db.commit()
    return named(item)


@router.delete("/projects/{project_id}", status_code=202)
def delete_project(project_id: str, db: Db, user: CurrentUser, tasks: BackgroundTasks):
    from app.worker import schedule

    project = db.scalar(select(Project).join(Membership, Membership.organization_id == Project.organization_id)
                        .where(Project.id == project_id, Membership.user_id == user.id, Membership.role == "owner")
                        .with_for_update(of=Project))
    if project is None:
        raise HTTPException(404, "Project not found")
    active = db.scalar(select(Job).where(Job.project_id == project.id, Job.status.in_(("queued", "running"))).limit(1))
    if active:
        if active.kind == "purge":
            return {"status": "pending_deletion"}
        raise HTTPException(409, "Wait for active project jobs before deleting")
    project.pending_deletion = True
    job = Job(project_id=project.id, kind="purge", payload={})
    db.add_all((job, AuditEvent(organization_id=project.organization_id, actor_id=user.id,
                                project_ref=project.id, event="project_deletion_requested")))
    db.commit()
    schedule(tasks, job.id)
    return {"status": "pending_deletion"}


def require_conversation(db, user, conversation_id, *, write=False):
    item = db.get(Conversation, conversation_id)
    if item is None:
        raise HTTPException(404, "Conversation not found")
    require_project(db, user, item.project_id, write=write)
    return item


@router.get("/projects/{project_id}/conversations", response_model=list[NamedResponse])
def conversations(project_id: str, db: Db, user: CurrentUser, offset: int = 0):
    require_project(db, user, project_id)
    query = select(Conversation).where(Conversation.project_id == project_id).order_by(Conversation.title, Conversation.id)
    return [named(item) for item in db.scalars(query.offset(max(offset, 0)).limit(100))]


@router.post("/projects/{project_id}/conversations", status_code=201, response_model=NamedResponse)
def create_conversation(project_id: str, body: Title, db: Db, user: CurrentUser):
    require_project(db, user, project_id, write=True)
    item = Conversation(project_id=project_id, title=body.title)
    db.add(item)
    db.commit()
    return named(item)


@router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
def conversation(conversation_id: str, db: Db, user: CurrentUser, offset: int = 0):
    item = require_conversation(db, user, conversation_id)
    records = db.scalars(select(Message).where(Message.conversation_id == item.id)
                         .order_by(Message.created, Message.id).offset(max(offset, 0)).limit(100))
    return {**named(item), "messages": [{"id": m.id, "body": m.body} for m in records]}


@router.patch("/conversations/{conversation_id}", response_model=NamedResponse)
def update_conversation(conversation_id: str, body: Title, db: Db, user: CurrentUser):
    item = require_conversation(db, user, conversation_id, write=True)
    item.title = body.title
    db.commit()
    return named(item)


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: str, db: Db, user: CurrentUser):
    db.delete(require_conversation(db, user, conversation_id, write=True))
    db.commit()


@router.post("/conversations/{conversation_id}/messages", status_code=201, response_model=MessageResponse)
def add_message(conversation_id: str, body: MessageBody, db: Db, user: CurrentUser):
    item = require_conversation(db, user, conversation_id, write=True)
    message = Message(conversation_id=item.id, body=body.body)
    db.add(message)
    db.commit()
    return {"id": message.id, "body": message.body}


class TeamRole(BaseModel):
    role: Literal["editor", "viewer"]


class TeamMember(TeamRole):
    email: Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, max_length=254,
                                            pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")]


def owner_team(db, user, project_id):
    project = require_project(db, user, project_id)
    owner = db.get(Membership, (project.organization_id, user.id))
    if owner is None or owner.role != "owner":
        raise HTTPException(403, "Only workspace owners can manage team access")
    return project


def team_change(db, user, project, event):
    db.add(AuditEvent(organization_id=project.organization_id, actor_id=user.id,
                      project_ref=project.id, event=event))
    db.commit()


@router.get("/projects/{project_id}/team")
def team(project_id: str, db: Db, user: CurrentUser):
    project = require_project(db, user, project_id)
    membership = db.get(Membership, (project.organization_id, user.id))
    if membership is None:
        raise HTTPException(404, "Workspace membership not found")
    if membership.role != "owner":
        return {"role": membership.role, "members": []}
    rows = db.execute(select(User, Membership).join(Membership, Membership.user_id == User.id)
                      .where(Membership.organization_id == project.organization_id).order_by(User.email))
    return {"role": "owner", "members": [{"id": member.id, "email": member.email, "role": access.role}
                                         for member, access in rows]}


@router.post("/projects/{project_id}/team", status_code=201)
def add_team_member(project_id: str, body: TeamMember, db: Db, user: CurrentUser):
    project = owner_team(db, user, project_id)
    member = db.scalar(select(User).where(User.email == body.email))
    if member is None:
        raise HTTPException(404, "A registered account with this email was not found")
    try:
        db.add(Membership(organization_id=project.organization_id, user_id=member.id, role=body.role))
        team_change(db, user, project, "workspace_member_added")
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "This account already has workspace access") from exc
    return {"id": member.id, "email": member.email, "role": body.role}


def editable_member(db, project, member_id):
    membership = db.get(Membership, (project.organization_id, member_id), with_for_update=True)
    if membership is None:
        raise HTTPException(404, "Workspace member not found")
    if membership.role == "owner":
        raise HTTPException(409, "Workspace ownership cannot be changed here")
    return membership


@router.patch("/projects/{project_id}/team/{member_id}")
def update_team_member(project_id: str, member_id: str, body: TeamRole, db: Db, user: CurrentUser):
    project = owner_team(db, user, project_id)
    membership = editable_member(db, project, member_id)
    membership.role = body.role
    team_change(db, user, project, "workspace_role_changed")
    return {"id": member_id, "role": body.role}


@router.delete("/projects/{project_id}/team/{member_id}", status_code=204)
def remove_team_member(project_id: str, member_id: str, db: Db, user: CurrentUser):
    project = owner_team(db, user, project_id)
    db.delete(editable_member(db, project, member_id))
    team_change(db, user, project, "workspace_member_removed")
