BEGIN;

DO $$
DECLARE
    tiffany_id uuid := gen_random_uuid();
    partner_id uuid := gen_random_uuid();
    outsider_id uuid := gen_random_uuid();
    test_household_id uuid := gen_random_uuid();
    other_household_id uuid := gen_random_uuid();
    task_id uuid := gen_random_uuid();
    time_block_id uuid := gen_random_uuid();
    contribution bigint;
BEGIN
    INSERT INTO app_users (id, display_name) VALUES
        (tiffany_id, 'Tiffany'),
        (partner_id, 'Partner'),
        (outsider_id, 'Outside Member');

    INSERT INTO households (id, name, created_by_user_id) VALUES
        (test_household_id, 'Test Household', tiffany_id),
        (other_household_id, 'Other Household', outsider_id);

    INSERT INTO household_memberships (household_id, user_id) VALUES
        (test_household_id, tiffany_id),
        (test_household_id, partner_id),
        (other_household_id, outsider_id);

    INSERT INTO tasks (
        id,
        household_id,
        created_by_user_id,
        planned_for_user_id,
        title
    ) VALUES (
        task_id,
        test_household_id,
        tiffany_id,
        partner_id,
        'Clean the garage'
    );

    INSERT INTO time_blocks (
        id,
        household_id,
        created_by_user_id,
        participant_user_id,
        block_kind,
        status,
        starts_at,
        ends_at
    ) VALUES (
        time_block_id,
        test_household_id,
        partner_id,
        partner_id,
        'planned',
        'completed',
        '2026-09-05 10:00:00+00',
        '2026-09-05 11:00:00+00'
    );

    INSERT INTO time_block_tasks (household_id, time_block_id, task_id)
    VALUES (test_household_id, time_block_id, task_id);

    INSERT INTO completion_records (
        household_id,
        created_by_user_id,
        completed_by_user_id,
        task_id,
        time_block_id,
        category,
        duration_minutes,
        completed_at
    ) VALUES (
        test_household_id,
        tiffany_id,
        partner_id,
        task_id,
        time_block_id,
        'cleaning',
        60,
        '2026-09-05 11:00:00+00'
    );

    SELECT duration_minutes
    INTO contribution
    FROM member_contribution_durations
    WHERE member_contribution_durations.household_id = test_household_id
      AND user_id = partner_id;

    IF contribution <> 60 THEN
        RAISE EXCEPTION 'expected a 60-minute contribution, got %', contribution;
    END IF;

    BEGIN
        INSERT INTO tasks (
            household_id,
            created_by_user_id,
            title
        ) VALUES (
            test_household_id,
            outsider_id,
            'Cross-household task'
        );
        RAISE EXCEPTION 'cross-household creator was accepted';
    EXCEPTION
        WHEN foreign_key_violation THEN
            NULL;
    END;

    INSERT INTO audit_events (
        household_id,
        actor_user_id,
        action,
        entity_type,
        entity_id,
        after_values
    ) VALUES (
        test_household_id,
        tiffany_id,
        'create',
        'task',
        task_id,
        jsonb_build_object('title', 'Clean the garage')
    );

    BEGIN
        UPDATE audit_events
        SET action = 'update'
        WHERE entity_id = task_id;
        RAISE EXCEPTION 'audit event update was accepted';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM <> 'audit events are append-only' THEN
                RAISE;
            END IF;
    END;
END;
$$;

ROLLBACK;
