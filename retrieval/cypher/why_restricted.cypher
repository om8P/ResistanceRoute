// why_restricted: for one drug, its AWaRe group and class, the mechanisms that
// defeat it (class-level CONFERS_RESISTANCE_TO or drug-level INACTIVATES) with
// the pathogens that carry them, the pathogens intrinsically resistant to its
// class, the recommendations that name it, and passages that mention it.
MATCH (d:Drug {id: $drug_id})-[ic:IN_CLASS]->(c:DrugClass)
RETURN d.id AS drug_id, d.name AS drug_name, d.aware_group AS aware_group,
       c.id AS class_id, c.name AS class_name, c.family AS family,
       properties(ic) AS in_class,
       [(m:Mechanism)-[r:CONFERS_RESISTANCE_TO]->(c) |
          {id: m.id, name: m.name, via: 'CONFERS_RESISTANCE_TO', props: properties(r),
           pathogens: [(p:Pathogen)-[h:HAS_MECHANISM]->(m) |
                       {id: p.id, name: p.name, props: properties(h)}]}] AS by_class,
       [(m:Mechanism)-[r:INACTIVATES]->(d) |
          {id: m.id, name: m.name, via: 'INACTIVATES', props: properties(r),
           pathogens: [(p:Pathogen)-[h:HAS_MECHANISM]->(m) |
                       {id: p.id, name: p.name, props: properties(h)}]}] AS by_drug,
       [(p:Pathogen)-[r:INTRINSICALLY_RESISTANT_TO]->(c) |
          {id: p.id, name: p.name, props: properties(r)}] AS intrinsic,
       [(rec:Recommendation)-[rd:RECOMMENDS]->(d) |
          {id: rec.id, text: rec.text, line_of_therapy: rec.line_of_therapy,
           regimen_type: rec.regimen_type, props: properties(rd),
           guideline: head([(rec)-[f:FROM]->(g:Guideline) |
                            {id: g.id, title: g.title, year: g.year, props: properties(f)}]),
           pathogen: head([(rec)-[fp:FOR_PATHOGEN]->(p:Pathogen) |
                           {id: p.id, name: p.name, props: properties(fp)}]),
           passages: [(s:Passage)-[sp:SUPPORTS]->(rec) |
                      {id: s.id, section: s.section, props: properties(sp)}]}] AS recommendations,
       [(s:Passage)-[mn:MENTIONS]->(d)
          WHERE any(w IN $restrict_words WHERE toLower(s.text) CONTAINS w) |
          {id: s.id, source_doc: s.source_doc, section: s.section, text: s.text,
           props: properties(mn)}] AS passages
