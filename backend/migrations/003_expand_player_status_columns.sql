-- Migration: expand player text columns that can exceed original limits

ALTER TABLE players
    ALTER COLUMN status TYPE VARCHAR(100),
    ALTER COLUMN injury_status TYPE VARCHAR(100),
    ALTER COLUMN injury_body_part TYPE VARCHAR(100);
