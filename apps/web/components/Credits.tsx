// Attribution required by the data licences (CC BY 4.0: credit, licence link, indicate changes;
// Open-Meteo additionally asks for a link next to where its data are shown).

const A = ({ href, children }: { href: string; children: React.ReactNode }) => (
  <a href={href} target="_blank" rel="noopener noreferrer" className="underline decoration-dotted underline-offset-2 hover:text-ink">
    {children}
  </a>
);

const CC_BY = "https://creativecommons.org/licenses/by/4.0/";

export function OpenMeteoCredit() {
  return <A href="https://open-meteo.com/">Weather data by Open-Meteo.com</A>;
}

export function SmardCredit() {
  return <A href="https://www.smard.de">Bundesnetzagentur | SMARD.de</A>;
}

export function DataCredits({ weather = true }: { weather?: boolean }) {
  return (
    <span>
      Data: <SmardCredit /> (<A href={CC_BY}>CC BY 4.0</A>)
      {weather && (
        <>
          {" · "}
          <OpenMeteoCredit /> (NOAA GFS model, <A href={CC_BY}>CC BY 4.0</A>)
        </>
      )}
      . Changes: unit conversion, hourly aggregation, area weighting and forecasts built by GridMind; no endorsement
      by the data providers is implied.
    </span>
  );
}

export function SiteFooterCredits() {
  return (
    <>
      <DataCredits /> Boundaries: <A href="https://www.naturalearthdata.com">Natural Earth</A> (public domain). SMARD
      data originate from ENTSO-E. Research output, not for operational or trading decisions.
    </>
  );
}
