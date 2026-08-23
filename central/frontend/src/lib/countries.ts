/* Offline nationality list (ISO 3166-1 alpha-2 + Arabic name). No CDN, no lookup service.
   Lebanon first, then the nationalities most frequently encountered locally, then the rest. */

export interface Country {
  code: string;
  ar: string;
}

export const PRIORITY_COUNTRIES: Country[] = [
  { code: "LB", ar: "لبناني" },
  { code: "SY", ar: "سوري" },
  { code: "PS", ar: "فلسطيني" },
  { code: "IQ", ar: "عراقي" },
  { code: "JO", ar: "أردني" },
  { code: "EG", ar: "مصري" },
  { code: "SD", ar: "سوداني" },
  { code: "ET", ar: "إثيوبي" },
  { code: "BD", ar: "بنغلاديشي" },
  { code: "PH", ar: "فلبيني" },
  { code: "LK", ar: "سريلانكي" },
  { code: "NP", ar: "نيبالي" },
];

export const OTHER_COUNTRIES: Country[] = [
  { code: "SA", ar: "سعودي" },
  { code: "AE", ar: "إماراتي" },
  { code: "KW", ar: "كويتي" },
  { code: "QA", ar: "قطري" },
  { code: "BH", ar: "بحريني" },
  { code: "OM", ar: "عماني" },
  { code: "YE", ar: "يمني" },
  { code: "LY", ar: "ليبي" },
  { code: "TN", ar: "تونسي" },
  { code: "DZ", ar: "جزائري" },
  { code: "MA", ar: "مغربي" },
  { code: "MR", ar: "موريتاني" },
  { code: "SO", ar: "صومالي" },
  { code: "DJ", ar: "جيبوتي" },
  { code: "KM", ar: "قمري" },
  { code: "TR", ar: "تركي" },
  { code: "IR", ar: "إيراني" },
  { code: "AM", ar: "أرمني" },
  { code: "AZ", ar: "أذربيجاني" },
  { code: "GE", ar: "جورجي" },
  { code: "RU", ar: "روسي" },
  { code: "UA", ar: "أوكراني" },
  { code: "BY", ar: "بيلاروسي" },
  { code: "MD", ar: "مولدوفي" },
  { code: "RO", ar: "روماني" },
  { code: "BG", ar: "بلغاري" },
  { code: "GR", ar: "يوناني" },
  { code: "CY", ar: "قبرصي" },
  { code: "FR", ar: "فرنسي" },
  { code: "DE", ar: "ألماني" },
  { code: "GB", ar: "بريطاني" },
  { code: "IT", ar: "إيطالي" },
  { code: "ES", ar: "إسباني" },
  { code: "PT", ar: "برتغالي" },
  { code: "NL", ar: "هولندي" },
  { code: "BE", ar: "بلجيكي" },
  { code: "SE", ar: "سويدي" },
  { code: "NO", ar: "نرويجي" },
  { code: "DK", ar: "دنماركي" },
  { code: "FI", ar: "فنلندي" },
  { code: "PL", ar: "بولندي" },
  { code: "CZ", ar: "تشيكي" },
  { code: "AT", ar: "نمساوي" },
  { code: "CH", ar: "سويسري" },
  { code: "US", ar: "أميركي" },
  { code: "CA", ar: "كندي" },
  { code: "MX", ar: "مكسيكي" },
  { code: "BR", ar: "برازيلي" },
  { code: "AR", ar: "أرجنتيني" },
  { code: "VE", ar: "فنزويلي" },
  { code: "CO", ar: "كولومبي" },
  { code: "AU", ar: "أسترالي" },
  { code: "NZ", ar: "نيوزيلندي" },
  { code: "IN", ar: "هندي" },
  { code: "PK", ar: "باكستاني" },
  { code: "AF", ar: "أفغاني" },
  { code: "CN", ar: "صيني" },
  { code: "JP", ar: "ياباني" },
  { code: "KR", ar: "كوري" },
  { code: "ID", ar: "إندونيسي" },
  { code: "MY", ar: "ماليزي" },
  { code: "TH", ar: "تايلندي" },
  { code: "VN", ar: "فيتنامي" },
  { code: "KE", ar: "كيني" },
  { code: "NG", ar: "نيجيري" },
  { code: "GH", ar: "غاني" },
  { code: "CM", ar: "كاميروني" },
  { code: "CI", ar: "إيفواري" },
  { code: "SN", ar: "سنغالي" },
  { code: "ZA", ar: "جنوب أفريقي" },
  { code: "ER", ar: "إريتري" },
  { code: "TD", ar: "تشادي" },
  { code: "SS", ar: "جنوب سوداني" },
];

export const ALL_COUNTRIES: Country[] = [...PRIORITY_COUNTRIES, ...OTHER_COUNTRIES];

export const LEBANON = "LB";

export function countryName(code: string | null | undefined, fallback?: string | null): string {
  if (!code) return fallback || "—";
  const hit = ALL_COUNTRIES.find((c) => c.code === code);
  return hit ? hit.ar : fallback || code;
}

export function isLebanese(code: string | null | undefined): boolean {
  return code === LEBANON;
}
