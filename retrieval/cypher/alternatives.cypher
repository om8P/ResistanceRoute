// alternatives: for one pathogen and one set of mechanisms (a group), every drug
// with the reasons it is excluded, each reason carrying its edge's provenance.
// Exclusion rule (T03, D4): classes the pathogen is intrinsically resistant to,
// plus classes ANY mechanism in $mechanism_ids confers resistance to, plus drugs
// ANY of them inactivates (union over mechanisms), plus the classes the question
// reports as resistant ($resistant_class_ids, a phenotype, no edge).
MATCH (p:Pathogen {id: $pathogen_id})
OPTIONAL MATCH (m:Mechanism) WHERE m.id IN $mechanism_ids
WITH p, collect(m) AS mechs
MATCH (d:Drug)-[ic:IN_CLASS]->(c:DrugClass)
WITH p, mechs, d, ic, c,
     [(p)-[r:INTRINSICALLY_RESISTANT_TO]->(c) | properties(r)] AS intrinsic,
     reduce(acc = [], m IN mechs |
        acc + [(m)-[r:CONFERS_RESISTANCE_TO]->(c) |
               {mechanism_id: m.id, mechanism_name: m.name, props: properties(r)}]) AS conferred,
     reduce(acc = [], m IN mechs |
        acc + [(m)-[r:INACTIVATES]->(d) |
               {mechanism_id: m.id, mechanism_name: m.name, props: properties(r)}]) AS inactivated
RETURN d.id AS drug_id, d.name AS drug_name, d.aware_group AS aware_group,
       c.id AS class_id, c.name AS class_name, c.family AS family,
       properties(ic) AS in_class,
       intrinsic, conferred, inactivated,
       c.id IN $resistant_class_ids AS reported_resistant
ORDER BY drug_name
