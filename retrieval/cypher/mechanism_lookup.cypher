// mechanism_lookup: how a pathogen resists a set of classes (or drugs). Returns
// the pathogen's mechanisms with the classes they confer resistance to and the
// drugs they inactivate, restricted to $class_ids / $drug_ids when given, and
// the pathogen's intrinsic resistance to those classes.
MATCH (p:Pathogen {id: $pathogen_id})
RETURN p.id AS pathogen_id, p.name AS pathogen_name,
       [(p)-[h:HAS_MECHANISM]->(m:Mechanism) |
          {id: m.id, name: m.name, type: m.type, ambler_class: m.ambler_class,
           props: properties(h),
           genes: size([(g:Gene)-[:ENCODES]->(m) | g.id]),
           classes: [(m)-[r:CONFERS_RESISTANCE_TO]->(c:DrugClass)
                       WHERE size($class_ids) = 0 OR c.id IN $class_ids |
                     {id: c.id, name: c.name, props: properties(r)}],
           drugs: [(m)-[r:INACTIVATES]->(d:Drug)-[:IN_CLASS]->(c:DrugClass)
                     WHERE (size($class_ids) = 0 AND size($drug_ids) = 0)
                        OR c.id IN $class_ids OR d.id IN $drug_ids |
                   {id: d.id, name: d.name, class_id: c.id, props: properties(r)}]}] AS mechanisms,
       [(p)-[r:INTRINSICALLY_RESISTANT_TO]->(c:DrugClass)
          WHERE size($class_ids) = 0 OR c.id IN $class_ids |
        {id: c.id, name: c.name, props: properties(r)}] AS intrinsic
