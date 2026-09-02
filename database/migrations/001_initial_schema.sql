BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE FUNCTION set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

CREATE TABLE app_users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    display_name text NOT NULL CHECK (length(trim(display_name)) > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE auth_identities (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    provider text NOT NULL CHECK (length(trim(provider)) > 0),
    provider_subject text NOT NULL CHECK (length(trim(provider_subject)) > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (provider, provider_subject)
);

CREATE TABLE households (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL CHECK (length(trim(name)) > 0),
    created_by_user_id uuid NOT NULL REFERENCES app_users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE household_memberships (
    household_id uuid NOT NULL REFERENCES households(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES app_users(id),
    role text NOT NULL DEFAULT 'member' CHECK (role IN ('member', 'administrator')),
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive')),
    joined_at timestamptz NOT NULL DEFAULT now(),
    left_at timestamptz,
    PRIMARY KEY (household_id, user_id),
    CHECK (
        (status = 'active' AND left_at IS NULL)
        OR (status = 'inactive' AND left_at IS NOT NULL)
    )
);

CREATE TABLE tasks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id uuid NOT NULL REFERENCES households(id) ON DELETE CASCADE,
    created_by_user_id uuid NOT NULL,
    planned_for_user_id uuid,
    title text NOT NULL CHECK (length(trim(title)) > 0),
    description text,
    category text NOT NULL DEFAULT 'other' CHECK (length(trim(category)) > 0),
    lifecycle_status text NOT NULL DEFAULT 'active'
        CHECK (lifecycle_status IN ('active', 'completed', 'cancelled')),
    due_at timestamptz,
    estimated_duration_minutes integer CHECK (estimated_duration_minutes > 0),
    completed_at timestamptz,
    cancelled_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (household_id, id),
    FOREIGN KEY (household_id, created_by_user_id)
        REFERENCES household_memberships(household_id, user_id),
    FOREIGN KEY (household_id, planned_for_user_id)
        REFERENCES household_memberships(household_id, user_id),
    CHECK (
        (lifecycle_status = 'active' AND completed_at IS NULL AND cancelled_at IS NULL)
        OR (lifecycle_status = 'completed' AND completed_at IS NOT NULL AND cancelled_at IS NULL)
        OR (lifecycle_status = 'cancelled' AND completed_at IS NULL AND cancelled_at IS NOT NULL)
    )
);

CREATE TABLE recurrence_rules (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id uuid NOT NULL REFERENCES households(id) ON DELETE CASCADE,
    task_id uuid NOT NULL,
    frequency text NOT NULL CHECK (frequency IN ('daily', 'weekly', 'monthly', 'yearly')),
    frequency_interval integer NOT NULL DEFAULT 1 CHECK (frequency_interval > 0),
    days_of_week smallint[],
    day_of_month smallint CHECK (day_of_month BETWEEN 1 AND 31),
    starts_on date NOT NULL,
    ends_on date,
    timezone text NOT NULL CHECK (length(trim(timezone)) > 0),
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (task_id),
    UNIQUE (household_id, id),
    FOREIGN KEY (household_id, task_id) REFERENCES tasks(household_id, id) ON DELETE CASCADE,
    CHECK (ends_on IS NULL OR ends_on >= starts_on),
    CHECK (days_of_week IS NULL OR days_of_week <@ ARRAY[0, 1, 2, 3, 4, 5, 6]::smallint[])
);

CREATE TABLE task_instances (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id uuid NOT NULL REFERENCES households(id) ON DELETE CASCADE,
    task_id uuid NOT NULL,
    recurrence_rule_id uuid,
    planned_for_user_id uuid,
    occurrence_date date NOT NULL,
    lifecycle_status text NOT NULL DEFAULT 'active'
        CHECK (lifecycle_status IN ('active', 'completed', 'skipped', 'cancelled')),
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (task_id, occurrence_date),
    UNIQUE (household_id, id),
    UNIQUE (task_id, id),
    FOREIGN KEY (household_id, task_id) REFERENCES tasks(household_id, id) ON DELETE CASCADE,
    FOREIGN KEY (household_id, recurrence_rule_id)
        REFERENCES recurrence_rules(household_id, id),
    FOREIGN KEY (household_id, planned_for_user_id)
        REFERENCES household_memberships(household_id, user_id),
    CHECK (
        (lifecycle_status = 'completed' AND completed_at IS NOT NULL)
        OR (lifecycle_status <> 'completed' AND completed_at IS NULL)
    )
);

CREATE TABLE time_blocks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id uuid NOT NULL REFERENCES households(id) ON DELETE CASCADE,
    created_by_user_id uuid NOT NULL,
    participant_user_id uuid,
    block_kind text NOT NULL CHECK (block_kind IN ('planned', 'actual')),
    status text NOT NULL CHECK (status IN ('planned', 'completed', 'cancelled')),
    title text,
    starts_at timestamptz NOT NULL,
    ends_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (household_id, id),
    FOREIGN KEY (household_id, created_by_user_id)
        REFERENCES household_memberships(household_id, user_id),
    FOREIGN KEY (household_id, participant_user_id)
        REFERENCES household_memberships(household_id, user_id),
    CHECK (ends_at > starts_at),
    CHECK (
        (block_kind = 'planned' AND status IN ('planned', 'completed', 'cancelled'))
        OR (block_kind = 'actual' AND status = 'completed')
    )
);

CREATE TABLE time_block_tasks (
    household_id uuid NOT NULL REFERENCES households(id) ON DELETE CASCADE,
    time_block_id uuid NOT NULL,
    task_id uuid NOT NULL,
    task_instance_id uuid,
    planned_minutes integer CHECK (planned_minutes > 0),
    sort_order integer NOT NULL DEFAULT 0 CHECK (sort_order >= 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (time_block_id, task_id),
    FOREIGN KEY (household_id, time_block_id)
        REFERENCES time_blocks(household_id, id) ON DELETE CASCADE,
    FOREIGN KEY (household_id, task_id)
        REFERENCES tasks(household_id, id) ON DELETE CASCADE,
    FOREIGN KEY (task_id, task_instance_id)
        REFERENCES task_instances(task_id, id)
);

CREATE TABLE completion_records (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id uuid NOT NULL REFERENCES households(id) ON DELETE CASCADE,
    created_by_user_id uuid NOT NULL,
    completed_by_user_id uuid NOT NULL,
    task_id uuid,
    task_instance_id uuid,
    time_block_id uuid,
    category text NOT NULL DEFAULT 'other' CHECK (length(trim(category)) > 0),
    description text,
    duration_minutes integer NOT NULL CHECK (duration_minutes > 0),
    completed_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (household_id, id),
    FOREIGN KEY (household_id, created_by_user_id)
        REFERENCES household_memberships(household_id, user_id),
    FOREIGN KEY (household_id, completed_by_user_id)
        REFERENCES household_memberships(household_id, user_id),
    FOREIGN KEY (household_id, task_id)
        REFERENCES tasks(household_id, id),
    FOREIGN KEY (task_id, task_instance_id)
        REFERENCES task_instances(task_id, id),
    FOREIGN KEY (household_id, time_block_id)
        REFERENCES time_blocks(household_id, id),
    CHECK (task_instance_id IS NULL OR task_id IS NOT NULL)
);

CREATE TABLE audit_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id uuid NOT NULL REFERENCES households(id) ON DELETE CASCADE,
    actor_user_id uuid NOT NULL,
    action text NOT NULL CHECK (action IN ('create', 'update', 'delete')),
    entity_type text NOT NULL CHECK (length(trim(entity_type)) > 0),
    entity_id uuid NOT NULL,
    before_values jsonb,
    after_values jsonb,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (household_id, actor_user_id)
        REFERENCES household_memberships(household_id, user_id),
    CHECK (before_values IS NOT NULL OR after_values IS NOT NULL)
);

CREATE TABLE integration_requests (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id uuid NOT NULL REFERENCES households(id) ON DELETE CASCADE,
    actor_user_id uuid NOT NULL,
    client_name text NOT NULL CHECK (length(trim(client_name)) > 0),
    idempotency_key text NOT NULL CHECK (length(trim(idempotency_key)) > 0),
    operation text NOT NULL CHECK (length(trim(operation)) > 0),
    response_status integer CHECK (response_status BETWEEN 100 AND 599),
    response_body jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    UNIQUE (actor_user_id, client_name, idempotency_key),
    FOREIGN KEY (household_id, actor_user_id)
        REFERENCES household_memberships(household_id, user_id)
);

CREATE INDEX tasks_household_status_idx
    ON tasks (household_id, lifecycle_status);
CREATE INDEX tasks_planned_for_idx
    ON tasks (household_id, planned_for_user_id)
    WHERE planned_for_user_id IS NOT NULL;
CREATE INDEX task_instances_household_date_idx
    ON task_instances (household_id, occurrence_date);
CREATE INDEX time_blocks_household_starts_at_idx
    ON time_blocks (household_id, starts_at);
CREATE INDEX completion_records_household_completed_at_idx
    ON completion_records (household_id, completed_at);
CREATE INDEX completion_records_member_completed_at_idx
    ON completion_records (household_id, completed_by_user_id, completed_at);
CREATE INDEX audit_events_household_occurred_at_idx
    ON audit_events (household_id, occurred_at DESC);

CREATE VIEW member_contribution_durations AS
SELECT
    household_id,
    completed_by_user_id AS user_id,
    date_trunc('day', completed_at) AS contribution_day,
    sum(duration_minutes)::bigint AS duration_minutes
FROM completion_records
GROUP BY household_id, completed_by_user_id, date_trunc('day', completed_at);

CREATE TRIGGER app_users_set_updated_at
BEFORE UPDATE ON app_users
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER households_set_updated_at
BEFORE UPDATE ON households
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER tasks_set_updated_at
BEFORE UPDATE ON tasks
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER recurrence_rules_set_updated_at
BEFORE UPDATE ON recurrence_rules
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER task_instances_set_updated_at
BEFORE UPDATE ON task_instances
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER time_blocks_set_updated_at
BEFORE UPDATE ON time_blocks
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER completion_records_set_updated_at
BEFORE UPDATE ON completion_records
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE FUNCTION prevent_audit_event_changes()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'audit events are append-only';
END;
$$;

CREATE TRIGGER audit_events_are_append_only
BEFORE UPDATE OR DELETE ON audit_events
FOR EACH ROW EXECUTE FUNCTION prevent_audit_event_changes();

COMMIT;

