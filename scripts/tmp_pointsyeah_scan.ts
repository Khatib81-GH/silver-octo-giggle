import { writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const modulePath = process.env.POINTSYEAH_MODULE || "/tmp/pointsyeah-api/src/pointsyeah.ts";
const mod = await import(pathToFileURL(modulePath).href);

const input = {
  departure: "JED",
  arrival: "DTW",
  departDate: "2026-12-25",
  departDateTo: "2027-01-05",
  cabins: ["Economy"],
  adults: 1,
  children: 0,
};

const snapshots: unknown[] = [];
let results: unknown[] = [];
let error: string | null = null;

try {
  results = await mod.search(input, {
    timeoutMs: 180_000,
    pollIntervalMs: 250,
    onUpdate: (snapshot: unknown) => {
      snapshots.push(snapshot);
      writeFileSync(
        "tmp_pointsyeah_progress.json",
        JSON.stringify({ input, snapshots, results }, null, 2),
      );
    },
  });
} catch (e) {
  error = e instanceof Error ? `${e.name}: ${e.message}\n${e.stack ?? ""}` : String(e);
}

const output = {
  source: "PointsYeah anonymous live-search API via open-source client",
  retrieved_at: new Date().toISOString(),
  input,
  error,
  results,
  snapshots,
};
writeFileSync("tmp_pointsyeah_results.json", JSON.stringify(output, null, 2));

const programs = Array.isArray(results)
  ? results.map((r: any) => ({
      date: r?.date,
      program: r?.program,
      code: r?.code,
      route_count: Array.isArray(r?.routes) ? r.routes.length : 0,
    }))
  : [];
writeFileSync("tmp_pointsyeah_programs.json", JSON.stringify(programs, null, 2));

console.log(JSON.stringify({
  error,
  result_count: Array.isArray(results) ? results.length : 0,
  programs,
}, null, 2));
