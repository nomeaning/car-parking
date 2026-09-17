-- ============================================================
-- REMOVE LEGACY UNIQUE CONSTRAINT FROM PARKING_SLOTS
-- ============================================================

-- Drop the old unique restriction on slot_number if it exists from previous iterations
ALTER TABLE public.parking_slots
DROP CONSTRAINT IF EXISTS parking_slots_slot_number_key;

-- Gracefully make slot_number nullable if the column exists in the legacy layer
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'parking_slots'
          AND column_name = 'slot_number'
    ) THEN
        ALTER TABLE public.parking_slots ALTER COLUMN slot_number DROP NOT NULL;
    END IF;
END $$;
