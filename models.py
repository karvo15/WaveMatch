"""
Pydantic models for WaveMatch database tables.
Each model mirrors the corresponding table schema exactly.
"""
from datetime import date, datetime
from typing import Optional, Dict, Any, List
from uuid import UUID
from pydantic import BaseModel, Field
from enum import Enum


# ============================================================
# ENUM-TYPE MODELS (for better type safety)
# ============================================================
class PosterStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"

class OpportunityStatus(str, Enum):
    active = "active"
    expired = "expired"
    edited = "edited"
    pending_approval = "pending_approval"
    rejected = "rejected"

class ApplicationStatus(str, Enum):
    available = "available"
    ongoing = "ongoing"
    under_review = "under_review"
    scheduled = "scheduled"

class ApplicationOutcome(str, Enum):
    yes = "yes"
    no = "no"
    waiting = "waiting"


# ============================================================
# TAGS
# ============================================================
class TagBase(BaseModel):
    name: str
    is_custom: bool = False


class TagCreate(TagBase):
    pass


class TagUpdate(BaseModel):
    name: Optional[str] = None
    is_custom: Optional[bool] = None


class TagInDBBase(TagBase):
    id: UUID
    created_at: datetime


class Tag(TagInDBBase):
    pass


# ============================================================
# USERS
# ============================================================
class UserBase(BaseModel):
    phone_number: str
    name: Optional[str] = None


class UserCreate(UserBase):
    pass


class UserUpdate(BaseModel):
    phone_number: Optional[str] = None
    name: Optional[str] = None


class UserInDBBase(UserBase):
    id: UUID
    created_at: datetime


class User(UserInDBBase):
    pass


# ============================================================
# USER_TAGS (junction table)
# ============================================================
class UserTagBase(BaseModel):
    user_id: UUID
    tag_id: UUID


class UserTagCreate(UserTagBase):
    pass


class UserTagUpdate(BaseModel):
    user_id: Optional[UUID] = None
    tag_id: Optional[UUID] = None


class UserTagInDBBase(UserTagBase):
    pass


class UserTag(UserTagInDBBase):
    pass


# ============================================================
# POSTERS
# ============================================================
class PosterBase(BaseModel):
    phone_number: str
    display_name: str
    status: PosterStatus = PosterStatus.pending  # pending, approved, rejected
    requires_post_approval: bool = False  # admin toggle for per-post approval


class PosterCreate(PosterBase):
    pass


class PosterUpdate(BaseModel):
    phone_number: Optional[str] = None
    display_name: Optional[str] = None
    status: Optional[PosterStatus] = None


class PosterInDBBase(PosterBase):
    id: UUID
    created_at: datetime


class Poster(PosterInDBBase):
    pass


# ============================================================
# OPPORTUNITIES
# ============================================================
class OpportunityBase(BaseModel):
    poster_id: UUID
    title: str
    description: Optional[str] = None
    type: str  # meeting, volunteering, event, scholarship, other
    application_start_date: Optional[date] = None  # DATE field
    application_deadline: date  # DATE NOT NULL
    result_date: Optional[date] = None  # DATE field
    event_start_date: Optional[date] = None  # DATE field
    link: str
    status: OpportunityStatus = OpportunityStatus.active  # active, expired, edited


class OpportunityCreate(OpportunityBase):
    pass


class OpportunityUpdate(BaseModel):
    poster_id: Optional[UUID] = None
    title: Optional[str] = None
    description: Optional[str] = None
    type: Optional[str] = None
    application_start_date: Optional[date] = None
    application_deadline: Optional[date] = None
    result_date: Optional[date] = None
    event_start_date: Optional[date] = None
    link: Optional[str] = None
    status: Optional[OpportunityStatus] = None


class OpportunityInDBBase(OpportunityBase):
    id: UUID
    created_at: datetime
    updated_at: datetime


class Opportunity(OpportunityInDBBase):
    pass


# ============================================================
# OPPORTUNITY_TAGS (junction table)
# ============================================================
class OpportunityTagBase(BaseModel):
    opportunity_id: UUID
    tag_id: UUID


class OpportunityTagCreate(OpportunityTagBase):
    pass


class OpportunityTagUpdate(BaseModel):
    opportunity_id: Optional[UUID] = None
    tag_id: Optional[UUID] = None


class OpportunityTagInDBBase(OpportunityTagBase):
    pass


class OpportunityTag(OpportunityTagInDBBase):
    pass


# ============================================================
# CONVERSATION STATES
# ============================================================
class ConversationStateBase(BaseModel):
    phone_number: str
    current_flow: str  # e.g. 'register_poster', 'register_user', 'post_opportunity', 'edit_opportunity', 'manual_add'
    current_step: str  # e.g. 'awaiting_display_name', 'awaiting_tags', 'awaiting_deadline'
    collected_data: Dict[str, Any] = Field(default_factory=dict)


class ConversationStateCreate(ConversationStateBase):
    pass


class ConversationStateUpdate(BaseModel):
    phone_number: Optional[str] = None
    current_flow: Optional[str] = None
    current_step: Optional[str] = None
    collected_data: Optional[Dict[str, Any]] = None


class ConversationStateInDBBase(ConversationStateBase):
    created_at: datetime
    updated_at: datetime


class ConversationState(ConversationStateInDBBase):
    pass


# ============================================================
# APPLICATIONS
# ============================================================
class ApplicationBase(BaseModel):
    user_id: UUID
    opportunity_id: Optional[UUID] = None  # NULL if manually added by the user
    custom_title: Optional[str] = None  # used only when opportunity_id IS NULL
    custom_description: Optional[str] = None
    status: ApplicationStatus = ApplicationStatus.available  # available, ongoing, under_review, scheduled
    next_reminder_at: Optional[datetime] = None  # TIMESTAMPTZ
    reminder_interval_days: int = 2
    deadline_heads_up_sent: bool = False
    outcome: Optional[ApplicationOutcome] = None  # yes, no, waiting
    scheduled_event_date: Optional[date] = None  # DATE
    # for manually-added items, since there's no linked opportunity row:
    custom_deadline: Optional[date] = None  # DATE
    custom_result_date: Optional[date] = None  # DATE


class ApplicationCreate(ApplicationBase):
    pass


class ApplicationUpdate(BaseModel):
    user_id: Optional[UUID] = None
    opportunity_id: Optional[UUID] = None
    custom_title: Optional[str] = None
    custom_description: Optional[str] = None
    status: Optional[ApplicationStatus] = None
    next_reminder_at: Optional[datetime] = None
    reminder_interval_days: Optional[int] = None
    deadline_heads_up_sent: Optional[bool] = None
    outcome: Optional[ApplicationOutcome] = None
    scheduled_event_date: Optional[date] = None
    custom_deadline: Optional[date] = None
    custom_result_date: Optional[date] = None


class ApplicationInDBBase(ApplicationBase):
    id: UUID
    created_at: datetime
    updated_at: datetime


class Application(ApplicationInDBBase):
    pass


# ============================================================
# HELPER VIEWS (for convenience, not direct DB tables)
# ============================================================
# Note: applications_with_effective_dates is a VIEW, not a table
# We'll create a model for it for convenience when querying
class ApplicationWithEffectiveDates(Application):
    effective_deadline: Optional[date] = None
    effective_result_date: Optional[date] = None
    effective_event_start_date: Optional[date] = None