/// <reference path="../.astro/types.d.ts" />

interface ImportMetaEnv {
  readonly PUBLIC_REPORT_SOURCE?: 'local' | 'remote';
  readonly REPORT_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
