import { readdir, readFile } from 'node:fs/promises';
import path from 'node:path';

export type ReportRoute = {
  dataFileId: string;
  routeId: string;
  displayName: string;
};

type LoadedReport = {
  dataFileId: string;
  fileName: string;
  report: Record<string, any>;
};

const REPORT_PREFIX = 'report_';
const REPORT_SUFFIX = '.json';

export function defaultReportDataDir() {
  return path.join(process.cwd(), 'src', 'data');
}

export async function loadReportRoutes(dataDir = defaultReportDataDir()): Promise<ReportRoute[]> {
  let files: string[] = [];
  try {
    files = await readdir(dataDir);
  } catch {
    return [];
  }

  const loadedReports: LoadedReport[] = [];
  for (const fileName of files.filter(isReportJson).sort()) {
    const dataFileId = stripReportFileName(fileName);

    try {
      const raw = await readFile(path.join(dataDir, fileName), 'utf-8');
      loadedReports.push({
        dataFileId,
        fileName,
        report: JSON.parse(raw),
      });
    } catch {
      // Keep malformed reports routable by file id so the page can fail normally.
      loadedReports.push({ dataFileId, fileName, report: {} });
    }
  }

  const routeBaseCounts = new Map<string, number>();
  loadedReports.forEach(item => {
    const base = preferredRouteBase(item);
    routeBaseCounts.set(base, (routeBaseCounts.get(base) ?? 0) + 1);
  });

  const routeBaseRanks = new Map<string, number>();
  const usedRouteIds = new Set<string>();

  return loadedReports.map(item => {
    const base = preferredRouteBase(item);
    const rank = (routeBaseRanks.get(base) ?? 0) + 1;
    const groupSize = routeBaseCounts.get(base) ?? 1;
    routeBaseRanks.set(base, rank);

    const candidateRouteId = groupSize > 1 ? `${base}_${rank}` : base;
    const routeId = uniqueRouteId(candidateRouteId, usedRouteIds);
    const displayName = groupSize > 1
      ? `${preferredDisplayName(item)}_${rank}`
      : preferredDisplayName(item);

    return {
      dataFileId: item.dataFileId,
      routeId,
      displayName,
    };
  });
}

function isReportJson(fileName: string) {
  return fileName.startsWith(REPORT_PREFIX) && fileName.endsWith(REPORT_SUFFIX);
}

function stripReportFileName(fileName: string) {
  return fileName.slice(REPORT_PREFIX.length, -REPORT_SUFFIX.length);
}

function preferredRouteBase(item: LoadedReport) {
  const user = item.report.user ?? {};
  return safeSegment(
    user.handle ?? user.report_slug ?? item.report.user_id ?? item.dataFileId,
    item.dataFileId,
  );
}

function preferredDisplayName(item: LoadedReport) {
  const user = item.report.user ?? {};
  const displayName = user.display_name ?? user.handle ?? item.report.user_id ?? item.dataFileId;
  return String(displayName).trim() || item.dataFileId;
}

function safeSegment(value: unknown, fallback: string) {
  const raw = String(value ?? fallback).trim();
  const cleaned = raw.replace(/[^A-Za-z0-9_.-]+/g, '_').replace(/^_+|_+$/g, '');
  return cleaned || fallback || 'report';
}

function uniqueRouteId(candidate: string, usedRouteIds: Set<string>) {
  let routeId = candidate;
  let index = 2;

  while (usedRouteIds.has(routeId)) {
    routeId = `${candidate}_${index}`;
    index += 1;
  }

  usedRouteIds.add(routeId);
  return routeId;
}
