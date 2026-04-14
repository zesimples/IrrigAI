# Prompt 07 — Frontend: Onboarding, Configuration Forms, Dashboard & Probe Charts

## Context

You have read `00-project-brief.md` and completed Prompts 01–06. The backend API is functional. Now build the frontend.

## Design Reference

**CRITICAL: Before writing any frontend code, open `design-reference.html` in a browser.** This is the target design for the dashboard, probe chart, and recommendation detail. It contains:
- The exact visual design, color palette, typography, spacing, and component structure
- CSS custom properties (color tokens) to map into your Tailwind config
- Component-by-component CSS class documentation explaining what each piece does
- All text in Portuguese (pt-PT) as the primary language

The design file is annotated with comments mapping each visual section to a React component name. Follow these mappings when building your component tree.

**Design system tokens to extract into `tailwind.config.ts`:**
```
irrigai-green:       #639922   (healthy, irrigate, high confidence)
irrigai-green-bg:    #EAF3DE
irrigai-green-dark:  #27500A
irrigai-amber:       #EF9F27   (warning, medium confidence, reduce)
irrigai-amber-bg:    #FAEEDA
irrigai-amber-dark:  #633806
irrigai-red:         #E24B4A   (critical, low confidence, PWP)
irrigai-red-bg:      #FCEBEB
irrigai-red-dark:    #791F1F
irrigai-blue:        #85B7EB   (water, FC reference, info)
irrigai-blue-bg:     #E6F1FB
irrigai-blue-dark:   #0C447C
irrigai-teal:        #5DCAA5   (probe 30cm)
irrigai-purple:      #AFA9EC   (probe 60cm)
irrigai-surface:     #F5F4F0   (background surfaces)
```

**Typography:**
- Body: DM Sans (400 regular, 500 medium)
- Display/numbers: Fraunces (serif, for large values and the farm name)
- Both available via Google Fonts

## Key Design Principle: Forms Are First-Class Citizens

Unlike a system with pre-filled data, IrrigAI requires users to configure their own farm. The onboarding and configuration forms are just as important as the dashboard — they directly affect recommendation quality. Every form should:
- Show sensible defaults/suggestions (from templates)
- Let the user skip optional fields
- Explain WHY each field matters (tooltip: "This improves recommendation accuracy by X%")
- Show completion progress
- Be revisitable at any time from settings

## Architecture

```
src/
├── app/
│   ├── layout.tsx
│   ├── page.tsx                      # Redirects based on setup status
│   │
│   ├── onboarding/                   # NEW: Step-by-step setup wizard
│   │   ├── page.tsx                  # Onboarding hub
│   │   ├── farm/page.tsx             # Step 1: Create farm
│   │   ├── plots/page.tsx            # Step 2: Add plots + soil
│   │   ├── sectors/page.tsx          # Step 3: Add sectors + crop
│   │   └── irrigation/page.tsx       # Step 4: Configure irrigation systems
│   │
│   ├── dashboard/
│   │   └── page.tsx
│   ├── sectors/
│   │   └── [sectorId]/
│   │       ├── page.tsx
│   │       ├── probes/page.tsx
│   │       ├── recommendations/[recId]/page.tsx
│   │       └── edit/page.tsx         # NEW: Edit sector config
│   ├── alerts/
│   │   └── page.tsx
│   ├── irrigation/
│   │   └── log/page.tsx
│   └── settings/
│       ├── page.tsx                  # Farm settings hub
│       ├── farm/page.tsx             # Edit farm details
│       ├── plots/page.tsx            # Manage plots
│       ├── crop-profiles/page.tsx    # NEW: View/edit crop profile templates
│       └── soil-presets/page.tsx     # NEW: View soil presets
│
├── components/
│   ├── ui/                           # shadcn/ui base
│   ├── layout/
│   │   ├── AppShell.tsx
│   │   ├── MobileNav.tsx
│   │   └── Header.tsx
│   │
│   ├── onboarding/                   # NEW
│   │   ├── OnboardingProgress.tsx    # Step indicator (1 of 4)
│   │   ├── FarmForm.tsx              # Farm name, location
│   │   ├── PlotForm.tsx              # Plot name, area, soil selector
│   │   ├── SoilSelector.tsx          # Preset dropdown + custom option
│   │   ├── SectorForm.tsx            # Sector name, crop type, variety, planting year
│   │   ├── CropTypeSelector.tsx      # Crop type cards with icons
│   │   ├── PhenologicalStageSelector.tsx  # Visual stage picker (timeline)
│   │   ├── IrrigationSystemForm.tsx  # System type, emitter specs
│   │   └── SkipPrompt.tsx            # "Skip for now — you can set this later"
│   │
│   ├── dashboard/
│   │   ├── FarmOverview.tsx
│   │   ├── SectorCard.tsx
│   │   ├── AlertsBanner.tsx
│   │   ├── MissingDataPrompt.tsx     # "Set phenological stage for Setor 4 to improve recommendations"
│   │   └── SetupCompletionBar.tsx    # NEW: Shows how much config is complete
│   │
│   ├── sector/
│   │   ├── SectorHeader.tsx
│   │   ├── RootzoneGauge.tsx
│   │   ├── RecommendationSummary.tsx
│   │   ├── IrrigationHistory.tsx
│   │   ├── ProbeStatusCards.tsx
│   │   └── SectorConfigSummary.tsx   # NEW: Shows current config with "edit" links
│   │
│   ├── probes/
│   │   ├── ProbeChart.tsx
│   │   ├── DepthSelector.tsx
│   │   └── TimeRangeSelector.tsx
│   │
│   ├── recommendation/
│   │   ├── RecommendationDetail.tsx
│   │   ├── ConfidenceBadge.tsx
│   │   ├── ReasonsList.tsx
│   │   ├── ComputationTrace.tsx
│   │   ├── AcceptRejectActions.tsx
│   │   └── MissingDataCallout.tsx    # NEW: "These missing inputs reduced confidence"
│   │
│   ├── forms/                        # NEW: Shared form components
│   │   ├── FormField.tsx             # Label + input + help tooltip
│   │   ├── PresetSelector.tsx        # Generic preset dropdown with "custom" option
│   │   ├── UnitInput.tsx             # Numeric input with unit label (mm, L/h, etc.)
│   │   └── OptionalFieldToggle.tsx   # "I know this" / "I don't know" toggle
│   │
│   ├── alerts/
│   │   ├── AlertCard.tsx
│   │   └── AlertFilters.tsx
│   └── shared/
│       ├── StatusIndicator.tsx
│       ├── ConfidenceBar.tsx
│       ├── EmptyState.tsx
│       └── LoadingSkeleton.tsx
│
├── lib/
│   ├── api.ts                        # Typed API client
│   ├── utils.ts
│   └── constants.ts
│
├── hooks/
│   ├── useFarmDashboard.ts
│   ├── useSectorDetail.ts
│   ├── useProbeReadings.ts
│   ├── useRecommendation.ts
│   ├── useCropProfileTemplates.ts    # NEW: Fetch available crop profiles
│   └── useSoilPresets.ts             # NEW: Fetch soil presets
│
└── types/
    └── index.ts
```

## What to Produce

### 1. Onboarding Flow

#### Entry Logic (`app/page.tsx`)
- If user has no farms → redirect to `/onboarding`
- If user has farms → redirect to `/dashboard`

#### Step 1: Farm (`onboarding/farm/page.tsx`)
- Farm name (required)
- Location: either address search (geocode) or manual lat/lon entry or "I'll set this later"
- Region (text, optional)
- Timezone (dropdown, default Europe/Lisbon)

#### Step 2: Plot(s) (`onboarding/plots/page.tsx`)
- Add one or more plots
- Per plot: name, area (ha, optional)
- Soil configuration:
  - `SoilSelector` component: dropdown of soil presets from API (`GET /api/v1/soil-presets`)
  - Each preset shows: name, texture, FC, PWP, TAW
  - "Personalizado" / "Custom" option → reveals FC and PWP numeric inputs
  - "Não sei" / "I don't know" option → uses loam defaults, adds to missing-data tracking
- Tooltip per field explaining impact: "O tipo de solo afeta o cálculo da água disponível."

#### Step 3: Sector(s) (`onboarding/sectors/page.tsx`)
- Add sectors to each plot
- Per sector: name, area (optional)
- **Crop type selector** (`CropTypeSelector`):
  - Shows available crop templates from API (`GET /api/v1/crop-profile-templates`)
  - Card layout with crop icon + name
  - On selection: loads the template stages and displays them as read-only preview
- Variety (text, optional)
- Planting year (optional for perennials) / Sowing date (for annuals)
- Tree spacing, row spacing (optional, shown only for tree crops)
- **Phenological stage selector** (`PhenologicalStageSelector`):
  - After crop type is selected, shows that crop's stages as a visual timeline
  - User taps the current stage
  - "Não sei" option → engine uses mid-season default
  - Tooltip: "Definir o estádio fenológico melhora a precisão em ~10%"
- Irrigation strategy: Full ETc (default), RDI, Deficit custom — show only if they want to customize

#### Step 4: Irrigation System (`onboarding/irrigation/page.tsx`)
- Per sector: configure the irrigation system
- System type selector (drip/pivot/sprinkler) with suggested defaults per type
- For drip: emitter flow (L/h), emitter spacing (m), lines per row, row spacing reference
- For pivot: application rate (mm/h), depth per pass
- Efficiency (pre-filled based on system type, editable)
- "Skip for now" clearly available — the system works without this but can't compute runtime

#### Completion
After step 4 (or any skip):
- Show completion summary: "Your farm is set up! Here's what's configured and what you can improve later."
- List any missing optional data with impact notes
- "Go to Dashboard" button

### 2. Configuration Forms (Settings)

All onboarding forms must be reusable as edit forms in the settings area:
- `settings/farm/page.tsx` — reuses `FarmForm`
- `settings/plots/page.tsx` — list plots with edit/add
- Sector edit (`sectors/[sectorId]/edit/page.tsx`) — reuses sector + irrigation forms

#### Crop Profile Editor (`settings/crop-profiles/page.tsx`)
- Lists crop profile templates
- Agronomist role can edit a template's stages (Kc values, MAD, root depths)
- Shows which sectors use which template
- Can create a new crop type template

### 3. Dashboard Page (`app/dashboard/page.tsx`)

Same as original Prompt 07 design, plus:

**Setup completion bar** (if farm is new or has missing config):
- Shows: "Farm setup: 75% complete"
- Lists the 1–2 most impactful missing items as actionable prompts
- "O Setor 4 - Guara não tem estádio fenológico definido. [Definir agora]"
- Disappears when everything is configured

**Missing data prompts** (`MissingDataPrompt` component):
- Pulls from dashboard API `missing_data_prompts` field
- Shows at bottom of dashboard, dismissible
- Links to the relevant edit form

### 4. Sector Detail Page

Same as original, plus:

**Config summary card** (`SectorConfigSummary`):
- Shows: crop type, variety, stage, soil type, irrigation system type
- Green checkmarks for configured items, amber warnings for missing
- "Editar" link for each → goes to edit form
- If phenological stage is outdated (set > 30 days ago), suggest update

### 5. Recommendation Detail Page

Same as original, plus:

**Missing data callout** (`MissingDataCallout`):
- At the top of the page if recommendation has missing_data items
- "Esta recomendação tem confiança reduzida porque faltam dados:"
- Lists each missing item with a link to configure it
- E.g., "Sistema de rega não configurado para este setor → [Configurar]"

### 6. All Other Pages

Probe chart, alerts, irrigation logging — same as original Prompt 07.

### 7. API Endpoints Needed by Frontend

The frontend needs these additional endpoints (beyond what Prompt 06 defined):

```
GET  /api/v1/crop-profile-templates         # List all templates
GET  /api/v1/crop-profile-templates/{id}     # Template detail
GET  /api/v1/soil-presets                    # List all presets
GET  /api/v1/sectors/{id}/crop-profile       # Sector's editable crop profile
PUT  /api/v1/sectors/{id}/crop-profile       # Update sector's crop profile
POST /api/v1/sectors/{id}/crop-profile/reset # Reset to template defaults
```

**Add these endpoints to `api/v1/` if not already defined in Prompt 06.**

---

## Design Principles

1. **Mobile-first.** All screens work on a phone in bright sunlight.
2. **Glanceable dashboard.** "What should I do today?" in < 3 seconds.
3. **Progressive disclosure.** Simple by default, detail on demand.
4. **Forms explain themselves.** Every field has context about why it matters.
5. **Skip is always OK.** The system degrades gracefully with missing data.
6. **Color coding:** Green = good, Amber = attention, Red = critical, Blue = info.
7. **Bilingual:** pt-PT primary, English secondary.

---

## Done When

1. Onboarding flow: new user can create a farm with plots, sectors, and irrigation systems.
2. Soil selector loads presets from API and allows custom entry.
3. Crop type selector loads templates from API and shows stage preview.
4. Phenological stage selector shows the crop's stages as a visual timeline.
5. Dashboard shows setup completion bar for incomplete farms.
6. Recommendation detail shows missing-data callout with links to configure.
7. All forms are reusable in settings for editing existing records.
8. Responsive on 375px viewport.
9. All API calls work with the backend.

## Iteration Protocol

- Test the onboarding flow end-to-end: create a farm from scratch.
- Verify that after onboarding, the dashboard loads with the new farm's data.
- Verify that a sector created without irrigation system shows the correct missing-data prompts.
- Test form validation: required fields, numeric ranges, etc.
