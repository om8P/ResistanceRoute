// entities: names and labels of the question's entities, for path start nodes
// and for drug-to-class lookups.
MATCH (n)
WHERE n.id IN $ids AND (n:Pathogen OR n:Mechanism OR n:Drug OR n:DrugClass)
RETURN n.id AS id, labels(n)[0] AS label, n.name AS name,
       head([(n)-[:IN_CLASS]->(c:DrugClass) | c.id]) AS class_id
