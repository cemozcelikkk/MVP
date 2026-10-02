/**
 * Araç türü Türkçe etiketleri - `VehicleProfilesModal`, `ReviewFormModal` ve
 * yorum kartlarındaki araç anlık görüntüsü (ör. "Campervan · 6,4 m")
 * arasında paylaşılır ki etiket metni tek yerde değişsin.
 */
import type { VehicleType } from "./api";

export const VEHICLE_TYPE_LABEL: Record<VehicleType, string> = {
  motorhome: "Motokaravan",
  campervan: "Campervan",
  travel_trailer: "Çekme Karavan",
  other: "Diğer",
};
