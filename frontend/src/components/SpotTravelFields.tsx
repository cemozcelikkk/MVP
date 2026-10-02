import type { SpotTravelInfo } from "../lib/api";
import { Field, INPUT_CLASS, SegmentedGroup } from "./FormControls";
import { Section } from "./ui/Section";
export default function SpotTravelFields({ value, onChange }: {
  value: SpotTravelInfo;
  onChange: (value: SpotTravelInfo) => void;
}) {
  function set<K extends keyof SpotTravelInfo>(key: K, next: SpotTravelInfo[K]) { onChange({ ...value, [key]: next }); }
  const textFields = [
    ["rule_description", "Kural açıklaması", 2000], ["rule_source", "Kuralın kaynağı (tabela, işletmeci vb.)", 300],
    ["approach_description", "Son yaklaşım, dar geçit ve dönüş alanı", 2000], ["access_season", "Mevsimsel erişim bilgisi", 300],
  ] as const;
  return <>
    <Section title="Geceleme ve İzinler">
      <div className="flex flex-col gap-3">
        <Field label="Geceleme durumu">
          <SegmentedGroup value={value.overnight_status} onChange={(next) => set("overnight_status", next)} options={[
            { value: "unknown", label: "Bilinmiyor" }, { value: "allowed", label: "İzin veriliyor" }, { value: "not_allowed", label: "İzin verilmiyor" },
          ]} />
        </Field>
        <Field label="Maksimum kalış (gece)">
          <input type="number" min={1} max={365} value={value.max_stay_nights ?? ""} onChange={(e) => set("max_stay_nights", e.target.value ? Number(e.target.value) : null)} className={INPUT_CLASS} />
        </Field>
        <Field label="Özel mülk / izin şartı">
          <SegmentedGroup value={value.private_property_permission} onChange={(next) => set("private_property_permission", next)} options={[
            { value: "unknown", label: "Bilinmiyor" }, { value: "required", label: "İzin gerekli" }, { value: "not_required", label: "İzin gerekmiyor" },
          ]} />
        </Field>
        {textFields.slice(0, 2).map(([key, label, max]) => <Field key={key} label={label}>
          <textarea rows={2} maxLength={max} value={value[key] ?? ""} onChange={(e) => set(key, e.target.value || null)} className={INPUT_CLASS} />
        </Field>)}
        <Field label="Kuralın kontrol edildiği tarih">
          <input type="date" value={value.rule_checked_on ?? ""} onChange={(e) => set("rule_checked_on", e.target.value || null)} className={INPUT_CLASS} />
        </Field>
        <p className="text-xs text-text-secondary">Bunlar bildirilen bilgilerdir; güncellik ve topluluk doğrulaması detayda ayrıca gösterilir.</p>
      </div>
    </Section>
    <Section title="Giriş ve Yaklaşım">
      <div className="flex flex-col gap-3">
        <p className="text-xs text-text-secondary">Alan merkezinden farklı bir giriş varsa koordinatlarını birlikte girin. Navigasyon bu girişi kullanır.</p>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Giriş enlemi">
            <input type="number" step="any" min={-90} max={90} value={value.entry_latitude ?? ""} onChange={(e) => set("entry_latitude", e.target.value ? Number(e.target.value) : null)} className={INPUT_CLASS} />
          </Field>
          <Field label="Giriş boylamı">
            <input type="number" step="any" min={-180} max={180} value={value.entry_longitude ?? ""} onChange={(e) => set("entry_longitude", e.target.value ? Number(e.target.value) : null)} className={INPUT_CLASS} />
          </Field>
        </div>
        {textFields.slice(2).map(([key, label, max]) => <Field key={key} label={label}>
          <textarea rows={2} maxLength={max} value={value[key] ?? ""} onChange={(e) => set(key, e.target.value || null)} className={INPUT_CLASS} />
        </Field>)}
      </div>
    </Section>
  </>;
}
