# Domain Relation Types

## HAS_ACTIVE_INGREDIENT
Links a DRUG_PRODUCT to its ACTIVE_INGREDIENT(s)

## HAS_INACTIVE_INGREDIENT
Links a DRUG_PRODUCT to its INACTIVE_INGREDIENT(s)

## MANUFACTURES
A MANUFACTURER manufactures a DRUG_PRODUCT (MANUFACTURER → DRUG_PRODUCT)

## INDICATED_FOR
Links a DRUG_PRODUCT to an INDICATION (FDA-approved use)

## CONTRAINDICATED_IN
Links a DRUG_PRODUCT to a CONTRAINDICATION (prohibited patient condition)

## CAUSES_ADVERSE_REACTION
Links a DRUG_PRODUCT to an ADVERSE_REACTION observed in clinical or post-marketing data

## HAS_WARNING
Links a DRUG_PRODUCT to a WARNING (boxed or standard precaution)

## INTERACTS_WITH
Links a DRUG_PRODUCT to another DRUG_PRODUCT or substance involved in a clinically significant DRUG_INTERACTION

## DOSED_VIA
Links a DRUG_PRODUCT to a DOSAGE_REGIMEN specifying how and when to administer it

## STUDIED_IN_POPULATION
Links a DRUG_PRODUCT to a PATIENT_POPULATION with special safety or dosing notes

## HAS_MECHANISM
Links a DRUG_PRODUCT to its MECHANISM_OF_ACTION

## HAS_PK_PROPERTY
Links a DRUG_PRODUCT to a PHARMACOKINETIC_PROPERTY

## EVALUATED_IN
Links a DRUG_PRODUCT to a CLINICAL_STUDY that supported label claims

## BELONGS_TO_CLASS
Links a DRUG_PRODUCT to its PHARMACOLOGIC_CLASS

## IDENTIFIES
A REGULATORY_IDENTIFIER (NDC, NDA/ANDA, RxCUI, etc.) identifies a DRUG_PRODUCT (REGULATORY_IDENTIFIER → DRUG_PRODUCT)

## CONTRAINDICATED_WITH
Links a DRUG_PRODUCT to another DRUG_PRODUCT whose co-administration is explicitly prohibited
