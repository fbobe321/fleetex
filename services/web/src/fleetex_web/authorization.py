"""Authorization — privilegeLevel + isRestrictedUser + the project view.

Port of AuthorizationManager.getPrivilegeLevelForProjectWithUser + isRestrictedUser
and ProjectEditorHandler.buildProjectModelView (a faithful subset).
"""

from __future__ import annotations

OWNER = "owner"
READ_AND_WRITE = "readAndWrite"
REVIEW = "review"
READ_ONLY = "readOnly"
NONE = None


def _ids(refs) -> set[str]:
    return {str(r) for r in (refs or [])}


def privilege_level_for_user(project: dict, user_id: str | None, is_admin: bool = False) -> str | None:
    if is_admin:
        return OWNER
    if user_id and str(project.get("owner_ref")) == str(user_id):
        return OWNER
    if user_id:
        if user_id in _ids(project.get("collaberator_refs")):
            return READ_AND_WRITE
        if user_id in _ids(project.get("reviewer_refs")):
            return REVIEW
        if user_id in _ids(project.get("readOnly_refs")):
            return READ_ONLY
        # logged-in token members (project must be tokenBased)
        if project.get("publicAccesLevel") == "tokenBased":
            if user_id in _ids(project.get("tokenAccessReadAndWrite_refs")):
                return READ_AND_WRITE
            if user_id in _ids(project.get("tokenAccessReadOnly_refs")):
                return READ_ONLY
    public = project.get("publicAccesLevel")
    if public == READ_AND_WRITE:
        return READ_AND_WRITE
    if public == READ_ONLY:
        return READ_ONLY
    return NONE


def anonymous_privilege_level(project: dict, token: str | None) -> str | None:
    if project.get("publicAccesLevel") == "tokenBased" and token:
        tokens = project.get("tokens", {})
        if token == tokens.get("readAndWrite"):
            return READ_AND_WRITE
        if token == tokens.get("readOnly"):
            return READ_ONLY
    return NONE


def is_token_member(project: dict, user_id: str | None) -> bool:
    if not user_id:
        return False
    return user_id in _ids(project.get("tokenAccessReadAndWrite_refs")) or user_id in _ids(
        project.get("tokenAccessReadOnly_refs")
    )


def is_invited_member(project: dict, user_id: str | None) -> bool:
    if not user_id:
        return False
    return (
        user_id in _ids(project.get("collaberator_refs"))
        or user_id in _ids(project.get("readOnly_refs"))
        or user_id in _ids(project.get("reviewer_refs"))
    )


def is_restricted_user(privilege: str | None, token_member: bool, invited_member: bool, anonymous: bool) -> bool:
    if privilege is NONE:
        return True
    if privilege == READ_ONLY and (token_member or anonymous) and not invited_member:
        return True
    return False


def build_project_view(project: dict, owner: dict | None, restricted: bool) -> dict:
    owner_view = {"_id": str(project.get("owner_ref"))}
    if owner and not restricted:
        owner_view = {
            "_id": str(owner["_id"]),
            "first_name": owner.get("first_name", ""),
            "last_name": owner.get("last_name", ""),
            "email": owner.get("email", ""),
        }
    return {
        "_id": str(project["_id"]),
        "name": project.get("name", ""),
        "rootDoc_id": str(project["rootDoc_id"]) if project.get("rootDoc_id") else None,
        "mainBibliographyDoc_id": str(project["mainBibliographyDoc_id"]) if project.get("mainBibliographyDoc_id") else None,
        "rootFolder": project.get("rootFolder", []),
        "publicAccesLevel": project.get("publicAccesLevel", "private"),
        "dropboxEnabled": False,
        "compiler": project.get("compiler", "pdflatex"),
        "description": project.get("description", ""),
        "spellCheckLanguage": project.get("spellCheckLanguage", "en"),
        "deletedByExternalDataSource": project.get("deletedByExternalDataSource", False),
        "imageName": project.get("imageName"),
        "owner": owner_view,
        "members": [] if restricted else project.get("members", []),
        "invites": [] if restricted else project.get("invites", []),
        "features": project.get("features") or _DEFAULT_FEATURES,
    }


_DEFAULT_FEATURES = {
    "collaborators": -1,
    "versioning": True,
    "dropbox": False,
    "compileTimeout": 60,
    "compileGroup": "standard",
    "templates": True,
    "references": True,
    "trackChanges": True,
    "trackChangesVisible": True,
    "symbolPalette": True,
}
