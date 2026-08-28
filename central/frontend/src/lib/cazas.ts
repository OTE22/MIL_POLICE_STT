/* GENERATED from central/backend/app/services/lebanon_cazas.py - do not edit by hand.
 *
 * محل القيد is an identity namespace: رقم السجل is unique within a قضاء, not nationally.
 * The backend validates the code; this list only drives the picker. A backend test asserts
 * these codes match the Python list exactly, so the two cannot drift.
 */

export interface Caza {
  code: string;
  name: string;
  governorate: string;
}

export const CAZAS: Caza[] = [
  { code: "BEIRUT", name: "بيروت", governorate: "بيروت" },
  { code: "JBEIL", name: "جبيل", governorate: "جبل لبنان" },
  { code: "KESERWAN", name: "كسروان", governorate: "جبل لبنان" },
  { code: "MATN", name: "المتن", governorate: "جبل لبنان" },
  { code: "BAABDA", name: "بعبدا", governorate: "جبل لبنان" },
  { code: "ALEY", name: "عاليه", governorate: "جبل لبنان" },
  { code: "CHOUF", name: "الشوف", governorate: "جبل لبنان" },
  { code: "TRIPOLI", name: "طرابلس", governorate: "الشمال" },
  { code: "ZGHARTA", name: "زغرتا", governorate: "الشمال" },
  { code: "BSHARRI", name: "بشري", governorate: "الشمال" },
  { code: "BATROUN", name: "البترون", governorate: "الشمال" },
  { code: "KOURA", name: "الكورة", governorate: "الشمال" },
  { code: "MINIEH_DANNIEH", name: "المنية - الضنية", governorate: "الشمال" },
  { code: "AKKAR", name: "عكار", governorate: "عكار" },
  { code: "ZAHLE", name: "زحلة", governorate: "البقاع" },
  { code: "WEST_BEQAA", name: "البقاع الغربي", governorate: "البقاع" },
  { code: "RACHAYA", name: "راشيا", governorate: "البقاع" },
  { code: "BAALBEK", name: "بعلبك", governorate: "بعلبك - الهرمل" },
  { code: "HERMEL", name: "الهرمل", governorate: "بعلبك - الهرمل" },
  { code: "SIDON", name: "صيدا", governorate: "الجنوب" },
  { code: "TYRE", name: "صور", governorate: "الجنوب" },
  { code: "JEZZINE", name: "جزين", governorate: "الجنوب" },
  { code: "NABATIEH", name: "النبطية", governorate: "النبطية" },
  { code: "MARJEYOUN", name: "مرجعيون", governorate: "النبطية" },
  { code: "HASBAYA", name: "حاصبيا", governorate: "النبطية" },
  { code: "BINT_JBEIL", name: "بنت جبيل", governorate: "النبطية" },
];

export function cazaName(code: string | null | undefined): string | null {
  if (!code) return null;
  return CAZAS.find((c) => c.code === code)?.name ?? null;
}
