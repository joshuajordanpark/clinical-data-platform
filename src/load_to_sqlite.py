from pathlib import Path 
import sqlite3 
import pandas as pd 
from sqlalchemy import create_engine, text, inspect

PROJECT_ROOT = Path(__file__).parent.parent 

# refactoring file to separate validation functions and executable main function
def validate_loaded_row_count(
        df,
        table_name,
        connection,
        severity
):
    df_rows = len(df)

    result = connection.execute(
        text(f"SELECT COUNT(*) FROM {table_name}")
    )

    sql_rows = result.scalar_one()

    if df_rows == sql_rows:
        status = "PASS"
    else:
        status = "FAIL"
    
    return {
        "check": f"Match {table_name} sql rows to df rows",
        "status": status,
        "severity": severity,
        "count": abs(df_rows - sql_rows)
    }

def validate_encounter_patient_references(
        connection,
        severity
):

    result = connection.execute(
        text("""
        SELECT
            e.Id as encounter_Id,
            e.PATIENT,
            p.Id as patient_Id
        FROM encounters e 
        LEFT JOIN patients p ON e.PATIENT = p.Id
        WHERE p.Id IS NULL AND e.PATIENT IS NOT NULL
        """)
    )

    invalid_results = result.fetchall()

    if invalid_results:
        status = "FAIL"
    else:
        status = "PASS"

    return (
        {
            "check": "Encounter patient referential integrity",
            "status": status,
            "severity": severity,
            "count": len(invalid_results)
        }
    )

def load_tables(connection, patients, encounters):

    patients.to_sql(
        "patients",
        connection,
        if_exists="append",
        index=False
    )

    encounters.to_sql(
        "encounters",
        connection,
        if_exists="append",
        index=False
    )

def create_tables(connection):
    connection.execute(text("""
        CREATE TABLE IF NOT EXISTS patients (
            Id INTEGER PRIMARY KEY,
            FIRST TEXT
        )
    """))

    connection.execute(text("""
        CREATE TABLE IF NOT EXISTS encounters (
            Id INTEGER PRIMARY KEY,
            PATIENT INTEGER
        )
    """))

def run_transactional_load(connection, patients, encounters):
    load_tables(connection, patients, encounters)

    validation_results = [
        validate_loaded_row_count(patients, "patients", connection, 'CRITICAL'),
        validate_loaded_row_count(encounters, "encounters", connection, 'CRITICAL'),
        validate_encounter_patient_references(connection, 'CRITICAL')
    ]

    critical_failures = []

    for result in validation_results:
        if result['status'] == 'FAIL' and result['severity'] == 'CRITICAL':
            critical_failures.append(result)

    if critical_failures:
        print('\nPIPELINE FAILED\nCritical validation failures:')

        for failure in critical_failures:
            print(f"-{failure['check']}: {failure['count']} failure(s)")

        raise RuntimeError("Critical data validation failed")

    return validation_results

def clear_tables(connection):
    connection.execute(text("DELETE FROM encounters"))
    connection.execute(text("DELETE FROM patients"))

def run_full_refresh(connection, patients, encounters): 
    initialize_tables(connection, patients, encounters)
    clear_tables(connection)
    return run_transactional_load(connection, patients, encounters)

def initialize_tables(connection, patients, encounters):
    inspector = inspect(connection)

    if not inspector.has_table("patients"):
        patients.head(0).to_sql(
            "patients",
            connection,
            if_exists="fail",
            index=False
        )

    if not inspector.has_table("encounters"):
        encounters.head(0).to_sql(
            "encounters",
            connection,
            if_exists="fail",
            index=False
        )

# Main execution block
def main():

    patients_path = (
        PROJECT_ROOT / "data" / "processed" / "patients_clean.csv"
    )

    encounters_path = (
        PROJECT_ROOT / "data" / "processed" / "encounters_enriched.csv"
    )

    database_path = (
        PROJECT_ROOT / "data" / "warehouse" / "clinical.db"
    )

    database_path.parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(f"sqlite:///{database_path}")

    patients = pd.read_csv(patients_path)
    encounters = pd.read_csv(encounters_path)

    try:
        with engine.begin() as connection:

            load_validation_results = run_full_refresh(
                connection,
                patients,
                encounters)

            for result in load_validation_results:
                print(result)

    except Exception as e:
        print(f"An error occurred: {e}")
        raise

    with engine.connect() as connection:

        patient_count = connection.execute(text("SELECT COUNT(*) FROM patients")).scalar_one()

        print(f"DataFrame patient rows: {len(patients)}")
        print(f"SQL patient rows: {patient_count}")

        encounters_count = connection.execute(text("SELECT COUNT(*) FROM encounters")).scalar_one()

        print(f"DataFrame encounter rows: {len(encounters)}")
        print(f"SQL encounter rows: {encounters_count}")

        query = """
            WITH patient_encounter_counts AS (
            SELECT
                PATIENT,
                COUNT(*) AS encounter_count
            FROM encounters
            GROUP BY PATIENT
            )

            SELECT
                p.FIRST,
                p.LAST,
                p.GENDER,
                pec.encounter_count
            FROM patient_encounter_counts pec
            INNER JOIN patients p ON pec.PATIENT = p.Id
            ORDER BY pec.encounter_count DESC
            LIMIT 10
        """

        result = pd.read_sql_query(query, connection)

        print("\nTop 10 patients by encounter count:")
        print(result)

        encounter_class_query = """
        SELECT
            e.ENCOUNTERCLASS,
            COUNT(*) AS encounter_class_count
        FROM encounters e
        GROUP BY e.ENCOUNTERCLASS
        ORDER BY encounter_class_count DESC
        """
        
        encounter_class_query_result = pd.read_sql_query(encounter_class_query, connection)

        print("\nEncounters in each encounter class:")
        print(encounter_class_query_result)

        encounter_class_cost_query = """
        SELECT
            e.ENCOUNTERCLASS,
            SUM(TOTAL_CLAIM_COST) AS total_cost,
            AVG(TOTAL_CLAIM_COST) AS avg_cost
        FROM encounters e
        GROUP BY e.ENCOUNTERCLASS
        ORDER BY avg_cost DESC
        """
        
        encounter_class_cost_query_result = pd.read_sql_query(encounter_class_cost_query, connection)

        print("\nTotal claim cost and average claim cost by encounter class:")
        print(encounter_class_cost_query_result)

        encounter_class_cost_case_query = """
        WITH encounter_cost_categories AS (
            SELECT
                e.Id,
                e.ENCOUNTERCLASS,
                e.TOTAL_CLAIM_COST,
                CASE
                    WHEN e.TOTAL_CLAIM_COST < 1000 THEN 'LOW'
                    WHEN e.TOTAL_CLAIM_COST BETWEEN 1000 AND 5000 THEN 'MEDIUM'
                    ELSE 'HIGH'
            END AS cost_category
        FROM encounters e
        )

        SELECT c.cost_category,
            COUNT(*) AS encounter_count
            FROM encounter_cost_categories c
            GROUP BY c.cost_category
            ORDER BY encounter_count DESC
        """
        
        encounter_class_cost_case_query_result = pd.read_sql_query(encounter_class_cost_case_query, connection)

        print("\nEncounter count by cost category:")
        print(encounter_class_cost_case_query_result)

        encounters_ranked = """
        SELECT 
            e.PATIENT,
            e.Id as encounter_Id,
            e.TOTAL_CLAIM_COST,
            ROW_NUMBER() OVER (
                PARTITION BY e.PATIENT
                ORDER BY e.TOTAL_CLAIM_COST DESC
            ) AS encounter_rank
        FROM encounters e
        """
        
        encounters_ranked_result = pd.read_sql_query(encounters_ranked, connection)

        print("\nEncounters ranked by claim cost:")
        print(encounters_ranked_result)

        highest_encounter_per_patient = """
        WITH ranked_encounters AS (
            SELECT 
                e.PATIENT,
                e.Id as encounter_Id,
                e.TOTAL_CLAIM_COST,
                ROW_NUMBER() OVER (
                    PARTITION BY e.PATIENT
                    ORDER BY 
                        e.TOTAL_CLAIM_COST DESC, 
                        e.Id ASC
                ) AS encounter_rank
            FROM encounters e
        )

        SELECT
            PATIENT,
            encounter_Id,
            TOTAL_CLAIM_COST,
            encounter_rank
        FROM ranked_encounters
        WHERE encounter_rank = 1
        ORDER BY TOTAL_CLAIM_COST DESC
        """
        
        highest_encounter_per_patient_result = pd.read_sql_query(highest_encounter_per_patient, connection)

        print("\nHighest encounter per patient:")
        print(highest_encounter_per_patient_result)


if __name__ == "__main__":
    main()