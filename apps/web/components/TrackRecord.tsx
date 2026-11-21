"use client";

import { ErrorState, Panel, Skeleton, Stat } from "@/components/ui";
import { type TrackRecord, fmtMW, useData } from "@/lib/data";

const dt = new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/Berlin", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });

export default function TrackRecordView() {
  const tr = useData<TrackRecord>("track_record.json");
  if (tr.error) return <ErrorState message={tr.error} onRetry={tr.retry} />;
  const d = tr.data;
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Live track record</h1>
        <p className="mt-1 max-w-3xl text-[14px] text-ink-2">
          Real forecasts, issued before the delivery day and never revised. Each forecast is appended to{" "}
          <code>track_record/live_forecasts.csv</code> in the project&apos;s git history the moment it is made, so anyone can
          verify it existed before the outcome was known. Only forecasts issued on time (by 10:00 the day before) count
          toward the scores.
        </p>
      </div>
      {!d ? <Skeleton height={200} /> : d.status === "not_started" ? (
        <Panel title="Not started yet" subtitle="No live forecasts have been issued so far.">
          <p className="text-[13px] text-ink-2">
            The daily job (<code>gridmind live</code>) has not run yet. Backtest results are in the Model Lab; this page
            only shows forecasts made in real time.
          </p>
        </Panel>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Forecasts issued" value={String(d.summary?.days_issued ?? 0)} note={`${d.summary?.days_scored_on_time ?? 0} on time and fully scored`} />
            <Stat label="GridMind MAE (live)" value={fmtMW(d.summary?.mae_gridmind)} />
            <Stat label="TSO forecast MAE (same hours)" value={fmtMW(d.summary?.mae_tso)} />
            <Stat label="90% interval coverage" value={d.summary?.coverage_90 == null ? "—" : `${Math.round(d.summary.coverage_90 * 100)}%`} note="nominal 90%" />
          </div>
          <Panel title="Daily log" subtitle="Newest first. MAE in MW, over hours where both forecasts and the actual are available."
                 footer="Pending = actuals not yet published. Late = issued after the 10:00 D-1 deadline (kept for transparency, excluded from scores).">
            <div className="overflow-x-auto">
              <table className="num w-full min-w-[680px] text-[13px]">
                <thead className="text-left text-[12px] text-ink-2"><tr className="border-b border-border">
                  <th className="py-1.5 pr-3">Delivery day</th><th className="pr-3">Issued (local)</th><th className="pr-3">Weather run (UTC)</th>
                  <th className="pr-3">Status</th><th className="pr-3">GridMind MAE</th><th className="pr-3">TSO MAE</th><th>In 90% band</th></tr></thead>
                <tbody>
                  {[...d.days].reverse().map((r) => (
                    <tr key={r.delivery_day} className="border-b border-border">
                      <td className="py-1.5 pr-3">{r.delivery_day}</td>
                      <td className="pr-3">{dt.format(Date.parse(r.issued_at_utc))}</td>
                      <td className="pr-3">{r.weather_model_run?.slice(0, 13).replace("T", " ")}Z</td>
                      <td className="pr-3">{!r.on_time ? "⚠ late" : r.complete ? "✓ scored" : `pending (${r.scored}/${r.hours} h)`}</td>
                      <td className="pr-3">{fmtMW(r.mae_gridmind)}</td><td className="pr-3">{fmtMW(r.mae_tso)}</td>
                      <td>{r.coverage_90 == null ? "—" : `${Math.round(r.coverage_90 * 100)}%`}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </>
      )}
    </div>
  );
}
