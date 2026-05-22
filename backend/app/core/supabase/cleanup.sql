DO $$ 
DECLARE
  r RECORD;
BEGIN
  -- Loop through all tables specifically in the 'public' schema
  FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname = 'public') 
  LOOP
    EXECUTE 'TRUNCATE TABLE public.' || quote_ident(r.tablename) || ' RESTART IDENTITY CASCADE';
  END LOOP;
END $$;