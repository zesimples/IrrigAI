/**
 * Crop-type labels and phenological stage definitions.
 * Extend this file when adding new crop types.
 */

export const CROP_LABELS: Record<string, string> = {
  olive:    "Olival",
  almond:   "Amendoal",
  maize:    "Milho",
  vineyard: "Vinha",
};

export const STAGE_LABELS: Record<string, string> = {
  // Olive
  olive_dormancy:         "Dormência",
  olive_bud_break:        "Abrolhamento",
  olive_budbreak:         "Abrolhamento",
  olive_flowering:        "Floração",
  olive_fruit_set:        "Vingamento",
  olive_pit_hardening:    "Endurecimento do caroço",
  olive_oil_accumulation: "Acumulação de azeite",
  olive_veraison:         "Pintor",
  olive_harvest:          "Colheita",
  olive_post_harvest:     "Pós-colheita",

  // Vineyard
  vine_dormancy:    "Dormência",
  vine_bleeding:    "Choro",
  vine_budbreak:    "Abrolhamento",
  vine_shoot_growth:"Crescimento do lançamento",
  vine_flowering:   "Floração",
  vine_fruit_set:   "Vingamento",
  vine_berry_growth:"Crescimento da baga",
  vine_veraison:    "Pintor (Maturação)",
  vine_ripening:    "Maturação",
  vine_harvest:     "Colheita",
  vine_post_harvest:"Pós-colheita",

  // Almond
  almond_dormancy:     "Dormência",
  almond_bloom:        "Floração",
  almond_fruit_set:    "Vingamento",
  almond_shell_expansion: "Expansão da casca",
  almond_kernel_fill:  "Enchimento do miolo",
  almond_hull_split:   "Abertura do pericarpo",
  almond_post_harvest: "Pós-colheita",
};

/**
 * Maps each crop type to a month index (0 = Jan … 11 = Dec) → stage key.
 * Used to auto-suggest the current phenological stage based on the calendar.
 * When a month overlaps two stages the more advanced one is preferred.
 */
const STAGE_BY_MONTH: Record<string, Record<number, string>> = {
  olive: {
    0:  "olive_dormancy",
    1:  "olive_dormancy",
    2:  "olive_bud_break",
    3:  "olive_flowering",
    4:  "olive_flowering",
    5:  "olive_fruit_set",
    6:  "olive_pit_hardening",
    7:  "olive_oil_accumulation",
    8:  "olive_oil_accumulation",
    9:  "olive_veraison",
    10: "olive_harvest",
    11: "olive_post_harvest",
  },
  vineyard: {
    0:  "vine_dormancy",
    1:  "vine_bleeding",
    2:  "vine_budbreak",
    3:  "vine_budbreak",
    4:  "vine_shoot_growth",
    5:  "vine_flowering",
    6:  "vine_berry_growth",
    7:  "vine_veraison",
    8:  "vine_ripening",
    9:  "vine_harvest",
    10: "vine_post_harvest",
    11: "vine_dormancy",
  },
  almond: {
    0:  "almond_dormancy",
    1:  "almond_bloom",
    2:  "almond_bloom",
    3:  "almond_fruit_set",
    4:  "almond_shell_expansion",
    5:  "almond_shell_expansion",
    6:  "almond_kernel_fill",
    7:  "almond_kernel_fill",
    8:  "almond_hull_split",
    9:  "almond_post_harvest",
    10: "almond_post_harvest",
    11: "almond_dormancy",
  },
};

/**
 * Returns the most likely phenological stage for a given crop and month.
 * Falls back to the first stage in CROP_STAGES if the crop isn't mapped.
 */
export function getSuggestedStage(cropType: string, month: number): string {
  const map = STAGE_BY_MONTH[cropType];
  if (map) return map[month] ?? map[0];
  const stages = CROP_STAGES[cropType] ?? CROP_STAGES["olive"];
  return stages[0]?.value ?? "";
}

/** Per-crop stage options for the phenological stage selector. */
export const CROP_STAGES: Record<string, { value: string; label: string }[]> = {
  olive: [
    { value: "olive_dormancy",         label: "Dormência (Dez–Fev)" },
    { value: "olive_bud_break",        label: "Abrolhamento (Mar)" },
    { value: "olive_flowering",        label: "Floração (Abr–Mai)" },
    { value: "olive_fruit_set",        label: "Vingamento (Jun)" },
    { value: "olive_pit_hardening",    label: "Endurecimento do caroço (Jul)" },
    { value: "olive_oil_accumulation", label: "Acumulação de azeite (Ago–Set)" },
    { value: "olive_veraison",         label: "Pintor (Out)" },
    { value: "olive_harvest",          label: "Colheita (Out–Nov)" },
    { value: "olive_post_harvest",     label: "Pós-colheita (Nov–Dez)" },
  ],
  vineyard: [
    { value: "vine_dormancy",     label: "Dormência (Dez–Fev)" },
    { value: "vine_bleeding",     label: "Choro (Fev–Mar)" },
    { value: "vine_budbreak",     label: "Abrolhamento (Mar–Abr)" },
    { value: "vine_shoot_growth", label: "Crescimento do lançamento (Abr–Mai)" },
    { value: "vine_flowering",    label: "Floração (Mai–Jun)" },
    { value: "vine_fruit_set",    label: "Vingamento (Jun)" },
    { value: "vine_berry_growth", label: "Crescimento da baga (Jul)" },
    { value: "vine_veraison",     label: "Pintor / Maturação (Ago)" },
    { value: "vine_ripening",     label: "Maturação (Ago–Set)" },
    { value: "vine_harvest",      label: "Colheita (Set–Out)" },
    { value: "vine_post_harvest", label: "Pós-colheita (Out–Nov)" },
  ],
  almond: [
    { value: "almond_dormancy",        label: "Dormência (Dez–Jan)" },
    { value: "almond_bloom",           label: "Floração (Fev–Mar)" },
    { value: "almond_fruit_set",       label: "Vingamento (Mar–Abr)" },
    { value: "almond_shell_expansion", label: "Expansão da casca (Mai–Jun)" },
    { value: "almond_kernel_fill",     label: "Enchimento do miolo (Jul–Ago)" },
    { value: "almond_hull_split",      label: "Abertura do pericarpo (Ago–Set)" },
    { value: "almond_post_harvest",    label: "Pós-colheita (Out–Nov)" },
  ],
};
