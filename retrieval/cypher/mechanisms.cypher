// mechanisms: the pathogen's mechanisms plus any mechanism the question names,
// with the HAS_MECHANISM edge (null when the pathogen has no such edge) and the
// classes among $class_ids that each mechanism confers resistance to.
// Used by alternatives and recommendation_lookup to form the mechanism groups.
MATCH (p:Pathogen {id: $pathogen_id})
MATCH (m:Mechanism)
WHERE m.id IN $mechanism_ids OR (p)-[:HAS_MECHANISM]->(m)
OPTIONAL MATCH (p)-[h:HAS_MECHANISM]->(m)
RETURN p.id AS pathogen_id, p.name AS pathogen_name,
       m.id AS mechanism_id, m.name AS mechanism_name, m.type AS mechanism_type,
       m.ambler_class AS ambler_class, properties(h) AS has_mechanism,
       [(m)-[r:CONFERS_RESISTANCE_TO]->(c:DrugClass) WHERE c.id IN $class_ids |
          {class_id: c.id, class_name: c.name, props: properties(r)}] AS confers_reported
ORDER BY mechanism_name
