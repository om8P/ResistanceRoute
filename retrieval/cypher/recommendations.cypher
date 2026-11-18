// recommendations: every recommendation for the pathogen, with its guideline,
// mechanisms (empty when the guideline names none), drugs and supporting
// passages, each with its edge's provenance. Filtering by mechanism (D34) and
// regimen type (D33) is applied in graph_search.py.
MATCH (p:Pathogen {id: $pathogen_id})<-[fp:FOR_PATHOGEN]-(r:Recommendation)-[fr:FROM]->(g:Guideline)
RETURN r.id AS rec_id, r.text AS text, r.regimen_type AS regimen_type,
       r.line_of_therapy AS line_of_therapy, r.infection_site AS infection_site,
       r.patient_group AS patient_group,
       properties(fp) AS for_pathogen,
       g.id AS guideline_id, g.title AS guideline_title, g.year AS guideline_year,
       properties(fr) AS from_props,
       [(r)-[fm:FOR_MECHANISM]->(m:Mechanism) |
          {id: m.id, name: m.name, props: properties(fm)}] AS mechanisms,
       [(r)-[rd:RECOMMENDS]->(d:Drug)-[:IN_CLASS]->(c:DrugClass) |
          {id: d.id, name: d.name, aware_group: d.aware_group, class_id: c.id,
           props: properties(rd)}] AS drugs,
       [(s:Passage)-[sp:SUPPORTS]->(r) |
          {id: s.id, section: s.section, props: properties(sp)}] AS passages
ORDER BY rec_id
