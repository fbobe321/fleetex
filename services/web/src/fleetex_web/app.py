"""HTTP layer for the web auth slice.

Routes: POST /login, POST /logout, POST /user/password/update (session-backed),
and the internal POST /project/:id/join (basic-auth, used by real-time).
"""

from __future__ import annotations

import base64

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fleetex_service_kit import Settings, create_app
from motor.motor_asyncio import AsyncIOMotorClient
from redis import asyncio as aioredis

from . import authorization as authz
from .auth import authenticate
from .config import WebConfig
from .compile import ClsiManager, register_compile_routes
from .editor import DocstoreClient, register_editor_routes
from .file_tree import EditorEventsPublisher, FilestoreClient, FileTreeManager, register_file_tree_routes
from .frontend import register_frontend_routes
from .passwords import verify_password
from .projects import ProjectManager, register_project_routes
from .sessions import SessionStore, generate_session_id, get_logged_in_user_id, serialize_user
from .users import UserManager


def _cookie_header(config: WebConfig, signed_value: str) -> str:
    parts = [f"{config.cookie_name}={signed_value}", "Path=/", "HttpOnly", f"Max-Age={config.cookie_max_age_s}", f"SameSite={config.same_site.capitalize()}"]
    if config.secure_cookie:
        parts.append("Secure")
    return "; ".join(parts)


def _check_basic_auth(request: Request, config: WebConfig) -> bool:
    header = request.headers.get("authorization", "")
    if not header.startswith("Basic "):
        return False
    try:
        user, _, password = base64.b64decode(header[6:]).decode("utf-8").partition(":")
    except (ValueError, UnicodeDecodeError):
        return False
    return user == config.web_api_user and password == config.web_api_password


def build_app(config: WebConfig | None = None, *, db=None, redis=None, docstore=None, filestore=None, events=None, clsi=None) -> FastAPI:
    config = config or WebConfig.from_env()
    settings = Settings.from_env("web", default_port=config.port, env={})
    app = create_app(settings, connect_mongo=False, connect_redis=False, status_text="web is alive")

    if db is None:
        db = AsyncIOMotorClient(config.mongo_url)["sharelatex"]
    if redis is None:
        redis = aioredis.from_url(config.redis_url, decode_responses=True)

    users = UserManager(db, config.bcrypt_rounds)
    store = SessionStore(redis, config.session_secrets, config.cookie_max_age_s)
    projects = ProjectManager(db)
    app.state.db = db
    app.state.users = users
    app.state.store = store
    app.state.projects = projects
    app.state.config = config

    async def _session(request: Request):
        return await store.load_from_cookie(request.cookies.get(config.cookie_name))

    # ---- login ---------------------------------------------------------- #
    @app.post("/login")
    async def login(request: Request):
        body = await request.json()
        email, password = body.get("email"), body.get("password")
        if not email or not isinstance(email, str):
            return JSONResponse({"message": {"type": "error", "text": "invalid email"}}, status_code=400)
        user = await authenticate(users, email, password or "")
        if not user:
            return JSONResponse({"message": {"type": "error", "key": "invalid-password-retry-or-reset"}}, status_code=401)
        sid = generate_session_id()
        await store.save(sid, {"passport": {"user": serialize_user(user)}, "justLoggedIn": True})
        await users.record_login(user["_id"], request.client.host if request.client else None)
        resp = JSONResponse({"redir": "/project"})
        resp.headers.append("set-cookie", _cookie_header(config, store.sign_cookie(sid)))
        return resp

    # ---- logout --------------------------------------------------------- #
    @app.post("/logout")
    async def logout(request: Request):
        sid, _sess = await _session(request)
        if sid:
            await store.destroy(sid)
        resp = JSONResponse({"redir": "/login"})
        resp.delete_cookie(config.cookie_name, path="/")
        return resp

    # ---- change password ------------------------------------------------ #
    @app.post("/user/password/update")
    async def change_password(request: Request):
        _sid, session = await _session(request)
        user_id = get_logged_in_user_id(session)
        if not user_id:
            return JSONResponse({"message": {"type": "error", "text": "not authenticated"}}, status_code=401)
        body = await request.json()
        user = await users.find_by_id(user_id)
        if not user or not verify_password(body.get("currentPassword") or "", user.get("hashedPassword", "")):
            return JSONResponse({"message": {"type": "error", "text": "your current password is incorrect"}}, status_code=400)
        new1, new2 = body.get("newPassword1"), body.get("newPassword2")
        if not new1 or new1 != new2:
            return JSONResponse({"message": {"type": "error", "text": "passwords do not match"}}, status_code=400)
        await users.set_password(user_id, new1)
        return JSONResponse({"message": {"type": "success", "email": user["email"], "text": "password changed"}})

    # ---- internal: project join (real-time calls this) ------------------ #
    @app.post("/project/{project_id}/join")
    async def join_project(project_id: str, request: Request):
        if not _check_basic_auth(request, config):
            return Response(status_code=401)
        body = await request.json()
        user_id = body.get("userId")
        anon_token = body.get("anonymousAccessToken")
        if user_id == "anonymous-user":
            user_id = None
        try:
            project = await db["projects"].find_one({"_id": ObjectId(project_id)})
        except (InvalidId, TypeError):
            project = None
        if not project:
            return Response(status_code=403)

        if user_id:
            user = await users.find_by_id(user_id)
            privilege = authz.privilege_level_for_user(project, user_id, bool(user and user.get("isAdmin")))
        else:
            privilege = authz.anonymous_privilege_level(project, anon_token)
        if privilege is authz.NONE:
            return Response(status_code=403)

        token_member = authz.is_token_member(project, user_id)
        invited = authz.is_invited_member(project, user_id)
        restricted = authz.is_restricted_user(privilege, token_member, invited, anonymous=user_id is None)
        owner = await users.find_by_id(str(project.get("owner_ref"))) if project.get("owner_ref") else None
        return JSONResponse(
            {
                "project": authz.build_project_view(project, owner, restricted),
                "privilegeLevel": privilege,
                "isRestrictedUser": restricted,
                "isTokenMember": token_member,
                "isInvitedMember": invited,
            }
        )

    register_project_routes(app, pm=projects, db=db, store=store, config=config)
    docstore = docstore if docstore is not None else DocstoreClient(config.docstore_url)
    app.state.docstore = docstore
    register_editor_routes(app, pm=projects, db=db, store=store, config=config, docstore=docstore)

    filestore = filestore if filestore is not None else FilestoreClient(config.filestore_url)
    events = events if events is not None else EditorEventsPublisher(redis)
    ft = FileTreeManager(db, docstore, filestore, events)
    app.state.file_tree = ft
    register_file_tree_routes(app, pm=projects, db=db, store=store, config=config, ft=ft)

    clsi = clsi if clsi is not None else ClsiManager(config.clsi_url, config.document_updater_url, config.filestore_url)
    app.state.clsi = clsi
    register_compile_routes(app, pm=projects, store=store, config=config, clsi=clsi)

    register_frontend_routes(app, config=config, store=store, users=users)
    return app


app = build_app()
