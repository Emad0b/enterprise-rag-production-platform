import hashlib, hmac, secrets, time, json
from fastapi import Header, HTTPException, Depends
from .db import db, sql, audit


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    return (
        salt
        + ":"
        + hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 310000).hex()
    )


def issue_session(uid):
    token = secrets.token_urlsafe(32)
    with db() as c:
        sql(c, "DELETE FROM sessions WHERE expires<?", (time.time(),))
        sql(
            c,
            "INSERT INTO sessions VALUES (?,?,?)",
            (hashlib.sha256(token.encode()).hexdigest(), uid, time.time() + 3600),
        )
    return token


def principal(authorization: str | None = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Sign in to the document workspace")
    token = authorization[7:]
    with db() as c:
        row = sql(
            c,
            "SELECT u.id,u.email,u.name,u.groups_json,u.admin FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.token=? AND s.expires>?",
            (hashlib.sha256(token.encode()).hexdigest(), time.time()),
        ).fetchone()
    if not row:
        raise HTTPException(401, "Session expired")
    return {
        "id": row[0],
        "email": row[1],
        "name": row[2],
        "groups": json.loads(row[3]),
        "admin": bool(row[4]),
    }


def administrator(user=Depends(principal)):
    if not user["admin"]:
        raise HTTPException(403, "Administrator permission required")
    return user


def acl_clause(user, alias="d"):
    groups = user["groups"]
    if not groups:
        return "1=0", []
    return (
        f"EXISTS (SELECT 1 FROM acl a WHERE a.document_id={alias}.id AND a.group_name IN ("
        + ",".join("?" for _ in groups)
        + "))",
        list(groups),
    )


def authorized(user, ids):
    if not ids:
        return
    clause, args = acl_clause(user)
    for did in set(ids):
        with db() as c:
            row = sql(
                c,
                "SELECT d.id FROM documents d WHERE d.id=? AND " + clause,
                (did, *args),
            ).fetchone()
            if not row:
                missing = True
            else:
                missing = False
        if missing:
            audit(user["id"], "document_access_denied", {"document_id": did})
            raise HTTPException(404, "Document unavailable")
