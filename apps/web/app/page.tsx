import AtlasView from "@/components/Atlas";
import ControlAreaForecasts from "@/components/ControlAreaForecasts";

export default function Page() {
  return (
    <div className="space-y-5">
      <AtlasView />
      <ControlAreaForecasts />
    </div>
  );
}
