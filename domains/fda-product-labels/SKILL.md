# fda-product-labels Domain

You are analyzing FDA Structured Product Labeling (SPL) documents — the authoritative regulatory labels submitted by manufacturers for prescription and over-the-counter drug products. Each document is a JSON file containing clinical sections (indications, contraindications, warnings, adverse reactions, pharmacology) alongside structured openfda metadata (brand/generic names, NDC codes, pharmacologic class, manufacturer). Extract precise, clinically meaningful entities and relationships that would support pharmacovigilance, formulary analysis, drug interaction screening, and regulatory intelligence.

## Entity Types

| Type | Description |
|------|-------------|
| DRUG_PRODUCT | A drug product identified by brand/generic name, product type (Rx/OTC), dosage form, and route of administration |
| ACTIVE_INGREDIENT | An active pharmaceutical ingredient (API) with substance name and UNII code |
| INACTIVE_INGREDIENT | An excipient or inactive ingredient in the formulation |
| MANUFACTURER | The manufacturer, labeler, or marketing company responsible for the drug product |
| INDICATION | An FDA-approved therapeutic use or clinical condition the drug is indicated to treat |
| CONTRAINDICATION | A patient condition, prior history, or co-medication that prohibits use of the drug |
| ADVERSE_REACTION | An adverse event or side effect observed in clinical trials or post-marketing surveillance |
| WARNING | A boxed warning, warnings-and-precautions entry, or safety signal requiring clinician action |
| DRUG_INTERACTION | A clinically significant interaction between this drug and another drug, substance, or food that affects safety or efficacy |
| DOSAGE_REGIMEN | A specific dosing instruction including dose amount, frequency, route, and target patient population |
| PATIENT_POPULATION | A patient subgroup with special dosing or safety considerations (pediatric, geriatric, renally impaired, pregnant, nursing mothers) |
| MECHANISM_OF_ACTION | The pharmacological mechanism by which the active ingredient produces its therapeutic effect |
| PHARMACOKINETIC_PROPERTY | A PK parameter including absorption, distribution, metabolism, excretion, half-life, Cmax, bioavailability, or protein binding |
| CLINICAL_STUDY | A clinical trial or study referenced in the label to support safety or efficacy claims |
| PHARMACOLOGIC_CLASS | An FDA-recognized drug class designation (EPC, MoA, Chemical Structure, or PE classification) |
| REGULATORY_IDENTIFIER | A regulatory code such as NDA/ANDA application number, NDC code, RxCUI, UNII, or SPL set ID |
| LABTEST | A laboratory monitoring test referenced in the label for tracking drug safety or efficacy (e.g. liver function tests for hepatotoxic drugs, CBC for immunosuppressants, lipid panels for statins, INR for anticoagulants) |

## Relation Types

Direction matters: write each relation from the Source type to the Target type. Relations marked symmetric may be written either way.

| Type | Source → Target | Description |
|------|-----------------|-------------|
| HAS_ACTIVE_INGREDIENT | DRUG_PRODUCT → ACTIVE_INGREDIENT | Links a DRUG_PRODUCT to its ACTIVE_INGREDIENT(s) |
| HAS_INACTIVE_INGREDIENT | DRUG_PRODUCT → INACTIVE_INGREDIENT | Links a DRUG_PRODUCT to its INACTIVE_INGREDIENT(s) |
| MANUFACTURES | MANUFACTURER → DRUG_PRODUCT | A MANUFACTURER manufactures a DRUG_PRODUCT. |
| INDICATED_FOR | DRUG_PRODUCT → INDICATION | Links a DRUG_PRODUCT to an INDICATION (FDA-approved use) |
| CONTRAINDICATED_IN | DRUG_PRODUCT → CONTRAINDICATION | Links a DRUG_PRODUCT to a CONTRAINDICATION (prohibited patient condition) |
| CAUSES_ADVERSE_REACTION | DRUG_PRODUCT → ADVERSE_REACTION | Links a DRUG_PRODUCT to an ADVERSE_REACTION observed in clinical or post-marketing data |
| HAS_WARNING | DRUG_PRODUCT → WARNING | Links a DRUG_PRODUCT to a WARNING (boxed or standard precaution) |
| INTERACTS_WITH | DRUG_PRODUCT → DRUG_INTERACTION/DRUG_PRODUCT/ACTIVE_INGREDIENT | Links a DRUG_PRODUCT to another DRUG_PRODUCT or substance involved in a clinically significant DRUG_INTERACTION |
| DOSED_VIA | DRUG_PRODUCT → DOSAGE_REGIMEN | Links a DRUG_PRODUCT to a DOSAGE_REGIMEN specifying how and when to administer it |
| STUDIED_IN_POPULATION | DRUG_PRODUCT → PATIENT_POPULATION | Links a DRUG_PRODUCT to a PATIENT_POPULATION with special safety or dosing notes |
| HAS_MECHANISM | DRUG_PRODUCT/ACTIVE_INGREDIENT → MECHANISM_OF_ACTION | Links a DRUG_PRODUCT to its MECHANISM_OF_ACTION |
| HAS_PK_PROPERTY | DRUG_PRODUCT/ACTIVE_INGREDIENT → PHARMACOKINETIC_PROPERTY | Links a DRUG_PRODUCT to a PHARMACOKINETIC_PROPERTY |
| EVALUATED_IN | DRUG_PRODUCT → CLINICAL_STUDY | Links a DRUG_PRODUCT to a CLINICAL_STUDY that supported label claims |
| BELONGS_TO_CLASS | DRUG_PRODUCT/ACTIVE_INGREDIENT → PHARMACOLOGIC_CLASS | Links a DRUG_PRODUCT to its PHARMACOLOGIC_CLASS |
| IDENTIFIES | REGULATORY_IDENTIFIER → DRUG_PRODUCT | A REGULATORY_IDENTIFIER (NDC, NDA/ANDA, RxCUI, etc.) identifies a DRUG_PRODUCT. |
| CONTRAINDICATED_WITH | DRUG_PRODUCT → DRUG_PRODUCT/ACTIVE_INGREDIENT (symmetric) | Links a DRUG_PRODUCT to another DRUG_PRODUCT whose co-administration is explicitly prohibited |
| HAS_LABTEST | DRUG_PRODUCT/WARNING → LABTEST | The label calls for monitoring with a LABTEST — from the DRUG_PRODUCT, or from the WARNING the monitoring guards against. |
| WARNS_OF | WARNING → ADVERSE_REACTION | A WARNING concerns a specific ADVERSE_REACTION (e.g. the boxed warning "Risk of thyroid C-cell tumors" warns of medullary thyroid carcinoma). |

## Extraction Guidelines

1. Extract DRUG_PRODUCT from openfda.brand_name, openfda.generic_name, openfda.product_type, and openfda.route fields; include SPL id and set_id as attributes.
2. Extract ACTIVE_INGREDIENT from openfda.substance_name and UNII, and from the active_ingredient or spl_product_data_elements sections; include strength if stated.
3. Extract INACTIVE_INGREDIENT from the inactive_ingredient section; list each excipient as a separate entity.
4. Extract MANUFACTURER from openfda.manufacturer_name; note if the manufacturer is also the original packager.
5. Extract INDICATION from the indications_and_usage section; create one entity per distinct approved use or condition.
6. Extract CONTRAINDICATION from the contraindications section; note specific patient populations when stated.
7. Extract ADVERSE_REACTION from the adverse_reactions section; prioritize reactions with incidence data or ≥2% frequency over placebo.
8. Extract WARNING from the boxed_warning section (mark as boxed=true) and from warnings_and_cautions or warnings sections; name the specific hazard.
9. Extract DRUG_INTERACTION from the drug_interactions section; identify the interacting drug/class and the clinical consequence.
10. Extract DOSAGE_REGIMEN from the dosage_and_administration section; include dose, frequency, route, and any titration instructions; create separate entities per population or indication if multiple regimens are specified.
11. Extract PATIENT_POPULATION from use_in_specific_populations, pediatric_use, geriatric_use, pregnancy, and nursing_mothers sections; note dose adjustments or contraindications specific to the population.
12. Extract MECHANISM_OF_ACTION from the mechanism_of_action or clinical_pharmacology section; state the molecular target and pharmacological effect.
13. Extract PHARMACOKINETIC_PROPERTY from the pharmacokinetics section; create one entity per parameter (half-life, Cmax, AUC, protein binding, bioavailability, metabolic pathway, renal/hepatic excretion).
14. Extract CLINICAL_STUDY from the clinical_studies section; include study design, population size, and primary endpoint if stated.
15. Extract PHARMACOLOGIC_CLASS from openfda.pharm_class_epc, pharm_class_moa, pharm_class_cs, and pharm_class_pe; classify each by type (EPC, MoA, CS, or PE).
16. Extract REGULATORY_IDENTIFIER from openfda.application_number (NDA/ANDA), openfda.product_ndc, openfda.rxcui, openfda.unii, and set_id/id (SPL IDs).
17. Extract LABTEST from sections that reference laboratory monitoring (warnings_and_cautions, adverse_reactions, clinical_pharmacology); create one entity per distinct test (e.g. ALT, AST, total bilirubin, complete blood count, serum creatinine, INR, lipid panel); prefer named tests over generic phrases like "blood work". Include the monitoring purpose as context when stated (e.g. "monitor LFTs every 4 weeks during therapy").
18. Relation endpoints (source_entity / target_entity) MUST be the exact `name` of an entity declared in the same extraction. Never use placeholder IDs such as "DRUG_PRODUCT_1" or "INDICATION_1", and declare every entity before referencing it — a relation whose endpoint is not a declared entity name is dropped at build.
19. Name the DRUG_PRODUCT by its brand name (e.g. "Lipitor"), and reuse that exact name as the source of every DRUG_PRODUCT relation.
20. HAS_WARNING targets a WARNING entity named for the hazard (e.g. "Risk of thyroid C-cell tumors"); never point HAS_WARNING at an ADVERSE_REACTION. When the warning concerns a specific reaction, also link WARNS_OF (WARNING → ADVERSE_REACTION). A WARNING must never share a name with any other entity in the same extraction, compared case-insensitively — the graph builder resolves relation endpoints by name, so "malignancy" as both a WARNING and an ADVERSE_REACTION sends the edges to the wrong node. Prefix warnings with "Risk of" (e.g. WARNING "Risk of malignancy" WARNS_OF ADVERSE_REACTION "lymphoma"). The same applies to every type pair: one name, one entity.
21. When the label calls for laboratory monitoring, link HAS_LABTEST from the DRUG_PRODUCT (or from the WARNING it guards against) to the LABTEST.
22. Use the active relation names exactly as written (MANUFACTURES, IDENTIFIES) — write the manufacturer or identifier first. Never use passive "*_BY" forms; the graph builder rewrites them.
