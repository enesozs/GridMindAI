import { Panel } from "@/components/ui";
import { DataCredits } from "@/components/Credits";

export const metadata = { title: "Methods & sources — GridMind" };

const SOURCES = [
  ["Bundesnetzagentur | SMARD.de", "CC BY 4.0", "Actual load, TSO day-ahead load forecast, generation by type, for DE-LU and the four German control areas (quarter-hourly). SMARD receives these data from ENTSO-E. SMARD wholesale prices are not used, because their licensing is under review."],
  ["Weather data by Open-Meteo.com (NOAA GFS model)", "CC BY 4.0 (free API, non-commercial)", "Archived GFS forecasts made 48 hours before each hour (Previous Runs API), at 13 population-weighted points. Temperature is the model input; lead-0 values are used only for the labelled hindsight experiment."],
  ["Natural Earth", "Public domain", "German state boundaries, grouped into approximate TSO control-area footprints."],
];

export default function Page() {
  return (
    <div className="max-w-4xl space-y-5">
      <h1 className="text-2xl font-semibold tracking-tight">Methods &amp; sources</h1>
      <Panel title="What is forecast">
        <ul className="list-disc space-y-1.5 pl-5 text-[14px] text-ink-2">
          <li><b className="text-ink">Target:</b> hourly mean total electricity load of the Germany–Luxembourg bidding zone, in MW (the mean of four published quarter-hour values; an hour with a missing quarter is not scored).</li>
          <li><b className="text-ink">Issue time:</b> 10:00 Europe/Berlin on the day before delivery, the same deadline by which the TSOs must publish their own day-ahead forecast (EU Regulation 543/2013). That makes the comparison fair.</li>
          <li><b className="text-ink">Information allowed:</b> load published at least two hours before issue, the GFS temperature forecast made 48 hours before each delivery hour (so it existed before the issue time), and the calendar. Nothing else, and never the TSO forecast itself.</li>
          <li><b className="text-ink">Models:</b> naive baselines, a ridge regression, and gradient-boosted quantile trees (5/25/50/75/95%) whose intervals are calibrated with conformalized quantile regression.</li>
          <li><b className="text-ink">Evaluation:</b> monthly refits on expanding windows, a validation year for development, and a frozen test year (Nov 2025 – Oct 2026) evaluated once. Significance via the Diebold–Mariano test on daily errors.</li>
        </ul>
      </Panel>
      <Panel title="What this is not">
        <ul className="list-disc space-y-1.5 pl-5 text-[14px] text-ink-2">
          <li>Load is grid load measured by TSOs, not household consumption; rooftop solar used on site lowers it.</li>
          <li>Control-area map shapes are approximations by federal state, not network topology.</li>
          <li>Historical actuals are SMARD&apos;s latest (revised) values, so backtest lag features are slightly better than what was known at the time; the live track record measures this honestly.</li>
          <li>Research output only: not for grid operation, trading or safety-critical decisions.</li>
        </ul>
      </Panel>
      <Panel title="Data sources and licences" footer={<DataCredits />}>
        <table className="w-full text-[13px]">
          <thead className="text-left text-[12px] text-ink-2"><tr className="border-b border-border"><th className="py-1.5 pr-3">Source</th><th className="pr-3">Licence</th><th>Used for</th></tr></thead>
          <tbody>{SOURCES.map(([s, l, u]) => (
            <tr key={s} className="border-b border-border align-top"><td className="py-1.5 pr-3 font-medium text-ink">{s}</td><td className="pr-3 whitespace-nowrap">{l}</td><td className="text-ink-2">{u}</td></tr>
          ))}</tbody>
        </table>
      </Panel>
    </div>
  );
}
