from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy import select, update

from .. import services as svc
from ..core import ApiError, MAX_FILE, end_session, get_db, session_user
from ..models import *  # noqa: F403
from ..schemas import ClinicIn, ClinicPatch, QuoteIn, StaffIn

pages = APIRouter(include_in_schema=False)
T = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates"))
T.env.filters["ru"] = lambda v: svc.RU.get(v, v)
T.env.filters["dt"] = lambda v: v.strftime("%d.%m.%Y %H:%M") if v else ""
BASE = {"patient": "/cases", "coordinator": "/coordinator/cases", "clinic": "/clinic/cases"}
HOME = {"patient": "/dashboard", "coordinator": "/coordinator", "clinic": "/clinic", "admin": "/admin"}


def who(request, db, *roles):
    u = session_user(db, request.cookies.get("refresh"))
    if not u:
        raise ApiError(401, "UNAUTHORIZED", "Требуется вход")
    if u.role not in roles:
        raise ApiError(403, "FORBIDDEN", "Нет доступа к этому разделу")
    return u


def render(request, db, name, u, **ctx):
    notes = db.scalars(select(Notification).where(Notification.user_id == u.id).order_by(Notification.id.desc()).limit(8)).all()
    return T.TemplateResponse(request, name, {
        "u": u, "home": HOME[u.role], "notes": notes, "unread": sum(not n.is_read for n in notes),
        "ok": request.query_params.get("ok"), "err": request.query_params.get("err"), **ctx})


def act(db, back, fn):
    try:
        fn()
    except (ApiError, ValidationError) as e:
        db.rollback()
        msg = e.message if isinstance(e, ApiError) else "Проверьте заполнение полей"
        return RedirectResponse(f"{back}?err={quote(msg)}", 303)
    return RedirectResponse(f"{back}?ok=1", 303)


def case_ctx(db, u, cid):
    c = svc.get_case(db, u, cid)
    ctx = {"c": c, "spec": db.get(Specialty, c.specialty_id), "base": f"{BASE[u.role]}/{cid}", "back": HOME[u.role],
           "docs": svc.docs_of(db, u, cid), "offers": svc.offers_of(db, u, cid), "convs": svc.convs_of(db, u, cid),
           "shares": [], "clinics": [], "my_shares": [], "patient": None}
    if u.role in ("patient", "coordinator"):
        ctx["shares"] = svc.shares_of(db, u, cid)
        ctx["patient"] = db.get(User, c.patient_id)
    if u.role == "coordinator":
        used = {s.clinic_id for s, _ in ctx["shares"]}
        q = (select(Clinic).join(ClinicSpecialty, ClinicSpecialty.clinic_id == Clinic.id)
             .where(Clinic.verification_status == "verified", ClinicSpecialty.specialty_id == c.specialty_id))
        ctx["clinics"] = [x for x in db.scalars(q) if x.id not in used]
    if u.role == "clinic":
        ctx["my_shares"] = svc.approved_shares(db, cid, svc.user_clinics(db, u))
    return ctx


# --- выход и уведомления -------------------------------------------------------
@pages.post("/logout")
def p_logout(request: Request, db=Depends(get_db)):
    end_session(db, request.cookies.get("refresh"))
    resp = RedirectResponse("/", 303)
    resp.delete_cookie("refresh", path="/")
    return resp


@pages.post("/notifications/read")
def p_notes_read(request: Request, db=Depends(get_db)):
    u = who(request, db, "patient", "coordinator", "clinic", "admin")
    db.execute(update(Notification).where(Notification.user_id == u.id).values(is_read=True))
    db.commit()
    return RedirectResponse(HOME[u.role], 303)


# --- пациент -------------------------------------------------------------------
@pages.get("/dashboard")
def p_dashboard(request: Request, db=Depends(get_db)):
    u = who(request, db, "patient")
    rows = db.execute(select(Case, Specialty).join(Specialty, Specialty.id == Case.specialty_id)
                      .where(Case.patient_id == u.id).order_by(Case.id.desc())).all()
    return render(request, db, "cases_list.html", u, title="Мои заявки", new=True, status=None,
                  rows=[{"c": c, "spec": s.name, "url": f"/cases/{c.id}", "extra": c.target_country or "—"} for c, s in rows])


@pages.get("/cases/{cid}")
def p_case(cid: int, request: Request, db=Depends(get_db)):
    u = who(request, db, "patient")
    return render(request, db, "case_detail.html", u, **case_ctx(db, u, cid))


@pages.post("/cases/{cid}/submit")
def p_submit(cid: int, request: Request, db=Depends(get_db)):
    u = who(request, db, "patient")
    return act(db, f"/cases/{cid}", lambda: svc.submit_case(db, u, cid))


@pages.post("/cases/{cid}/cancel")
def p_cancel(cid: int, request: Request, db=Depends(get_db)):
    u = who(request, db, "patient")
    return act(db, f"/cases/{cid}", lambda: svc.cancel_case(db, u, cid))


@pages.post("/cases/{cid}/upload")
async def p_upload(cid: int, request: Request, file: UploadFile = File(...), db=Depends(get_db)):
    u = who(request, db, "patient")
    data = await file.read(MAX_FILE + 1)
    return act(db, f"/cases/{cid}", lambda: svc.add_doc(db, u, cid, file.filename, file.content_type, data))


@pages.post("/cases/{cid}/shares/{sid}/consent")
def p_consent(cid: int, sid: int, request: Request, approved: str = Form(...), db=Depends(get_db)):
    u = who(request, db, "patient")
    return act(db, f"/cases/{cid}", lambda: svc.consent(db, u, cid, sid, approved == "1"))


@pages.post("/cases/{cid}/shares/{sid}/revoke")
def p_revoke(cid: int, sid: int, request: Request, db=Depends(get_db)):
    u = who(request, db, "patient")
    return act(db, f"/cases/{cid}", lambda: svc.revoke(db, u, cid, sid))


@pages.post("/cases/{cid}/offers/{oid}/select")
def p_select(cid: int, oid: int, request: Request, db=Depends(get_db)):
    u = who(request, db, "patient")
    return act(db, f"/cases/{cid}", lambda: svc.select_offer(db, u, cid, oid))


# --- координатор ---------------------------------------------------------------
@pages.get("/coordinator")
def p_coord(request: Request, status: str | None = None, db=Depends(get_db)):
    u = who(request, db, "coordinator")
    q = (select(Case, Specialty).join(Specialty, Specialty.id == Case.specialty_id)
         .where(Case.status != "draft").order_by(Case.id.desc()))
    rows = db.execute(q.where(Case.status == status) if status else q).all()
    return render(request, db, "cases_list.html", u, title="Очередь заявок", new=False, status=status or "",
                  rows=[{"c": c, "spec": s.name, "url": f"/coordinator/cases/{c.id}", "extra": c.target_country or "—"} for c, s in rows])


@pages.get("/coordinator/cases/{cid}")
def p_coord_case(cid: int, request: Request, db=Depends(get_db)):
    u = who(request, db, "coordinator")
    return render(request, db, "case_detail.html", u, **case_ctx(db, u, cid))


@pages.post("/coordinator/cases/{cid}/status")
def p_coord_status(cid: int, request: Request, status: str = Form(...), db=Depends(get_db)):
    u = who(request, db, "coordinator")
    return act(db, f"/coordinator/cases/{cid}", lambda: svc.coord_status(db, u, cid, status))


@pages.post("/coordinator/cases/{cid}/cancel")
def p_coord_cancel(cid: int, request: Request, db=Depends(get_db)):
    u = who(request, db, "coordinator")
    return act(db, f"/coordinator/cases/{cid}", lambda: svc.cancel_case(db, u, cid))


@pages.post("/coordinator/cases/{cid}/share")
def p_coord_share(cid: int, request: Request, clinic_id: int = Form(...), db=Depends(get_db)):
    u = who(request, db, "coordinator")
    return act(db, f"/coordinator/cases/{cid}", lambda: svc.request_share(db, u, cid, clinic_id))


# --- клиника -------------------------------------------------------------------
@pages.get("/clinic")
def p_clinic(request: Request, db=Depends(get_db)):
    u = who(request, db, "clinic")
    ok = select(CaseShare.case_id).where(CaseShare.clinic_id.in_(svc.user_clinics(db, u)), CaseShare.consent_status == "approved")
    rows = db.execute(select(Case, Specialty).join(Specialty, Specialty.id == Case.specialty_id)
                      .where(Case.id.in_(ok)).order_by(Case.id.desc())).all()
    return render(request, db, "cases_list.html", u, title="Согласованные кейсы", new=False, status=None,
                  rows=[{"c": c, "spec": s.name, "url": f"/clinic/cases/{c.id}", "extra": c.target_country or "—"} for c, s in rows])


@pages.get("/clinic/cases/{cid}")
def p_clinic_case(cid: int, request: Request, db=Depends(get_db)):
    u = who(request, db, "clinic")
    return render(request, db, "case_detail.html", u, **case_ctx(db, u, cid))


@pages.post("/clinic/cases/{cid}/quote")
def p_quote(cid: int, request: Request, share_id: int = Form(...), currency: str = Form("USD"), price_min: int = Form(...),
            price_max: int = Form(...), details: str = Form(...), valid_until: str = Form(...), db=Depends(get_db)):
    u = who(request, db, "clinic")
    return act(db, f"/clinic/cases/{cid}", lambda: svc.add_offer(db, u, cid, QuoteIn(
        share_id=share_id, currency=currency.upper(), price_min=price_min, price_max=price_max,
        details=details, valid_until=valid_until)))


# --- администратор и модерация ---------------------------------------------------
def admin_view(request, db, u, **extra):
    clinics = [svc.clinic_card(db, c) for c in db.scalars(select(Clinic).order_by(Clinic.id))]
    return render(request, db, "admin.html", u, m=svc.metrics(db), clinics=clinics,
                  users=db.scalars(select(User).order_by(User.id).limit(300)).all(),
                  specs=db.scalars(select(Specialty).order_by(Specialty.name)).all(), **extra)


@pages.get("/admin")
def p_admin(request: Request, db=Depends(get_db)):
    return admin_view(request, db, who(request, db, "admin"))


@pages.post("/admin/clinics")
def p_clinic_new(request: Request, name: str = Form(...), country: str = Form(...), city: str = Form(...),
                 description: str = Form(""), image_url: str = Form(""), specialty_ids: list[int] = Form([]),
                 db=Depends(get_db)):
    u = who(request, db, "admin")
    return act(db, "/admin", lambda: svc.save_clinic(db, u, None, ClinicIn(
        name=name, country=country, city=city, description=description, specialty_ids=specialty_ids,
        image_url=image_url or None).model_dump()))


@pages.post("/admin/clinics/{clinic_id}")
def p_clinic_edit(clinic_id: int, request: Request, verification_status: str = Form(...), image_url: str = Form(""),
                  back: str = Form("/admin"), db=Depends(get_db)):
    u = who(request, db, "admin")
    back = back if back in ("/admin", "/admin/moderation") else "/admin"
    return act(db, back, lambda: svc.save_clinic(db, u, clinic_id, ClinicPatch(
        verification_status=verification_status, image_url=image_url or None).model_dump(exclude_unset=True)))


@pages.post("/admin/staff")
def p_staff(request: Request, email: str = Form(...), full_name: str = Form(...), role: str = Form(...),
            clinic_id: str = Form(""), db=Depends(get_db)):
    u = who(request, db, "admin")
    try:
        res = svc.create_staff(db, u, StaffIn(email=email, full_name=full_name, role=role,
                                              clinic_id=int(clinic_id) if clinic_id else None))
        return admin_view(request, db, u, note=f"Создан {res['email']}. Временный пароль (показывается один раз): {res['temp_password']}")
    except (ApiError, ValidationError) as e:
        db.rollback()
        return admin_view(request, db, u, err=e.message if isinstance(e, ApiError) else "Проверьте заполнение полей")


@pages.post("/admin/users/{uid}/active")
def p_user_active(uid: int, request: Request, active: str = Form(...), db=Depends(get_db)):
    u = who(request, db, "admin")
    return act(db, "/admin", lambda: svc.set_active(db, u, uid, active == "1"))


@pages.get("/admin/moderation")
def p_moderation(request: Request, db=Depends(get_db)):
    u = who(request, db, "admin")
    pending = [svc.clinic_card(db, c) for c in db.scalars(select(Clinic).where(Clinic.verification_status == "pending"))]
    offers = db.execute(select(Offer, Clinic, CaseShare).join(CaseShare, Offer.share_id == CaseShare.id)
                        .join(Clinic, Clinic.id == CaseShare.clinic_id).where(Offer.status == "active")
                        .order_by(Offer.id.desc()).limit(100)).all()
    log = db.execute(select(AuditLog, User.email).join(User, User.id == AuditLog.actor_user_id, isouter=True)
                     .order_by(AuditLog.id.desc()).limit(60)).all()
    return render(request, db, "moderation.html", u, pending=pending, offers=offers, log=log)


@pages.post("/admin/moderation/offers/{oid}/cancel")
def p_offer_cancel(oid: int, request: Request, db=Depends(get_db)):
    u = who(request, db, "admin")
    return act(db, "/admin/moderation", lambda: svc.moderate_offer(db, u, oid))
