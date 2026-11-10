-- ============================================================================
-- Hindu Tithi Birthday Calculator — Supabase PostgreSQL Schema & RLS Policies
-- ============================================================================
-- Run this entire script in your Supabase Dashboard -> SQL Editor.
-- All user-owned tables enforce Row Level Security (RLS) tied to auth.uid()
-- and cascade deletion when an auth.users account is permanently deleted.
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ----------------------------------------------------------------------------
-- 1. Trigger helper to maintain updated_at automatically
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

-- ----------------------------------------------------------------------------
-- 2. saved_birth_profiles
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.saved_birth_profiles (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL DEFAULT auth.uid() REFERENCES auth.users(id) ON DELETE CASCADE,
  label text NOT NULL CHECK (char_length(trim(label)) BETWEEN 1 AND 80),
  birth_date date NOT NULL,
  birth_time_mode text NOT NULL CHECK (birth_time_mode IN ('exact', 'approximate', 'unknown')),
  birth_time time NULL,
  birth_time_start time NULL,
  birth_time_end time NULL,
  location_name text NOT NULL CHECK (char_length(trim(location_name)) BETWEEN 1 AND 200),
  latitude double precision NOT NULL CHECK (latitude BETWEEN -90 AND 90),
  longitude double precision NOT NULL CHECK (longitude BETWEEN -180 AND 180),
  timezone text NOT NULL CHECK (char_length(trim(timezone)) BETWEEN 1 AND 100),
  ayanamsha text NOT NULL DEFAULT 'lahiri' CHECK (ayanamsha IN ('lahiri', 'raman', 'krishnamurti', 'yukteshwar', 'true_citra')),
  lunar_system text NOT NULL DEFAULT 'amanta' CHECK (lunar_system IN ('amanta', 'purnimanta')),
  observance_method text NOT NULL DEFAULT 'sunrise' CHECK (observance_method IN ('sunrise', 'madhyahna', 'sunset')),
  adhika_rule text NOT NULL DEFAULT 'nija' CHECK (adhika_rule IN ('nija', 'adhika', 'both')),
  start_year integer NULL CHECK (start_year IS NULL OR (start_year BETWEEN 1583 AND 2500)),
  end_year integer NULL CHECK (end_year IS NULL OR (end_year BETWEEN 1583 AND 2500)),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT saved_birth_profiles_year_order CHECK (
    start_year IS NULL OR end_year IS NULL OR end_year >= start_year
  )
);

CREATE INDEX IF NOT EXISTS idx_saved_birth_profiles_user_created
  ON public.saved_birth_profiles (user_id, created_at DESC);

DROP TRIGGER IF EXISTS trg_saved_birth_profiles_updated_at ON public.saved_birth_profiles;
CREATE TRIGGER trg_saved_birth_profiles_updated_at
  BEFORE UPDATE ON public.saved_birth_profiles
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

-- ----------------------------------------------------------------------------
-- 3. calculation_history
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.calculation_history (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL DEFAULT auth.uid() REFERENCES auth.users(id) ON DELETE CASCADE,
  saved_birth_profile_id uuid NULL REFERENCES public.saved_birth_profiles(id) ON DELETE SET NULL,
  input_data jsonb NOT NULL,
  calculation_result jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_calculation_history_user_created
  ON public.calculation_history (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_calculation_history_profile
  ON public.calculation_history (saved_birth_profile_id);

-- ----------------------------------------------------------------------------
-- 4. Row Level Security (RLS) & Least-Privilege Grants
-- ----------------------------------------------------------------------------
REVOKE ALL ON public.saved_birth_profiles FROM anon, PUBLIC;
REVOKE ALL ON public.calculation_history FROM anon, PUBLIC;

GRANT SELECT, INSERT, UPDATE, DELETE ON public.saved_birth_profiles TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.calculation_history TO authenticated;

ALTER TABLE public.saved_birth_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.calculation_history ENABLE ROW LEVEL SECURITY;

-- saved_birth_profiles policies
DROP POLICY IF EXISTS "Users can view own birth profiles" ON public.saved_birth_profiles;
CREATE POLICY "Users can view own birth profiles"
  ON public.saved_birth_profiles
  FOR SELECT
  TO authenticated
  USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can insert own birth profiles" ON public.saved_birth_profiles;
CREATE POLICY "Users can insert own birth profiles"
  ON public.saved_birth_profiles
  FOR INSERT
  TO authenticated
  WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can update own birth profiles" ON public.saved_birth_profiles;
CREATE POLICY "Users can update own birth profiles"
  ON public.saved_birth_profiles
  FOR UPDATE
  TO authenticated
  USING (auth.uid() = user_id)
  WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can delete own birth profiles" ON public.saved_birth_profiles;
CREATE POLICY "Users can delete own birth profiles"
  ON public.saved_birth_profiles
  FOR DELETE
  TO authenticated
  USING (auth.uid() = user_id);

-- calculation_history policies (including cross-table profile ownership check)
DROP POLICY IF EXISTS "Users can view own calculation history" ON public.calculation_history;
CREATE POLICY "Users can view own calculation history"
  ON public.calculation_history
  FOR SELECT
  TO authenticated
  USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can insert own calculation history" ON public.calculation_history;
CREATE POLICY "Users can insert own calculation history"
  ON public.calculation_history
  FOR INSERT
  TO authenticated
  WITH CHECK (
    auth.uid() = user_id
    AND (
      saved_birth_profile_id IS NULL
      OR EXISTS (
        SELECT 1
        FROM public.saved_birth_profiles p
        WHERE p.id = saved_birth_profile_id
          AND p.user_id = auth.uid()
      )
    )
  );

DROP POLICY IF EXISTS "Users can update own calculation history" ON public.calculation_history;
CREATE POLICY "Users can update own calculation history"
  ON public.calculation_history
  FOR UPDATE
  TO authenticated
  USING (auth.uid() = user_id)
  WITH CHECK (
    auth.uid() = user_id
    AND (
      saved_birth_profile_id IS NULL
      OR EXISTS (
        SELECT 1
        FROM public.saved_birth_profiles p
        WHERE p.id = saved_birth_profile_id
          AND p.user_id = auth.uid()
      )
    )
  );

DROP POLICY IF EXISTS "Users can delete own calculation history" ON public.calculation_history;
CREATE POLICY "Users can delete own calculation history"
  ON public.calculation_history
  FOR DELETE
  TO authenticated
  USING (auth.uid() = user_id);
