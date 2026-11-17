// AMR-Navigator graph constraints and indexes (task T01).
// One statement per line, each ending in ';'. Safe to run repeatedly.
// Apply with pipeline.graph_db.apply_constraints(driver).
// Required properties are checked in Python (pipeline/validate.py), because
// property-existence constraints are not available in Neo4j Community Edition.

CREATE CONSTRAINT pathogen_id_unique IF NOT EXISTS FOR (n:Pathogen) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT mechanism_id_unique IF NOT EXISTS FOR (n:Mechanism) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT gene_id_unique IF NOT EXISTS FOR (n:Gene) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT drug_id_unique IF NOT EXISTS FOR (n:Drug) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT drugclass_id_unique IF NOT EXISTS FOR (n:DrugClass) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT recommendation_id_unique IF NOT EXISTS FOR (n:Recommendation) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT guideline_id_unique IF NOT EXISTS FOR (n:Guideline) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT surveillancestat_id_unique IF NOT EXISTS FOR (n:SurveillanceStat) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT passage_id_unique IF NOT EXISTS FOR (n:Passage) REQUIRE n.id IS UNIQUE;

CREATE INDEX drug_name IF NOT EXISTS FOR (n:Drug) ON (n.name);
CREATE INDEX pathogen_name IF NOT EXISTS FOR (n:Pathogen) ON (n.name);
CREATE INDEX mechanism_name IF NOT EXISTS FOR (n:Mechanism) ON (n.name);
CREATE INDEX drugclass_name IF NOT EXISTS FOR (n:DrugClass) ON (n.name);
