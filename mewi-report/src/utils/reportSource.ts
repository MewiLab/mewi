import { readFile } from 'node:fs/promises';
import path from 'node:path';

import type { FrontendReport, ReportProduct, ReportRoute } from './reportSchema';
import { defaultReportDataDir, loadReportRoutes } from './reportRoutes';

export interface ReportSource {
  load(id: string, product?: ReportProduct): Promise<FrontendReport | null>;
  list(product?: ReportProduct): Promise<ReportRoute[]>;
}

export class LocalFileReportSource implements ReportSource {
  constructor(private readonly dataDir = defaultReportDataDir()) {}

  async load(id: string, product: ReportProduct = 'attachment'): Promise<FrontendReport | null> {
    if (product !== 'attachment') {
      return null;
    }

    try {
      const raw = await readFile(path.join(this.dataDir, `report_${id}.json`), 'utf-8');
      const parsed = JSON.parse(raw);
      return typeof parsed === 'object' && parsed !== null ? parsed : null;
    } catch {
      return null;
    }
  }

  async list(product: ReportProduct = 'attachment'): Promise<ReportRoute[]> {
    return product === 'attachment' ? loadReportRoutes(this.dataDir) : [];
  }
}

export class RemoteReportSource implements ReportSource {
  constructor(
    private readonly apiBase: string,
    private readonly token: string,
  ) {}

  async load(_id = 'me', product: ReportProduct = 'attachment'): Promise<FrontendReport | null> {
    const response = await fetch(this.url(`/report/me/${product}`), {
      headers: { Authorization: `Bearer ${this.token}` },
    });

    if (response.status === 404) {
      return null;
    }
    if (!response.ok) {
      throw new Error(`Report fetch failed with HTTP ${response.status}`);
    }

    const parsed = await response.json();
    return typeof parsed === 'object' && parsed !== null ? parsed : null;
  }

  async list(product: ReportProduct = 'attachment'): Promise<ReportRoute[]> {
    const response = await fetch(this.url(`/report/?product=${encodeURIComponent(product)}`), {
      headers: { Authorization: `Bearer ${this.token}` },
    });
    if (response.status === 404) {
      return [];
    }
    if (!response.ok) {
      throw new Error(`Report list fetch failed with HTTP ${response.status}`);
    }
    const parsed = await response.json();
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed.map((item) => ({
      dataFileId: String(item.data_file_id ?? item.user_id ?? ''),
      routeId: String(item.route_id ?? item.user_id ?? ''),
      displayName: String(item.display_name ?? item.user_id ?? ''),
    })).filter((item) => item.routeId);
  }

  private url(pathname: string) {
    const base = normalizeApiBase(this.apiBase);
    return `${base}${pathname}`;
  }
}

export function createLocalFileReportSource(dataDir?: string) {
  return new LocalFileReportSource(dataDir);
}

export function createRemoteReportSource(apiBase: string, token: string) {
  return new RemoteReportSource(apiBase, token);
}

function normalizeApiBase(apiBase: string) {
  const trimmed = (apiBase || '').trim().replace(/\/+$/, '');
  const base = trimmed || 'http://localhost:8000';
  return base.endsWith('/api/v1') ? base : `${base}/api/v1`;
}
