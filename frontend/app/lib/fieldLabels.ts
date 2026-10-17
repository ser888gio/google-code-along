import { RS_SECTIONS } from "../generated/rsSchema";

type Translate = (key: string) => string;

// Schema labels (English) → i18n keys. Labels without an entry fall back to the
// raw schema label.
const FIELD_LABEL_KEYS: Record<string, string> = {
	"Use Case Title (EN)": "rs.field.use_case_title",
	"Customer Department": "rs.field.customer_department",
	Requester: "rs.field.requester",
	"Product Owner": "rs.field.product_owner",
	"Target Users": "rs.field.target_users",
	"Refresh Frequency": "rs.field.report_frequency",
	"Process Description / As-Is": "rs.field.process_description_as_is",
	"Process Context": "rs.field.process_context",
	Trigger: "rs.field.trigger",
	"Purpose / To-Be": "rs.field.purpose_to_be",
	"Key Business Questions": "rs.field.key_business_questions",
	"KPIs & Metrics": "rs.field.kpis_and_metrics",
	"Saved Time (hours/year)": "rs.field.saved_time_hours_per_year",
	"Cost Saving": "rs.field.cost_saving",
	"Revenue Increase": "rs.field.revenue_increase",
	"Impacted Users": "rs.field.impacted_users",
	"Added Value": "rs.field.added_value",
	"Time Criticality": "rs.field.time_criticality",
	"Strategic Impact": "rs.field.strategic_impact",
	"Risk Avoidance": "rs.field.risk_avoidance",
	"Acceptance Criteria": "rs.field.acceptance_criteria",
	"Systems & Tools Involved": "rs.field.systems_and_tools",
	"Types of Documents Involved": "rs.field.document_types",
	"Dimensions & Data Cuts": "rs.field.dimensions_and_cuts",
	"Data Security Classification": "rs.field.data_security_classification",
	"Solution Type": "rs.field.solution_type",
	Comments: "rs.field.comments",
	"Attachments (GCS paths)": "rs.field.attachments",
};

const LABEL_BY_FIELD_KEY = new Map(
	RS_SECTIONS.flatMap((section) => section.fields).map((f) => [f.key, f.label]),
);

export function translateFieldLabel(label: string, t: Translate): string {
	const key = FIELD_LABEL_KEYS[label];
	return key ? t(key) : label;
}

/** Translated label for a schema field key, e.g. "report_frequency". */
export function fieldLabelForKey(fieldKey: string, t: Translate): string {
	const label = LABEL_BY_FIELD_KEY.get(fieldKey);
	return label ? translateFieldLabel(label, t) : fieldKey.replace(/_/g, " ");
}
