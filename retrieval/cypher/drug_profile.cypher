// drug_profile: class, family and AWaRe group of the named drugs, or of every
// drug in the named classes, with the recommendations that name each drug.
MATCH (d:Drug)-[ic:IN_CLASS]->(c:DrugClass)
WHERE d.id IN $drug_ids OR c.id IN $class_ids
RETURN d.id AS drug_id, d.name AS drug_name, d.aware_group AS aware_group,
       c.id AS class_id, c.name AS class_name, c.family AS family,
       properties(ic) AS in_class,
       [(r:Recommendation)-[rd:RECOMMENDS]->(d) |
          {id: r.id, line_of_therapy: r.line_of_therapy, props: properties(rd)}] AS recommendations
ORDER BY class_id, drug_name
