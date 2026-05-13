"""Solution-type-aware rubric and example overrides.

Each entry in SOLUTION_CONFIGS maps a solution-type slug to a dict of
field-key → SolutionFieldOverride. Only fields that need a solution-specific
rubric or example need to appear here; the rest fall back to field_schema.py
defaults automatically.

get_field_rubric_block() is the single entry point used by the classifier
and extraction prompts — it merges field_schema defaults with the override.
"""

from __future__ import annotations

from typing import TypedDict

from field_schema import FIELD_SCHEMA


class SolutionFieldOverride(TypedDict, total=False):
    validation_mode: str
    expected_shape: str
    example_good: str
    rubric: list[str]


SolutionConfig = dict[str, SolutionFieldOverride]


# ---------------------------------------------------------------------------
# Per-solution configs
# ---------------------------------------------------------------------------

_POWER_BI: SolutionConfig = {
    "use_case_title": {
        "example_good": "Patents Reporting",
        "rubric": [
            "Names the BI deliverable, not the business problem",
            "Written in English",
            "Concise (2–6 words)",
        ],
    },
    "department": {
        "example_good": "Patent department (3-letter code level)",
        "rubric": [
            "Identifies a specific department or business unit",
            "Includes team code or hierarchy level if relevant",
        ],
    },
    "target_users": {
        "example_good": "All employees viewing the annual BI report; patent department analysts.",
        "rubric": [
            "Names the primary audience (role, group, or department)",
            "Distinguishes report consumers from report editors if relevant",
        ],
    },
    "report_frequency": {
        "example_good": "Monthly data refresh; annual summary report published in January.",
        "rubric": [
            "States refresh cadence (daily/weekly/monthly/annual/ad-hoc)",
            "Notes any special publishing cycle",
        ],
    },
    "process_as_is": {
        "example_good": (
            "Manual processing of data from WinPAT and Excel into a PowerPoint report; "
            "manual email distribution; ad-hoc lookups in WinPAT to answer employee questions."
        ),
        "rubric": [
            "Describes concrete current-state steps",
            "Names source systems used today (e.g. WinPAT, SAP, Excel)",
            "Identifies at least one pain point (manual effort, errors, slow access)",
        ],
    },
    "process_context": {
        "example_good": (
            "Triggered annually after patent application data is closed for the year; "
            "output feeds the management presentation cycle."
        ),
        "rubric": [
            "Describes upstream data source or trigger",
            "Describes downstream consumer (who uses the report output)",
        ],
    },
    "purpose_to_be": {
        "example_good": (
            "Automate annual report preparation, eliminate manual rewriting and errors, "
            "expand with historical insight, ensure BI report availability via a single "
            "link without forwarding presentations."
        ),
        "rubric": [
            "Describes what the Power BI report will replace or automate",
            "Names at least one specific improvement vs. as-is",
            "Mentions self-service access or single-link availability",
        ],
    },
    "key_business_questions": {
        "example_good": (
            "1) How many patent applications were filed in a given period? "
            "2) How does the count break down by department over time? "
            "3) Who in each department has the most applications?"
        ),
        "rubric": [
            "Lists at least 2 concrete, data-answerable questions",
            "Questions reflect business decisions or monitoring needs",
            "At least one question involves time or trend analysis",
        ],
    },
    "kpis_and_metrics": {
        "expected_shape": "Named metrics with definition, unit, and dimension breakdown.",
        "example_good": (
            "Number of patent applications: count of PRIO + EP + PCT in the selected period. Unit: count. "
            "Breakdown: by department, by year."
        ),
        "rubric": [
            "Names each KPI explicitly",
            "States the unit (count, %, EUR, hours)",
            "Defines calculation logic or source",
            "Names at least one breakdown dimension",
        ],
    },
    "impacted_users": {
        "example_good": "~15 patent department employees; ~8 hours/year each saved.",
        "rubric": [
            "Gives a user count or range",
            "Gives time-saved-per-user or aggregate savings",
        ],
    },
    "add_value": {
        "example_good": (
            "Self-service access for all employees; historical trend visibility; "
            "reduced risk of manual transcription errors in the annual presentation."
        ),
        "rubric": [
            "Names at least one qualitative benefit beyond cost savings",
            "Mentions self-service or reduced dependency on a single person",
        ],
    },
    "time_criticality": {
        "example_good": "Priority: Medium. Required by 14.01.2026 for annual management review.",
        "rubric": [
            "Picks a priority level (Low / Medium / High) or numeric tier",
            "Names a deadline or explicitly says none",
        ],
    },
    "strategic_impact": {
        "example_good": (
            "Supports IP strategy reporting to the executive team; "
            "aligns with the company-wide BI self-service initiative."
        ),
        "rubric": [
            "Connects to a named strategic objective or company initiative",
            "Not just 'important' without context",
        ],
    },
    "acceptance_criteria": {
        "example_good": (
            "Counts in Power BI match WinPAT for selected period; correct department mapping; "
            "replaces page 2 of the PPT with interactive filtering; "
            "employees can filter their own applications."
        ),
        "rubric": [
            "Lists at least 3 verifiable acceptance conditions",
            "Covers data accuracy (numbers match source)",
            "Covers user-visible behaviour (filtering, export, access)",
        ],
    },
    "systems_and_tools": {
        "example_good": "WinPAT (source), Excel exports, Databricks (planned), Power BI (target).",
        "rubric": [
            "Names at least one source system by name",
            "Names the target/output platform (Power BI)",
            "Notes integration status if relevant (planned, existing, TBD)",
        ],
    },
    "document_types": {
        "example_good": "Excel exports from WinPAT; PowerPoint annual report; tabular patent application data.",
        "rubric": [
            "Names at least one input document or data format",
            "Names the output format (report, dashboard, export)",
        ],
    },
    "dimensions_and_cuts": {
        "example_good": (
            "Time: year (drill-down to quarter/month if available). "
            "Organisation: department hierarchy to 3-letter level. "
            "Critical combination: department × time."
        ),
        "rubric": [
            "Names time dimension and granularity (year / quarter / month)",
            "Names organisational or categorical dimension",
            "Calls out the most important cross-dimension combination",
        ],
    },
    "data_security_classification": {
        "example_good": (
            "Confidential at source (patent names); Internal in the report after redaction; "
            "visible to all employees."
        ),
        "rubric": [
            "Picks an explicit classification level (Public / Internal / Confidential / Restricted)",
            "Notes who may access the report (audience or RLS rules)",
        ],
    },
    "solution_type": {
        "example_good": "Power BI report (analytical) backed by Databricks once available, Excel exports in the interim.",
        "rubric": [
            "Confirms Power BI as the target platform",
            "Mentions backing data layer or integration if known",
        ],
    },
}


_POWER_APPS: SolutionConfig = {
    "use_case_title": {
        "example_good": "F Educational Training Overview",
        "rubric": [
            "Names the app or automation deliverable, not the problem",
            "Written in English",
            "Concise (2–6 words)",
        ],
    },
    "department": {
        "example_good": "F (department code)",
        "rubric": [
            "Provides the department code or name that owns the app",
        ],
    },
    "target_users": {
        "example_good": "F Academy training coordinators; managers reviewing participation data.",
        "rubric": [
            "Names the primary app users by role",
            "Distinguishes data-entry users from read-only viewers if relevant",
        ],
    },
    "process_as_is": {
        "example_good": (
            "Currently no unified overview of trainings organised by F Academy exists. "
            "Data is tracked ad hoc in spreadsheets or not at all."
        ),
        "rubric": [
            "Describes the current manual or missing process",
            "Names the pain point (no overview, scattered data, errors)",
        ],
    },
    "process_context": {
        "example_good": (
            "Training events are booked via SAP and Booking; attendance data needs to be "
            "surfaced for KPI and strategic planning purposes."
        ),
        "rubric": [
            "Names upstream systems where source data lives (SAP, Booking, SharePoint)",
            "Explains how the app output is used (KPI reporting, planning)",
        ],
    },
    "purpose_to_be": {
        "example_good": (
            "Evidence of organised F educational events and participant counts, "
            "ideally in a Power App or improved Excel, so it is clear what is organised "
            "and how many people attend."
        ),
        "rubric": [
            "Describes what the app will track or display",
            "Names the target platform (Power App, Excel, SharePoint list)",
            "States what decision or visibility gap it closes",
        ],
    },
    "key_business_questions": {
        "example_good": (
            "1) Which trainings were organised by F Academy and when? "
            "2) How many participants attended each event? "
            "3) Which target groups were reached?"
        ),
        "rubric": [
            "Lists at least 2 questions the app must answer",
            "At least one question is about participant counts or event history",
        ],
    },
    "kpis_and_metrics": {
        "expected_shape": "Training KPIs: event count, participant count, target group coverage.",
        "example_good": (
            "Number of training events organised: count per period. "
            "Number of participants: headcount per event and cumulative. "
            "Target group coverage: % of target population trained."
        ),
        "rubric": [
            "Names each metric (event count, participant headcount, etc.)",
            "States the unit (count, %)",
            "Relates metrics to KPI or strategic goal",
        ],
    },
    "systems_and_tools": {
        "example_good": "SAP (source for bookings), Booking tool, SharePoint (document storage).",
        "rubric": [
            "Names the source system(s) where training data lives",
            "Names the target platform (Power App, SharePoint, Power Automate)",
        ],
    },
    "document_types": {
        "example_good": "SharePoint lists or libraries; possibly Excel attendance sheets.",
        "rubric": [
            "Names input data sources (SharePoint lists, Excel)",
            "Names output format (Power App screen, Excel report)",
        ],
    },
    "saved_time_hours_per_year": {
        "example_good": "~10 hours/year saved by eliminating manual tracking.",
        "rubric": [
            "Provides a numeric estimate, even if rough",
        ],
    },
    "add_value": {
        "example_good": (
            "Data important for KPIs and strategy. "
            "Provides overview and targeting of education for specific target groups."
        ),
        "rubric": [
            "Mentions KPI or strategic alignment",
            "Names at least one group that benefits from better visibility",
        ],
    },
    "data_security_classification": {
        "example_good": "Internal — training participation data visible to HR and managers.",
        "rubric": [
            "Picks Internal or Confidential",
            "Notes who can access (HR, managers, all employees)",
        ],
    },
    "time_criticality": {
        "example_good": "Low urgency — time criticality tier 1 (>24 months to critical impact).",
        "rubric": [
            "Picks a priority tier or level",
            "Notes any deadline or confirms none",
        ],
    },
    "impacted_users": {
        "example_good": "2–5 users (coordinators and managers).",
        "rubric": [
            "Gives a user count or range",
        ],
    },
    "strategic_impact": {
        "example_good": "Small strategic impact — supports HR KPI tracking and F Academy reporting.",
        "rubric": [
            "States impact level (Small / Medium / Large)",
            "Links to a specific KPI or strategic initiative",
        ],
    },
    "solution_type": {
        "example_good": "Power App (canvas app for data entry and overview) backed by SharePoint list.",
        "rubric": [
            "Confirms Power Apps or Power Platform as the target",
            "Mentions backing data store (SharePoint, Dataverse)",
        ],
    },
}


_MACHINE_LEARNING: SolutionConfig = {
    "use_case_title": {
        "example_good": "Sales Demand Forecasting Model",
        "rubric": [
            "Names the ML output (model, prediction, classifier)",
            "Written in English",
            "Concise (2–6 words)",
        ],
    },
    "purpose_to_be": {
        "expected_shape": "What the model predicts, replaces, or automates, and how it improves decisions.",
        "example_good": (
            "Predict weekly demand per SKU 4 weeks ahead to reduce overstock and stockouts; "
            "replace manual planner estimates with model-driven forecasts reviewed by planners."
        ),
        "rubric": [
            "States the prediction target (what is being predicted)",
            "States the forecast horizon or classification threshold",
            "Names the decision or process the model improves",
        ],
    },
    "key_business_questions": {
        "example_good": (
            "1) What demand is expected per SKU next 4 weeks? "
            "2) Which SKUs have the highest forecast error? "
            "3) Where can safety stock be reduced without risk?"
        ),
        "rubric": [
            "Lists at least 2 questions the model output must answer",
            "Questions relate to prediction, anomaly, or prioritisation",
        ],
    },
    "kpis_and_metrics": {
        "expected_shape": "Model performance metrics + business impact metrics.",
        "example_good": (
            "Model accuracy: MAPE ≤ 15% on held-out test set. "
            "Business impact: reduce overstock by 10%, stockouts by 15%. "
            "Retraining frequency: weekly."
        ),
        "rubric": [
            "Names at least one model performance metric (MAPE, AUC, F1, RMSE)",
            "States the acceptance threshold for the metric",
            "Includes at least one business outcome metric",
        ],
    },
    "process_as_is": {
        "example_good": (
            "Planners manually estimate demand using last year's sales and gut feel; "
            "process takes ~2 hours per planner per week; high variance leads to overstock."
        ),
        "rubric": [
            "Describes current manual estimation or rule-based process",
            "Names who does the work and how long it takes",
            "Identifies the key pain point (inaccuracy, manual effort, slow)",
        ],
    },
    "systems_and_tools": {
        "example_good": (
            "SAP (source of sales and inventory data), "
            "Azure ML or Databricks (model training), "
            "Power BI (output dashboard for planners)."
        ),
        "rubric": [
            "Names the source data system (ERP, data warehouse)",
            "Names the ML platform (Azure ML, Databricks, Vertex AI, etc.)",
            "Names the output consumer (dashboard, API, downstream system)",
        ],
    },
    "document_types": {
        "example_good": "Historical sales CSV exports from SAP; inventory snapshots; model artefact files (.pkl / .joblib).",
        "rubric": [
            "Names training data format/source",
            "Names model artefact or output format",
        ],
    },
    "dimensions_and_cuts": {
        "example_good": (
            "Time: week (forecast horizon 4 weeks). "
            "Product: SKU level, rollup to category. "
            "Geography: warehouse/region level."
        ),
        "rubric": [
            "Names forecast granularity (time bucket, product level, geography)",
            "Notes rollup levels if predictions are aggregated",
        ],
    },
    "acceptance_criteria": {
        "example_good": (
            "MAPE ≤ 15% on 8-week holdout; no systematic bias by product category; "
            "model retrained and deployed weekly without manual intervention; "
            "planner override rate < 30%."
        ),
        "rubric": [
            "States at least one quantitative acceptance threshold (MAPE, AUC, etc.)",
            "States at least one operational condition (retraining, deployment, SLA)",
            "States at least one business acceptance condition",
        ],
    },
    "data_security_classification": {
        "example_good": "Internal — sales and inventory data; model outputs visible to planners and supply chain managers.",
        "rubric": [
            "Picks classification level for training data",
            "Notes who can access model predictions",
        ],
    },
    "solution_type": {
        "example_good": "Machine learning forecasting model (Python / Azure ML) with Power BI output dashboard.",
        "rubric": [
            "Names the ML approach (forecasting, classification, clustering, NLP)",
            "Names the platform or framework",
            "Names how predictions are consumed (API, dashboard, file export)",
        ],
    },
    "add_value": {
        "example_good": (
            "Frees planners from manual estimation; reduces overstock cost; "
            "enables data-driven safety stock decisions."
        ),
        "rubric": [
            "Names at least one operational benefit beyond accuracy",
            "Mentions freed-up human time or improved decision quality",
        ],
    },
}


SOLUTION_CONFIGS: dict[str, SolutionConfig] = {
    "power_bi": _POWER_BI,
    "power_apps": _POWER_APPS,
    "machine_learning": _MACHINE_LEARNING,
    "generic": {},
}

# Normalised keyword → slug
_SLUG_MAP: dict[str, str] = {
    "power bi": "power_bi",
    "powerbi": "power_bi",
    "power bi report": "power_bi",
    "power bi dashboard": "power_bi",
    "reporting": "power_bi",
    "report": "power_bi",
    "dashboard": "power_bi",
    "power apps": "power_apps",
    "power app": "power_apps",
    "powerapps": "power_apps",
    "powerapp": "power_apps",
    "canvas app": "power_apps",
    "model-driven app": "power_apps",
    "power automate": "power_apps",
    "power platform": "power_apps",
    "machine learning": "machine_learning",
    "ml": "machine_learning",
    "ai model": "machine_learning",
    "prediction": "machine_learning",
    "forecasting": "machine_learning",
    "classification": "machine_learning",
    "nlp": "machine_learning",
}


def get_solution_config(solution_type: str | None) -> SolutionConfig:
    """Return the config for the given solution type string, falling back to generic."""
    if not solution_type:
        return SOLUTION_CONFIGS["generic"]
    normalised = solution_type.lower().strip()
    slug = _SLUG_MAP.get(normalised, "generic")
    return SOLUTION_CONFIGS.get(slug, SOLUTION_CONFIGS["generic"])


def get_field_rubric_block(field_key: str, solution_type: str | None = None) -> str:
    """Return a prompt-ready rubric block for one field, merged with solution-type override.

    The solution-type config wins over field_schema defaults for any key it provides.
    Falls back gracefully if either layer is missing.
    """
    base = FIELD_SCHEMA.get(field_key, {})
    override = get_solution_config(solution_type).get(field_key, {})

    label = base.get("label", field_key)
    mode = override.get("validation_mode") or base.get("validation_mode", "soft")
    shape = override.get("expected_shape") or base.get("expected_shape", "")
    rubric: list[str] = override.get("rubric") or base.get("rubric") or []
    example = override.get("example_good") or base.get("example_good", "")

    parts: list[str] = []
    parts.append(f"Field: {label} (key: {field_key})")
    parts.append(f"Validation mode: {mode}")
    if shape:
        parts.append(f"Expected shape: {shape}")
    if rubric:
        bullets = "\n".join(f"  - {item}" for item in rubric)
        parts.append(f"Must cover:\n{bullets}")
    if example:
        parts.append(f"Example of a strong answer: {example}")
    return "\n".join(parts)


def get_all_field_shapes(solution_type: str | None = None) -> str:
    """One-line shape summary per field for the bulk extraction prompt.

    Prefers solution-type override's expected_shape, falls back to field_schema default.
    """
    config = get_solution_config(solution_type)
    lines: list[str] = []
    for key, field in FIELD_SCHEMA.items():
        override = config.get(key, {})
        shape = override.get("expected_shape") or field.get("expected_shape", "")
        if not shape:
            continue
        mode = override.get("validation_mode") or field.get("validation_mode", "soft")
        lines.append(f"- {key} [{mode}]: {shape}")
    return "\n".join(lines)
