"""Вся бизнес-логика. Роутеры (REST) и HTML-дашборды вызывают только эти функции."""
import os
import secrets
from datetime import date, datetime, timezone

from sqlalchemy import delete, func, select

from .core import MAX_FILE, UPLOAD_DIR, ApiError, hash_pw, media_url
from .models import *  # noqa: F403

TRANSITIONS = {
    "draft": {"submitted", "cancelled"}, "submitted": {"in_review", "cancelled"},
    "in_review": {"awaiting_clinic", "cancelled"}, "awaiting_clinic": {"offers_received", "cancelled"},
    "offers_received": {"selected", "cancelled"}, "selected": {"closed"}, "closed": set(), "cancelled": set(),
}
COORD_MOVES = {("submitted", "in_review"), ("selected", "closed")}
RU = {
    "draft": "Черновик", "submitted": "Отправлена", "in_review": "На проверке", "awaiting_clinic": "Ждём клинику",
    "offers_received": "Есть сметы", "selected": "Смета выбрана", "closed": "Закрыта", "cancelled": "Отменена",
    "pending": "Ожидает", "approved": "Одобрено", "rejected": "Отклонено", "revoked": "Отозвано",
    "verified": "Проверена", "active": "Действует", "patient": "Пациент", "coordinator": "Координатор",
    "clinic": "Клиника", "admin": "Администратор",
}
EXT = {"application/pdf": ".pdf", "image/jpeg": ".jpg", "image/png": ".png"}
MAGIC = {"application/pdf": b"%PDF", "image/jpeg": b"\xff\xd8\xff", "image/png": b"\x89PNG"}


def NF(m="Не найдено"):
    return ApiError(404, "NOT_FOUND", m)


def d(o, drop=()):
    out = {}
    for c in o.__table__.columns:
        if c.name in drop or c.name in ("password_hash", "token_hash"):
            continue
        v = getattr(o, c.name)
        if isinstance(v, datetime):
            v = (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).isoformat()
        out[c.name] = v
    return out


def paged(db, q, page, limit, conv=d):
    total = db.scalar(select(func.count()).select_from(q.order_by(None).subquery()))
    rows = db.scalars(q.limit(limit).offset((page - 1) * limit)).all()
    return {"items": [conv(x) for x in rows], "page": page, "limit": limit, "total": total}


def audit(db, uid, action, etype, eid):
    db.add(AuditLog(actor_user_id=uid, action=action, entity_type=etype, entity_id=eid))


def notify(db, uid, typ, text):
    db.add(Notification(user_id=uid, type=typ, text=text))


def staff_of(db, clinic_id):
    return db.scalars(select(ClinicMembership.user_id).where(ClinicMembership.clinic_id == clinic_id)).all()


def user_clinics(db, u):
    return db.scalars(select(ClinicMembership.clinic_id).where(ClinicMembership.user_id == u.id)).all()


# --- доступ и статусы ------------------------------------------------------
def approved_shares(db, case_id, clinic_ids):
    if not clinic_ids:
        return []
    return db.scalars(select(CaseShare).where(
        CaseShare.case_id == case_id, CaseShare.clinic_id.in_(clinic_ids), CaseShare.consent_status == "approved")).all()


def get_case(db, u, cid, lock=False):
    c = db.get(Case, cid, with_for_update=lock)
    if not c:
        raise NF()
    if u.role == "patient":
        if c.patient_id != u.id:
            raise NF()
    elif u.role == "clinic":
        if not approved_shares(db, cid, user_clinics(db, u)):
            raise ApiError(403, "FORBIDDEN", "Нет согласия пациента на передачу кейса")
    elif u.role != "coordinator" or c.status == "draft":
        raise NF()
    return c


def move(db, c, new, actor_id):
    if new not in TRANSITIONS[c.status]:
        raise ApiError(409, "INVALID_STATUS_TRANSITION", f"Нельзя перейти из «{RU[c.status]}» в «{RU.get(new, new)}»")
    audit(db, actor_id, f"case.status:{c.status}->{new}", "case", c.id)
    c.status = new
    notify(db, c.patient_id, "status", f"Заявка №{c.id}: {RU[new]}")


# --- заявки ------------------------------------------------------------------
def create_case(db, u, b):
    if not db.get(Specialty, b.specialty_id):
        raise ApiError(422, "VALIDATION_ERROR", "Неизвестная специализация")
    c = Case(patient_id=u.id, **b.model_dump())
    db.add(c)
    db.flush()
    audit(db, u.id, "case.create", "case", c.id)
    db.commit()
    return d(c)


def patch_case(db, u, cid, b):
    c = get_case(db, u, cid)
    if c.status != "draft":
        raise ApiError(409, "CASE_NOT_EDITABLE", "Редактировать можно только черновик")
    data = {k: v for k, v in b.model_dump(exclude_unset=True).items() if v is not None or k in ("target_country", "budget_usd")}
    if "specialty_id" in data and not db.get(Specialty, data["specialty_id"]):
        raise ApiError(422, "VALIDATION_ERROR", "Неизвестная специализация")
    for k, v in data.items():
        setattr(c, k, v)
    db.commit()
    return d(c)


def submit_case(db, u, cid):
    c = get_case(db, u, cid)
    if not c.description.strip():
        raise ApiError(422, "VALIDATION_ERROR", "Заполните описание")
    move(db, c, "submitted", u.id)
    db.commit()
    return {"id": c.id, "status": c.status}


def cancel_case(db, u, cid):
    c = get_case(db, u, cid)
    move(db, c, "cancelled", u.id)
    db.commit()
    return {"id": c.id, "status": c.status}


def coord_status(db, u, cid, new):
    c = get_case(db, u, cid)
    if new != "cancelled" and (c.status, new) not in COORD_MOVES:
        raise ApiError(409, "INVALID_STATUS_TRANSITION", "Координатор может: взять в работу, закрыть, отменить")
    move(db, c, new, u.id)
    db.commit()
    return {"id": c.id, "status": c.status}


# --- документы ---------------------------------------------------------------
def add_doc(db, u, cid, name, mime, data):
    c = get_case(db, u, cid)
    if c.status in ("closed", "cancelled"):
        raise ApiError(409, "CASE_NOT_EDITABLE", "Заявка завершена")
    if len(data) > MAX_FILE:
        raise ApiError(413, "FILE_TOO_LARGE", "Файл больше 10 МБ")
    if mime not in EXT or not data.startswith(MAGIC[mime]):
        raise ApiError(415, "UNSUPPORTED_MEDIA_TYPE", "Допустимы только PDF, JPG, PNG")
    key = secrets.token_hex(16) + EXT[mime]
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    with open(os.path.join(UPLOAD_DIR, key), "wb") as f:
        f.write(data)
    doc = CaseDocument(case_id=c.id, uploader_id=u.id, file_key=key, file_name=os.path.basename(name or "file")[:255],
                       mime_type=mime, size_bytes=len(data))
    db.add(doc)
    db.flush()
    audit(db, u.id, "document.upload", "document", doc.id)
    db.commit()
    return d(doc, drop=("file_key",))


def docs_of(db, u, cid):
    get_case(db, u, cid)
    rows = db.scalars(select(CaseDocument).where(CaseDocument.case_id == cid).order_by(CaseDocument.id)).all()
    return [d(x, drop=("file_key",)) for x in rows]


def doc_file(db, u, cid, did):
    get_case(db, u, cid)
    doc = db.get(CaseDocument, did)
    if not doc or doc.case_id != cid:
        raise NF()
    audit(db, u.id, "document.download", "document", doc.id)
    db.commit()
    return os.path.join(UPLOAD_DIR, doc.file_key), doc


def del_doc(db, u, cid, did):
    get_case(db, u, cid)
    doc = db.get(CaseDocument, did)
    if not doc or doc.case_id != cid:
        raise NF()
    try:
        os.remove(os.path.join(UPLOAD_DIR, doc.file_key))
    except OSError:
        pass
    audit(db, u.id, "document.delete", "document", doc.id)
    db.delete(doc)
    db.commit()


# --- согласия ----------------------------------------------------------------
def request_share(db, u, cid, clinic_id):
    c = get_case(db, u, cid)
    if c.status not in ("in_review", "awaiting_clinic", "offers_received"):
        raise ApiError(409, "INVALID_STATUS_TRANSITION", "Сначала возьмите заявку в работу")
    cl = db.get(Clinic, clinic_id)
    if not cl or cl.verification_status != "verified":
        raise ApiError(400, "CLINIC_NOT_VERIFIED", "Клиника не проверена администратором")
    if db.scalar(select(CaseShare).where(CaseShare.case_id == cid, CaseShare.clinic_id == clinic_id)):
        raise ApiError(409, "SHARE_EXISTS", "Запрос этой клинике уже создавался")
    s = CaseShare(case_id=cid, clinic_id=clinic_id)
    db.add(s)
    db.flush()
    audit(db, u.id, "share.request", "share", s.id)
    notify(db, c.patient_id, "consent", f"Заявка №{cid}: подтвердите передачу данных в «{cl.name}»")
    db.commit()
    return d(s)


def consent(db, u, cid, sid, approved):
    c = get_case(db, u, cid)
    s = db.get(CaseShare, sid)
    if not s or s.case_id != cid:
        raise NF()
    if s.consent_status != "pending":
        raise ApiError(409, "CONSENT_ALREADY_SET", "Решение уже принято")
    s.consent_status, s.consent_at = ("approved" if approved else "rejected"), datetime.now(timezone.utc)
    audit(db, u.id, f"consent.{s.consent_status}", "share", s.id)
    if approved:
        db.add(Conversation(share_id=s.id))
        if c.status == "in_review":
            move(db, c, "awaiting_clinic", u.id)
        for uid in staff_of(db, s.clinic_id):
            notify(db, uid, "case", f"Новый согласованный кейс №{cid}")
    db.commit()
    return {"id": s.id, "consent_status": s.consent_status, "case_id": cid}


def revoke(db, u, cid, sid):
    get_case(db, u, cid)
    s = db.get(CaseShare, sid)
    if not s or s.case_id != cid:
        raise NF()
    if s.consent_status != "approved":
        raise ApiError(409, "CONSENT_NOT_ACTIVE", "Согласие не действует")
    s.consent_status = "revoked"
    for o in db.scalars(select(Offer).where(Offer.share_id == sid, Offer.status == "active")):
        o.status = "cancelled"
    audit(db, u.id, "consent.revoked", "share", s.id)
    db.commit()
    return {"id": s.id, "consent_status": s.consent_status, "case_id": cid}


def shares_of(db, u, cid):
    get_case(db, u, cid)
    rows = db.execute(select(CaseShare, Clinic).join(Clinic, Clinic.id == CaseShare.clinic_id)
                      .where(CaseShare.case_id == cid).order_by(CaseShare.id)).all()
    return [(s, cl) for s, cl in rows]


# --- сметы -------------------------------------------------------------------
def add_offer(db, u, cid, b):
    c = get_case(db, u, cid)
    s = db.get(CaseShare, b.share_id)
    if not s or s.case_id != cid or s.clinic_id not in user_clinics(db, u) or s.consent_status != "approved":
        raise ApiError(403, "FORBIDDEN", "Нет согласованной передачи для этой клиники")
    if c.status not in ("awaiting_clinic", "offers_received"):
        raise ApiError(409, "INVALID_STATUS_TRANSITION", "Заявка сейчас не принимает сметы")
    if b.valid_until < date.today().isoformat():
        raise ApiError(400, "VALID_UNTIL_PAST", "Срок действия уже истёк")
    o = Offer(**b.model_dump())
    db.add(o)
    db.flush()
    audit(db, u.id, "offer.create", "offer", o.id)
    notify(db, c.patient_id, "offer", f"Заявка №{cid}: новая предварительная смета")
    if c.status == "awaiting_clinic":
        move(db, c, "offers_received", u.id)
    db.commit()
    return d(o)


def patch_offer(db, u, qid, b):
    o = db.get(Offer, qid)
    s = db.get(CaseShare, o.share_id) if o else None
    if not s or s.clinic_id not in user_clinics(db, u):
        raise NF()
    if o.status != "active":
        raise ApiError(409, "QUOTE_NOT_AVAILABLE", "Смета больше не действует")
    for k, v in b.model_dump(exclude_none=True).items():
        setattr(o, k, v)
    if o.price_min > o.price_max:
        raise ApiError(422, "VALIDATION_ERROR", "price_min не может быть больше price_max")
    audit(db, u.id, "offer.update", "offer", o.id)
    db.commit()
    return d(o)


def offers_of(db, u, cid):
    get_case(db, u, cid)
    q = (select(Offer, Clinic).join(CaseShare, Offer.share_id == CaseShare.id)
         .join(Clinic, CaseShare.clinic_id == Clinic.id).where(CaseShare.case_id == cid).order_by(Offer.id))
    if u.role == "clinic":
        q = q.where(CaseShare.clinic_id.in_(user_clinics(db, u)))
    today = date.today().isoformat()
    return [{**d(o), "clinic_id": cl.id, "clinic_name": cl.name, "expired": o.valid_until < today}
            for o, cl in db.execute(q)]


def select_offer(db, u, cid, oid):
    c = get_case(db, u, cid, lock=True)  # блокировка строки: два параллельных выбора не пройдут
    o = db.get(Offer, oid)
    s = db.get(CaseShare, o.share_id) if o else None
    if not s or s.case_id != cid or s.consent_status != "approved":
        raise NF()
    if c.selected_offer_id or c.status != "offers_received":
        raise ApiError(409, "INVALID_STATUS_TRANSITION", "Смета по этой заявке уже выбрана или выбор недоступен")
    if o.status != "active" or o.valid_until < date.today().isoformat():
        raise ApiError(409, "QUOTE_NOT_AVAILABLE", "Смета отменена или устарела")
    o.status, c.selected_offer_id = "selected", o.id
    move(db, c, "selected", u.id)
    audit(db, u.id, "offer.select", "offer", o.id)
    for uid in staff_of(db, s.clinic_id):
        notify(db, uid, "offer", f"Пациент выбрал вашу смету по кейсу №{cid}")
    db.commit()
    return {"id": c.id, "status": c.status, "selected_offer_id": o.id}


def moderate_offer(db, u, oid):
    o = db.get(Offer, oid)
    if not o or o.status != "active":
        raise ApiError(409, "QUOTE_NOT_AVAILABLE", "Смета уже не действует")
    s = db.get(CaseShare, o.share_id)
    o.status = "cancelled"
    audit(db, u.id, "offer.moderate_cancel", "offer", o.id)
    for uid in staff_of(db, s.clinic_id):
        notify(db, uid, "offer", f"Смета по кейсу №{s.case_id} отменена модератором")
    db.commit()


# --- сообщения ---------------------------------------------------------------
def get_conv(db, u, cid, vid):
    c = get_case(db, u, cid)
    cv = db.get(Conversation, vid)
    s = db.get(CaseShare, cv.share_id) if cv else None
    if not s or s.case_id != cid:
        raise NF()
    if s.consent_status != "approved" or (u.role == "clinic" and s.clinic_id not in user_clinics(db, u)):
        raise ApiError(403, "FORBIDDEN", "Нет доступа к диалогу")
    return c, s


def convs_of(db, u, cid):
    get_case(db, u, cid)
    q = (select(Conversation, Clinic).join(CaseShare, Conversation.share_id == CaseShare.id)
         .join(Clinic, Clinic.id == CaseShare.clinic_id)
         .where(CaseShare.case_id == cid, CaseShare.consent_status == "approved"))
    if u.role == "clinic":
        q = q.where(CaseShare.clinic_id.in_(user_clinics(db, u)))
    return [{"id": cv.id, "share_id": cv.share_id, "clinic_name": cl.name} for cv, cl in db.execute(q)]


def msgs_of(db, u, cid, vid, page, limit):
    get_conv(db, u, cid, vid)
    q = select(Message).where(Message.conversation_id == vid).order_by(Message.id)
    names = {}
    res = paged(db, q, page, limit, lambda m: {**d(m), "mine": m.sender_id == u.id})
    for m in res["items"]:
        names[m["sender_id"]] = names.get(m["sender_id"]) or db.get(User, m["sender_id"]).full_name
        m["sender_name"] = names[m["sender_id"]]
    return res


def send_msg(db, u, cid, vid, body):
    c, s = get_conv(db, u, cid, vid)
    m = Message(conversation_id=vid, sender_id=u.id, body=body)
    db.add(m)
    db.flush()
    for uid in ([c.patient_id] if u.role != "patient" else staff_of(db, s.clinic_id)):
        notify(db, uid, "message", f"Новое сообщение по заявке №{cid}")
    db.commit()
    return {**d(m), "mine": True, "sender_name": u.full_name}


# --- клиники, админ ----------------------------------------------------------
def clinic_card(db, c):
    specs = db.scalars(select(Specialty).join(ClinicSpecialty, ClinicSpecialty.specialty_id == Specialty.id)
                       .where(ClinicSpecialty.clinic_id == c.id)).all()
    imgs = [media_url(i.url) for i in db.scalars(select(ClinicImage).where(ClinicImage.clinic_id == c.id)
                                                 .order_by(ClinicImage.is_cover.desc(), ClinicImage.id))]
    imgs = [i for i in imgs if i]
    return {**d(c), "specialties": [d(s) for s in specs], "images": imgs, "cover": imgs[0] if imgs else None}


def save_clinic(db, u, cid, data):
    if cid is None:
        c = Clinic(name=data["name"], country=data["country"], city=data["city"], description=data.get("description") or "")
        db.add(c)
        db.flush()
        audit(db, u.id, "clinic.create", "clinic", c.id)
    else:
        c = db.get(Clinic, cid)
        if not c:
            raise NF()
        for k in ("name", "country", "city", "description"):
            if data.get(k) is not None:
                setattr(c, k, data[k])
    if data.get("verification_status"):
        c.verification_status = data["verification_status"]
        audit(db, u.id, f"clinic.{c.verification_status}", "clinic", c.id)
    if data.get("specialty_ids") is not None:
        db.execute(delete(ClinicSpecialty).where(ClinicSpecialty.clinic_id == c.id))
        for sid in set(data["specialty_ids"]):
            if not db.get(Specialty, sid):
                raise ApiError(422, "VALIDATION_ERROR", f"Неизвестная специализация {sid}")
            db.add(ClinicSpecialty(clinic_id=c.id, specialty_id=sid))
    if data.get("image_url"):
        db.execute(delete(ClinicImage).where(ClinicImage.clinic_id == c.id))
        db.add(ClinicImage(clinic_id=c.id, url=data["image_url"].strip(), is_cover=True))
    db.commit()
    return clinic_card(db, c)


def create_staff(db, u, b):
    if db.scalar(select(User).where(User.email == b.email.lower())):
        raise ApiError(409, "EMAIL_TAKEN", "Email уже зарегистрирован")
    if b.role == "clinic" and not (b.clinic_id and db.get(Clinic, b.clinic_id)):
        raise ApiError(422, "VALIDATION_ERROR", "Для сотрудника клиники выберите клинику")
    pw = b.password or secrets.token_urlsafe(9)
    nu = User(email=b.email.lower(), password_hash=hash_pw(pw), full_name=b.full_name, phone="", role=b.role)
    db.add(nu)
    db.flush()
    if b.role == "clinic":
        db.add(ClinicMembership(user_id=nu.id, clinic_id=b.clinic_id))
    audit(db, u.id, "user.create_staff", "user", nu.id)
    db.commit()
    return {"id": nu.id, "email": nu.email, "role": nu.role, "temp_password": pw}


def set_active(db, u, uid, active):
    t = db.get(User, uid)
    if not t:
        raise NF()
    if t.id == u.id:
        raise ApiError(409, "SELF_BLOCK", "Нельзя заблокировать себя")
    t.is_active = active
    audit(db, u.id, "user.unblock" if active else "user.block", "user", t.id)
    db.commit()
    return d(t)


def metrics(db, f=None, t=None):
    def rng(col, q):
        q = q.where(col >= f) if f else q
        return q.where(col <= t) if t else q

    n = lambda q: db.scalar(q) or 0  # noqa: E731
    pct = lambda a, b: round(100 * a / b, 1) if b else 0  # noqa: E731
    cases = n(rng(Case.created_at, select(func.count(Case.id))))
    sub = n(rng(Case.created_at, select(func.count(Case.id)).where(Case.status != "draft")))
    sh = n(rng(CaseShare.created_at, select(func.count(CaseShare.id))))
    sh_ok = n(rng(CaseShare.created_at, select(func.count(CaseShare.id)).where(CaseShare.consent_status.in_(("approved", "revoked")))))
    with_offer = n(rng(Case.created_at, select(func.count(func.distinct(CaseShare.case_id))).select_from(CaseShare)
                       .join(Offer, Offer.share_id == CaseShare.id).join(Case, Case.id == CaseShare.case_id)))
    chosen = n(rng(Case.created_at, select(func.count(Case.id)).where(Case.status.in_(("selected", "closed")))))
    sub_at = {a.entity_id: a.occurred_at for a in db.scalars(select(AuditLog).where(AuditLog.action == "case.status:draft->submitted"))}
    first = db.execute(select(CaseShare.case_id, func.min(Offer.created_at)).join(Offer, Offer.share_id == CaseShare.id)
                       .group_by(CaseShare.case_id)).all()
    hrs = [(t0 - sub_at[c]).total_seconds() / 3600 for c, t0 in first if c in sub_at]
    return {"cases": cases, "submitted": sub, "share_requests": sh, "shares_approved": sh_ok,
            "consent_rate": pct(sh_ok, sh), "offer_rate": pct(with_offer, sub), "select_rate": pct(chosen, sub),
            "avg_hours_to_offer": round(sum(hrs) / len(hrs), 2) if hrs else None}
