# Domain Relation Types

## EXPERIENCED
**Patient → AdverseEvent**

A Patient experienced an AdverseEvent.

## TOOK
**Patient → Drug/Concomitant**

A Patient took a Drug or Concomitant prior to or during the AdverseEvent window.

## INDICATED_FOR
**Drug/Concomitant → Indication**

A Drug or Concomitant is indicated for an Indication (the prescribed reason for use).

## CO_ADMINISTERED_WITH
**Drug → Drug/Concomitant** (symmetric)

A Drug was co-administered with a Concomitant, or with another suspect Drug, during the same exposure window. Symmetric — material to drug-drug interaction signal detection.

## REPORTS
**Reporter → ReportType/Patient/AdverseEvent**

A Reporter submitted the report — link the Reporter to the ReportType (database / report kind), to the case Patient, or to a reported AdverseEvent. Reporter identity (HCP, consumer, lawyer, sponsor) conditions epistemic weight. Active form on purpose — sift-kg rewrites any "*ED_BY" name at build time (REPORTED_BY would become REPORTES).

## RESULTED_IN
**AdverseEvent → Outcome**

An AdverseEvent resulted in an Outcome (recovered, sequelae, fatal, unknown).

## OCCURRED_AFTER
**AdverseEvent → Drug**

An AdverseEvent occurred after a Drug exposure with a stated TemporalRelationship. Foundation of the temporality criterion.

## RESOLVED_ON_DECHALLENGE
**AdverseEvent → Drug/DechallengeRechallenge**

An AdverseEvent resolved when the suspect Drug was withdrawn — link to the withdrawn Drug, or to the DechallengeRechallenge entity that documents it.

## RECURRED_ON_RECHALLENGE
**AdverseEvent → Drug/DechallengeRechallenge**

An AdverseEvent recurred when the suspect Drug was reintroduced — link to the reintroduced Drug, or to the DechallengeRechallenge entity that documents it. Strongest single-case causality signal.

## CAUSES
**Drug/Concomitant → AdverseEvent**

A Drug (or Concomitant) is asserted to cause an AdverseEvent. Asserted only when Bradford-Hill criteria are met or when the source explicitly attributes causation. Active form on purpose — sift-kg rewrites CAUSED_BY to CAUSES at build time, and crosswalk.yaml projects CAUSES.

## TRIGGERED
**CausalitySignal/AdverseEvent → RegulatoryAction**

A CausalitySignal or AdverseEvent cluster triggered a RegulatoryAction (label change, withdrawal, REMS).

## CONTRADICTS
**CausalitySignal/DechallengeRechallenge/ReportType → CausalitySignal/DechallengeRechallenge/ReportType** (symmetric)

A claim from one report or database contradicts a claim from another (e.g., FAERS-asserted causation contradicted by EudraVigilance dechallenge-negative case). Symmetric across the contradicting pair.

## SUPPORTS
**DechallengeRechallenge/TemporalRelationship/ReportType → CausalitySignal**

Evidence that supports a CausalitySignal — a DechallengeRechallenge result, a TemporalRelationship (plausible time-to-onset), or a ReportType (the report or database the signal rests on). Use this, not TRIGGERED, for evidence flowing into a signal.

## ASSESSES
**CausalitySignal → Drug/Concomitant/AdverseEvent**

A CausalitySignal assesses a Drug (or Concomitant) and an AdverseEvent — link the signal to both members of the Drug-AdverseEvent pair it is about. Needed for CONTRADICTS between signals on the same pair.

## INTERACTS_WITH
**Drug → Drug/Concomitant** (symmetric)

A documented or suspected drug-drug interaction between two products (e.g. a "Drug interaction" PT, or the report attributing the event to the combination). Stronger than CO_ADMINISTERED_WITH, which records only co-exposure. Symmetric.

## PROGRESSED_TO
**AdverseEvent → AdverseEvent**

An AdverseEvent progressed to or caused a secondary AdverseEvent (e.g. rhabdomyolysis progressed to acute kidney injury).

## CHALLENGES
**DechallengeRechallenge → Drug/Concomitant**

A DechallengeRechallenge withdrew and/or reintroduced this Drug (or Concomitant). Links the challenge record to the product it tested.

## HAS_ONSET
**AdverseEvent → TemporalRelationship**

An AdverseEvent has a stated time-to-onset (TemporalRelationship) after exposure. Carries the temporality criterion as a graph edge.

## APPLIES_TO
**RegulatoryAction → Drug**

A RegulatoryAction (label change, boxed warning, REMS, withdrawal, recall) applies to a Drug.

## HAS_CONDITION
**Patient → Indication**

A Patient has a condition — medical history or the underlying disease the suspect drug treats. Material to confounding-by-indication analysis.

## WORSENING_OF
**AdverseEvent → Indication**

A reported AdverseEvent is a worsening, progression, or recurrence of an Indication (e.g. "Plasma cell myeloma" reported as an event in a patient treated for plasma cell myeloma). Flags possible confounding by indication.
