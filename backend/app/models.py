from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import String, ForeignKey, Integer, Boolean, DateTime, Text, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    full_name: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str] = mapped_column(String(50), default='')
    role: Mapped[str] = mapped_column(String(25), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Clinic(Base):
    __tablename__ = 'clinics'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    country: Mapped[str] = mapped_column(String(100), index=True)
    city: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default='')
    verification_status: Mapped[str] = mapped_column(String(20), default='pending')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ClinicImage(Base):
    """НОВАЯ таблица: картинки клиник в облаке. url = полный https-адрес или ключ объекта
    (тогда к нему добавляется CLOUD_MEDIA_BASE_URL). Существующие таблицы не меняются."""
    __tablename__ = 'clinic_images'
    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int] = mapped_column(ForeignKey('clinics.id'), index=True)
    url: Mapped[str] = mapped_column(String(500))
    is_cover: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Specialty(Base):
    __tablename__ = 'specialties'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    slug: Mapped[str] = mapped_column(String(150), unique=True)


class ClinicSpecialty(Base):
    __tablename__ = 'clinic_specialties'
    clinic_id: Mapped[int] = mapped_column(ForeignKey('clinics.id'), primary_key=True)
    specialty_id: Mapped[int] = mapped_column(ForeignKey('specialties.id'), primary_key=True)


class ClinicMembership(Base):
    __tablename__ = 'clinic_memberships'
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), primary_key=True)
    clinic_id: Mapped[int] = mapped_column(ForeignKey('clinics.id'), primary_key=True)


class Case(Base):
    __tablename__ = 'cases'
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    specialty_id: Mapped[int] = mapped_column(ForeignKey('specialties.id'))
    description: Mapped[str] = mapped_column(Text)
    target_country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    budget_usd: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default='draft', index=True)
    selected_offer_id: Mapped[int | None] = mapped_column(ForeignKey('offers.id', use_alter=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class CaseDocument(Base):
    __tablename__ = 'case_documents'
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey('cases.id'), index=True)
    uploader_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    file_key: Mapped[str] = mapped_column(String(100), unique=True)
    file_name: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(60))
    size_bytes: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CaseShare(Base):
    __tablename__ = 'case_shares'
    __table_args__ = (UniqueConstraint('case_id', 'clinic_id', name='uq_case_clinic'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey('cases.id'), index=True)
    clinic_id: Mapped[int] = mapped_column(ForeignKey('clinics.id'))
    consent_status: Mapped[str] = mapped_column(String(20), default='pending')
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Offer(Base):
    __tablename__ = 'offers'
    __table_args__ = (CheckConstraint('price_min <= price_max', name='ck_offer_range'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    share_id: Mapped[int] = mapped_column(ForeignKey('case_shares.id'), index=True)
    currency: Mapped[str] = mapped_column(String(3), default='USD')
    price_min: Mapped[int] = mapped_column(Integer)
    price_max: Mapped[int] = mapped_column(Integer)
    details: Mapped[str] = mapped_column(Text)
    valid_until: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), default='active')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Conversation(Base):
    __tablename__ = 'conversations'
    id: Mapped[int] = mapped_column(primary_key=True)
    share_id: Mapped[int] = mapped_column(ForeignKey('case_shares.id'), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Message(Base):
    __tablename__ = 'messages'
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey('conversations.id'), index=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Notification(Base):
    __tablename__ = 'notifications'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    type: Mapped[str] = mapped_column(String(40))
    text: Mapped[str] = mapped_column(Text)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AuditLog(Base):
    __tablename__ = 'audit_logs'
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    action: Mapped[str] = mapped_column(String(70))
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[int] = mapped_column(Integer)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class RefreshSession(Base):
    __tablename__ = 'refresh_sessions'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
