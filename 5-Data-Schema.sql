-- WaveMatch — Database Schema (PostgreSQL / Supabase)
-- Run this in the Supabase SQL Editor to create the full schema.
-- Row Level Security (RLS) is enabled on all tables; since the backend
-- talks to Supabase using the service_role key, it bypasses RLS by
-- design — these policies exist as a safety net, not the primary access
-- control mechanism.

-- ============================================================
-- TAGS
-- ============================================================
CREATE TABLE tags (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    is_custom BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- USERS
-- ============================================================
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    phone_number TEXT NOT NULL UNIQUE,
    name TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE user_tags (
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tag_id UUID NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, tag_id)
);

-- ============================================================
-- POSTERS
-- ============================================================
CREATE TYPE poster_status AS ENUM ('pending', 'approved', 'rejected');

CREATE TABLE posters (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    phone_number TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    status poster_status NOT NULL DEFAULT 'pending',
    requires_post_approval BOOLEAN NOT NULL DEFAULT false,  -- admin toggle for per-post approval
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- OPPORTUNITIES
-- ============================================================
CREATE TYPE opportunity_status AS ENUM ('active', 'expired', 'edited', 'pending_approval', 'rejected');

CREATE TABLE opportunities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    poster_id UUID NOT NULL REFERENCES posters(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT,
    type TEXT, -- meeting, volunteering, event, scholarship, other (free text, not enum, for flexibility)
    application_start_date DATE,
    application_deadline DATE NOT NULL,
    result_date DATE,
    event_start_date DATE,
    link TEXT NOT NULL,
    status opportunity_status NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE opportunity_tags (
    opportunity_id UUID NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
    tag_id UUID NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (opportunity_id, tag_id)
);

-- ============================================================
-- CONVERSATION STATES
-- Tracks where a phone number currently sits inside a multi-step
-- flow (registration, posting an opportunity, manual add, editing
-- a post, etc). Every incoming webhook event (button tap or free
-- text) looks this up FIRST, before deciding how to handle the
-- message. Lives in Postgres, not in-memory, so an in-progress
-- flow survives a Render restart mid-conversation.
--
-- Without this table, a multi-step flow has nowhere to persist
-- "we just asked for X, now waiting for the reply" between one
-- webhook call and the next — each webhook call is a fresh,
-- stateless HTTP request with no memory of prior steps unless it
-- reads that state back out of the database itself.
-- ============================================================
CREATE TABLE conversation_states (
    phone_number TEXT PRIMARY KEY,
    current_flow TEXT NOT NULL,        -- e.g. 'register_poster', 'register_user', 'post_opportunity', 'edit_opportunity', 'manual_add'
    current_step TEXT NOT NULL,        -- e.g. 'awaiting_display_name', 'awaiting_tags', 'awaiting_deadline'
    collected_data JSONB NOT NULL DEFAULT '{}', -- scratch space for values gathered so far in this flow
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- A row here means "this phone number is mid-flow." A row is
-- deleted the moment a flow completes or is abandoned/cancelled —
-- an ABSENT row means "no active flow, treat the next message as
-- a fresh top-level action (menu tap, etc)," not "flow step zero."

-- ============================================================
-- APPLICATIONS (the core lifecycle-tracking table)
-- ============================================================
CREATE TYPE application_status AS ENUM ('available', 'ongoing', 'under_review', 'scheduled');
CREATE TYPE application_outcome AS ENUM ('yes', 'no', 'waiting');

CREATE TABLE applications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    opportunity_id UUID REFERENCES opportunities(id) ON DELETE CASCADE, -- NULL if manually added by the user
    custom_title TEXT, -- used only when opportunity_id IS NULL
    custom_description TEXT,
    status application_status NOT NULL DEFAULT 'available',
    next_reminder_at TIMESTAMPTZ,
    reminder_interval_days INT NOT NULL DEFAULT 2,
    deadline_heads_up_sent BOOLEAN NOT NULL DEFAULT false,
    outcome application_outcome,
    scheduled_event_date DATE,
    -- for manually-added items, since there's no linked opportunity row:
    custom_deadline DATE,
    custom_result_date DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT manual_or_linked CHECK (
        (opportunity_id IS NOT NULL) OR (custom_title IS NOT NULL)
    )
);

-- Indexes to support the daily scheduler's queries efficiently
CREATE INDEX idx_applications_next_reminder ON applications (next_reminder_at) WHERE next_reminder_at IS NOT NULL;
CREATE INDEX idx_applications_status ON applications (status);
CREATE INDEX idx_applications_user_status ON applications (user_id, status);
CREATE INDEX idx_opportunities_deadline ON opportunities (application_deadline);

-- ============================================================
-- HELPER VIEW: effective deadline (handles both linked + manual applications)
-- Useful for the scheduler's expiry and heads-up passes without
-- needing a JOIN + COALESCE in every query.
-- ============================================================
CREATE VIEW applications_with_effective_dates AS
SELECT
    a.*,
    COALESCE(o.application_deadline, a.custom_deadline) AS effective_deadline,
    COALESCE(o.result_date, a.custom_result_date) AS effective_result_date,
    o.event_start_date AS effective_event_start_date
FROM applications a
LEFT JOIN opportunities o ON a.opportunity_id = o.id;

-- ============================================================
-- ROW LEVEL SECURITY (safety net — backend uses service_role and bypasses this)
-- ============================================================
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE posters ENABLE ROW LEVEL SECURITY;
ALTER TABLE opportunities ENABLE ROW LEVEL SECURITY;
ALTER TABLE applications ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversation_states ENABLE ROW LEVEL SECURITY;
ALTER TABLE tags ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_tags ENABLE ROW LEVEL SECURITY;
ALTER TABLE opportunity_tags ENABLE ROW LEVEL SECURITY;

-- No public policies are defined — by default, RLS with no policies
-- blocks all access via the anon key. Only the service_role key
-- (used exclusively by the backend server) can read/write.

-- ============================================================
-- SEED: starter fixed tags
-- ============================================================
INSERT INTO tags (name, is_custom) VALUES
    ('Scholarships', false),
    ('Internships', false),
    ('Volunteering', false),
    ('Tech Events / Conferences', false),
    ('Competitions / Hackathons', false),
    ('Workshops / Trainings', false),
    ('Bootcamps', false),
    ('Job Opportunities', false),
    ('Research Opportunities', false),
    ('Fellowships', false),
    ('Grants / Funding', false),
    ('Networking Events', false);
