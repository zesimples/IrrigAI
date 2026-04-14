"use client";

import { useEffect, useState } from "react";
import { catalogApi } from "@/lib/api";
import type { CropProfileTemplate, SoilPreset } from "@/types";

export function useSoilPresets() {
  const [presets, setPresets] = useState<SoilPreset[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    catalogApi
      .soilPresets()
      .then(setPresets)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  return { presets, loading, error };
}

export function useCropProfileTemplates() {
  const [templates, setTemplates] = useState<CropProfileTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    catalogApi
      .cropProfileTemplates()
      .then(setTemplates)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  return { templates, loading, error };
}
