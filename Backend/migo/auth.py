"""Cuentas simples (email + contraseña con PBKDF2) y token Bearer. Prototipo: los demás endpoints aún no exigen token."""
import hashlib, hmac, secrets
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from . import db

db.run("create table if not exists accounts(id serial primary key,email text unique,name text,salt text,pw text,token text,user_id int,created_at double precision)", write=True)
router = APIRouter(prefix="/auth")

class Reg(BaseModel): name: str = ""; email: str; password: str
class Login(BaseModel): email: str; password: str
class Link(BaseModel): user_id: int

def _h(pw, salt): return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 120_000).hex()
def _out(a): return {"token": a["token"], "user_id": a["user_id"], "name": a["name"], "email": a["email"]}
def _me(authorization):
    t = (authorization or "").replace("Bearer ", "")
    a = db.run("select * from accounts where token=?", (t,), one=True) if t else None
    if not a: raise HTTPException(401, "Sesión inválida, entra de nuevo")
    return a

@router.post("/register")
def register(b: Reg):
    e = b.email.strip().lower()
    if "@" not in e or len(b.password) < 6: raise HTTPException(422, "Correo válido y contraseña de 6+ caracteres")
    if db.run("select 1 from accounts where email=?", (e,), one=True): raise HTTPException(409, "Ese correo ya tiene cuenta")
    salt, tok = secrets.token_hex(16), secrets.token_urlsafe(32)
    db.run("insert into accounts(email,name,salt,pw,token,created_at) values(?,?,?,?,?,?)", (e, b.name.strip() or e.split("@")[0], salt, _h(b.password, salt), tok, db.now()), write=True)
    return _out(db.run("select * from accounts where email=?", (e,), one=True))

@router.post("/login")
def login(b: Login):
    a = db.run("select * from accounts where email=?", (b.email.strip().lower(),), one=True)
    if not a or not hmac.compare_digest(a["pw"], _h(b.password, a["salt"])): raise HTTPException(401, "Correo o contraseña incorrectos")
    tok = secrets.token_urlsafe(32); db.run("update accounts set token=? where id=?", (tok, a["id"]), write=True)
    return _out({**a, "token": tok})

@router.get("/me")
def me(authorization: str = Header(None)): return _out(_me(authorization))

@router.post("/link")
def link(b: Link, authorization: str = Header(None)):
    a = _me(authorization); db.run("update accounts set user_id=? where id=?", (b.user_id, a["id"]), write=True); return {"ok": True}
