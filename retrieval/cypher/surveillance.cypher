// surveillance: GLASS statistics for one pathogen about the target drugs or
// classes, optionally for one country and one year (null = any).
MATCH (p:Pathogen {id: $pathogen_id})<-[ap:ABOUT_PATHOGEN]-(s:SurveillanceStat)
WHERE ($country IS NULL OR s.country = $country)
  AND ($year IS NULL OR s.year = $year)
MATCH (s)-[at:ABOUT_DRUG|ABOUT_CLASS]->(t)
WHERE t.id IN $target_ids
RETURN s.id AS stat_id, s.country AS country, s.year AS year,
       s.pct_resistant AS pct_resistant, s.n_tested AS n_tested,
       properties(ap) AS about_pathogen,
       type(at) AS about_type, properties(at) AS about_props,
       t.id AS target_id, t.name AS target_name, labels(t)[0] AS target_label
ORDER BY target_id, country, year DESC
