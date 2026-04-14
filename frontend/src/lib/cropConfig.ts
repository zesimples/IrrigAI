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
