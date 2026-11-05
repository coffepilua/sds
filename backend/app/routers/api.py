from datetime import datetime

from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select

from .. import services as svc
from ..core import (ACCESS_TTL, MAX_FILE, ApiError, access_token, check_pw, current_user, end_session, get_db,
                    new_session, require, session_user, set_cookie)
from ..models import *  # noqa: F403
from ..schemas import *  # noqa: F403

r = APIRouter(prefix="/api/v1")
d = svc.d
ANY, PAT, COORD, CLIN, ADM = (Depends(x) for x in (current_user, require("patient"), require("coordinator"),
                                                   require("clinic"), require("admin")))
PC = Depends(require("patient", "coordinator"))
PAGE, LIMIT = Query(1, ge=1), Query(20, ge=1, le=100)


# --- auth / профиль ----------------------------------------------------------
@r.post("/auth/register", status_code=201)
def register(b: Register, db=Depends(get_db)):
    if db.scalar(select(User).where(User.email == b.email.lower())):
        raise ApiError(409, "EMAIL_TAKEN", "Email уже зарегистрирован")
    u = User(email=b.email.lower(), password_hash=svc.hash_pw(b.password), full_name=b.full_name, phone=b.phone, role="patient")
    db.add(u)
    db.commit()
    return {"id": u.id, "role": u.role, "email": u.email, "full_name": u.full_name}


@r.post("/auth/login")
def login(b: Login, resp: Response, db=Depends(get_db)):
    u = db.scalar(select(User).where(User.email == b.email.lower()))
    if not u or not u.is_active or not check_pw(u.password_hash, b.password):
        raise ApiError(401, "INVALID_CREDENTIALS", "Неверный email или пароль")
    set_cookie(resp, new_session(db, u))
    svc.audit(db, u.id, "auth.login", "user", u.id)
    db.commit()
    return {"access_token": access_token(u), "token_type": "bearer", "expires_in": ACCESS_TTL, "role": u.role}


@r.post("/auth/refresh")
def refresh(request: Request, db=Depends(get_db)):
    u = session_user(db, request.cookies.get("refresh"))
    if not u:
        raise ApiError(401, "UNAUTHORIZED", "Сессия истекла")
    return {"access_token": access_token(u), "token_type": "bearer", "expires_in": ACCESS_TTL}


@r.post("/auth/logout", status_code=204)
def logout(request: Request, db=Depends(get_db)):
    end_session(db, request.cookies.get("refresh"))
    resp = Response(status_code=204)
    resp.delete_cookie("refresh", path="/")
    return resp


@r.get("/me")
def me(u=ANY):
    return d(u)


@r.patch("/me")
def me_patch(b: ProfilePatch, u=ANY, db=Depends(get_db)):
    for k, v in b.model_dump(exclude_none=True).items():
        setattr(u, k, v)
    db.commit()
    return d(u)


# --- справочники и каталог ---------------------------------------------------
@r.get("/countries")
def countries(db=Depends(get_db)):
    return sorted(db.scalars(select(Clinic.country).where(Clinic.verification_status == "verified").distinct()).all())


@r.get("/specialties")
def specialties(db=Depends(get_db)):
    return [d(s) for s in db.scalars(select(Specialty).order_by(Specialty.name))]


@r.get("/clinics")
def clinics(country: str | None = None, specialty_id: int | None = None, page: int = PAGE, limit: int = LIMIT,
            db=Depends(get_db)):
    q = select(Clinic).where(Clinic.verification_status == "verified")
    if country:
        q = q.where(Clinic.country == country)
    if specialty_id:
        q = q.where(Clinic.id.in_(select(ClinicSpecialty.clinic_id).where(ClinicSpecialty.specialty_id == specialty_id)))
    return svc.paged(db, q.order_by(Clinic.id), page, limit, lambda c: svc.clinic_card(db, c))


@r.get("/clinics/{clinic_id}")
def clinic(clinic_id: int, db=Depends(get_db)):
    c = db.get(Clinic, clinic_id)
    if not c or c.verification_status != "verified":
        raise svc.NF()
    return svc.clinic_card(db, c)


# --- заявки ------------------------------------------------------------------
@r.post("/cases", status_code=201)
def case_create(b: CaseIn, u=PAT, db=Depends(get_db)):
    return svc.create_case(db, u, b)


@r.get("/cases")
def cases(status: str | None = None, page: int = PAGE, limit: int = LIMIT, u=PAT, db=Depends(get_db)):
    q = select(Case).where(Case.patient_id == u.id).order_by(Case.id.desc())
    return svc.paged(db, q.where(Case.status == status) if status else q, page, limit)


@r.get("/cases/{cid}")
def case_get(cid: int, u=ANY, db=Depends(get_db)):
    c = svc.get_case(db, u, cid)
    return {**d(c, drop=("patient_id",) if u.role == "clinic" else ())}


@r.patch("/cases/{cid}")
def case_patch(cid: int, b: CasePatch, u=PAT, db=Depends(get_db)):
    return svc.patch_case(db, u, cid, b)


@r.post("/cases/{cid}/submit")
def case_submit(cid: int, u=PAT, db=Depends(get_db)):
    return svc.submit_case(db, u, cid)


@r.post("/cases/{cid}/cancel")
def case_cancel(cid: int, b: ReasonIn | None = None, u=PC, db=Depends(get_db)):
    return svc.cancel_case(db, u, cid)


# --- документы ---------------------------------------------------------------
@r.post("/cases/{cid}/documents", status_code=201)
async def doc_upload(cid: int, file: UploadFile = File(...), u=PAT, db=Depends(get_db)):
    data = await file.read(MAX_FILE + 1)
    return svc.add_doc(db, u, cid, file.filename, file.content_type, data)


@r.get("/cases/{cid}/documents")
def doc_list(cid: int, u=ANY, db=Depends(get_db)):
    return svc.docs_of(db, u, cid)


@r.get("/cases/{cid}/documents/{did}/download")
def doc_download(cid: int, did: int, u=ANY, db=Depends(get_db)):
    path, doc = svc.doc_file(db, u, cid, did)
    return FileResponse(path, media_type=doc.mime_type, filename=doc.file_name)


@r.delete("/cases/{cid}/documents/{did}", status_code=204)
def doc_delete(cid: int, did: int, u=PC, db=Depends(get_db)):
    svc.del_doc(db, u, cid, did)


# --- координатор -------------------------------------------------------------
@r.get("/coordinator/cases")
def coord_cases(status: str | None = None, page: int = PAGE, limit: int = LIMIT, u=COORD, db=Depends(get_db)):
    q = select(Case).where(Case.status != "draft").order_by(Case.id.desc())
    return svc.paged(db, q.where(Case.status == status) if status else q, page, limit)


@r.patch("/coordinator/cases/{cid}/status")
def coord_set_status(cid: int, b: StatusIn, u=COORD, db=Depends(get_db)):
    return svc.coord_status(db, u, cid, b.status)


@r.post("/coordinator/cases/{cid}/share-requests", status_code=201)
def coord_share(cid: int, b: ShareIn, u=COORD, db=Depends(get_db)):
    return svc.request_share(db, u, cid, b.clinic_id)


# --- согласия ----------------------------------------------------------------
@r.get("/cases/{cid}/shares")
def shares(cid: int, u=PC, db=Depends(get_db)):
    return [{**d(s), "clinic_name": cl.name} for s, cl in svc.shares_of(db, u, cid)]


@r.post("/cases/{cid}/shares/{sid}/consent")
def share_consent(cid: int, sid: int, b: ConsentIn, u=PAT, db=Depends(get_db)):
    return svc.consent(db, u, cid, sid, b.approved)


@r.post("/cases/{cid}/shares/{sid}/revoke")
def share_revoke(cid: int, sid: int, u=PAT, db=Depends(get_db)):
    return svc.revoke(db, u, cid, sid)


# --- кабинет клиники и сметы -------------------------------------------------
@r.get("/clinic/cases")
def clinic_cases(page: int = PAGE, limit: int = LIMIT, u=CLIN, db=Depends(get_db)):
    ids = svc.user_clinics(db, u)
    ok = select(CaseShare.case_id).where(CaseShare.clinic_id.in_(ids), CaseShare.consent_status == "approved")
    q = select(Case).where(Case.id.in_(ok)).order_by(Case.id.desc())
    return svc.paged(db, q, page, limit, lambda c: d(c, drop=("patient_id",)))


@r.get("/clinic/cases/{cid}")
def clinic_case(cid: int, u=CLIN, db=Depends(get_db)):
    return d(svc.get_case(db, u, cid), drop=("patient_id",))


@r.post("/clinic/cases/{cid}/quotes", status_code=201)
def quote_create(cid: int, b: QuoteIn, u=CLIN, db=Depends(get_db)):
    return svc.add_offer(db, u, cid, b)


@r.patch("/clinic/quotes/{qid}")
def quote_patch(qid: int, b: QuotePatch, u=CLIN, db=Depends(get_db)):
    return svc.patch_offer(db, u, qid, b)


@r.get("/cases/{cid}/quotes")
def quotes(cid: int, u=ANY, db=Depends(get_db)):
    return svc.offers_of(db, u, cid)


@r.post("/cases/{cid}/quotes/{qid}/select")
def quote_select(cid: int, qid: int, u=PAT, db=Depends(get_db)):
    return svc.select_offer(db, u, cid, qid)


# --- диалоги -----------------------------------------------------------------
@r.get("/cases/{cid}/conversations")
def convs(cid: int, u=ANY, db=Depends(get_db)):
    return svc.convs_of(db, u, cid)


@r.get("/cases/{cid}/conversations/{vid}/messages")
def msgs(cid: int, vid: int, page: int = PAGE, limit: int = LIMIT, u=ANY, db=Depends(get_db)):
    return svc.msgs_of(db, u, cid, vid, page, limit)


@r.post("/cases/{cid}/conversations/{vid}/messages", status_code=201)
def msg_send(cid: int, vid: int, b: MsgIn, u=ANY, db=Depends(get_db)):
    return svc.send_msg(db, u, cid, vid, b.body)


# --- уведомления -------------------------------------------------------------
@r.get("/notifications")
def notifications(unread_only: bool = False, page: int = PAGE, limit: int = LIMIT, u=ANY, db=Depends(get_db)):
    q = select(Notification).where(Notification.user_id == u.id).order_by(Notification.id.desc())
    return svc.paged(db, q.where(Notification.is_read.is_(False)) if unread_only else q, page, limit)


@r.patch("/notifications/{nid}/read")
def notification_read(nid: int, u=ANY, db=Depends(get_db)):
    n = db.get(Notification, nid)
    if not n or n.user_id != u.id:
        raise svc.NF()
    n.is_read = True
    db.commit()
    return d(n)


# --- администратор -----------------------------------------------------------
@r.post("/admin/staff", status_code=201)
def admin_staff(b: StaffIn, u=ADM, db=Depends(get_db)):
    return svc.create_staff(db, u, b)


@r.post("/admin/clinics", status_code=201)
def admin_clinic_create(b: ClinicIn, u=ADM, db=Depends(get_db)):
    return svc.save_clinic(db, u, None, b.model_dump())


@r.patch("/admin/clinics/{clinic_id}")
def admin_clinic_patch(clinic_id: int, b: ClinicPatch, u=ADM, db=Depends(get_db)):
    return svc.save_clinic(db, u, clinic_id, b.model_dump(exclude_unset=True))


@r.get("/admin/users")
def admin_users(role: str | None = None, is_active: bool | None = None, page: int = PAGE, limit: int = LIMIT,
                u=ADM, db=Depends(get_db)):
    q = select(User).order_by(User.id)
    if role:
        q = q.where(User.role == role)
    if is_active is not None:
        q = q.where(User.is_active.is_(is_active))
    return svc.paged(db, q, page, limit)


@r.patch("/admin/users/{uid}/status")
def admin_user_status(uid: int, b: ActiveIn, u=ADM, db=Depends(get_db)):
    return svc.set_active(db, u, uid, b.is_active)


@r.get("/admin/metrics")
def admin_metrics(date_from: datetime | None = Query(None, alias="from"), date_to: datetime | None = Query(None, alias="to"),
                  u=ADM, db=Depends(get_db)):
    return svc.metrics(db, date_from, date_to)
