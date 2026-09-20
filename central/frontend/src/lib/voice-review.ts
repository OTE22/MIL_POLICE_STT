import type { BiometricCheck, BiometricPrintCheck, VoiceReviewAction } from "@/api/types";

export const reviewLabels: Record<VoiceReviewAction, string> = {
  NOTE: "إضافة ملاحظة", FLAG: "وضع علامة للمراجعة", RESOLVE: "إنهاء المراجعة", DEACTIVATE: "تعطيل البصمة",
};

export function printExplanation(row: BiometricPrintCheck, result: BiometricCheck): string {
  switch (row.status) {
    case "SINGLE_PRINT": return result.total_active_prints > 1
      ? "لا توجد عينة أخرى متوافقة تقنياً للمقارنة. اختلاف النموذج أو الإصدار لا يعني اختلاف المتحدث. أضف عينة مستقلة بإصدار متوافق."
      : "عينة واحدة لا تكفي لفحص الاتساق. أضف عينة من تسجيل مستقل.";
    case "ISOLATED": return `لم تصل أي مقارنة متوافقة إلى عتبة الاتساق ${result.coherence_threshold.toFixed(2)}. استمع إلى المصدر وقارنه بعينة أخرى قبل اتخاذ إجراء.`;
    case "NEAR_DUPLICATE": return `وصل التشابه مع عينة أخرى إلى عتبة شبه التكرار ${result.near_duplicate_threshold.toFixed(2)}. راجع المصدرين؛ التشابه المرتفع وحده لا يثبت تكرار التسجيل.`;
    case "COHERENT": return `تتوافق هذه العينة مع ${row.coherent_peer_count} من العينات عند العتبة المستخدمة. الاتساق لا يثبت هوية صاحب الصوت، وقد تبقى مجموعات أخرى منفصلة.`;
  }
}

export function comparisonScore(result: BiometricCheck, first: string, second: string): number | null {
  for (const group of result.groups) {
    const pair = group.pairs.find(p => (p.first_id === first && p.second_id === second) || (p.first_id === second && p.second_id === first));
    if (pair) return pair.similarity;
  }
  return null;
}

export function printGroupLabel(result: BiometricCheck, id: string): string {
  for (const [i, group] of result.groups.entries()) {
    const row = group.prints.find(p => p.enrollment_id === id);
    if (row) return `المجموعة ${i + 1}.${row.component_id}`;
  }
  return "بصمة غير فعالة أو محذوفة";
}
