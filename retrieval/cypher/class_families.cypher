// class_families: expand class families (D29) to every DrugClass in them, and
// return the named classes too, so callers get one list of class IDs.
MATCH (c:DrugClass)
WHERE c.family IN $families OR c.id IN $class_ids
RETURN c.id AS class_id, c.name AS class_name, c.family AS family
ORDER BY class_id
