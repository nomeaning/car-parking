-- ============================================================
-- MAKE PARKING_SLOTS STORAGE BUCKET PUBLIC
-- ============================================================
INSERT INTO storage.buckets (id, name, public)
VALUES ('parking_slots', 'parking_slots', true)
ON CONFLICT (id) DO UPDATE SET public = true;

-- Ensure RLS policies allow public read access to objects
CREATE POLICY "Public Access" ON storage.objects FOR SELECT USING (bucket_id = 'parking_slots');
