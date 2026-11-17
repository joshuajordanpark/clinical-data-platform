import pandas as pd
from sqlalchemy import create_engine, text, inspect
from src.load_to_sqlite import (
    load_tables,
    validate_encounter_patient_references,
    create_tables,
    validate_loaded_row_count,
    run_transactional_load,
    clear_tables,
    run_full_refresh,
    initialize_tables,
)
import src.load_to_sqlite as pipeline
import pytest
import shutil
from pathlib import Path

patients = pd.DataFrame({
    "Id": [1, 2],
    "FIRST": ["John", "Jane"]
})

encounters = pd.DataFrame({
    "Id": [101, 102],
    "PATIENT": [1, 2]
})

def test_load_tables_rolls_back_on_failure():
    engine = create_engine("sqlite:///:memory:")

    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE patients (
                Id INTEGER PRIMARY KEY,
                FIRST TEXT
            )
        """))

        connection.execute(text("""
            CREATE TABLE encounters(
                Id INTEGER PRIMARY KEY,
                PATIENT INTEGER
            )
        """))

    with pytest.raises(RuntimeError, match="Simulated failure after loading tables"):
        with engine.begin() as connection:
            load_tables(connection, patients, encounters)
            raise RuntimeError("Simulated failure after loading tables")

    with engine.connect() as connection:
        result = connection.execute(text("SELECT COUNT(*) FROM patients"))
        encounter_result = connection.execute(text("SELECT COUNT(*) FROM encounters"))
        patient_count = result.scalar_one()
        encounter_count = encounter_result.scalar_one()
        assert patient_count == 0, "Patients table should be empty after rollback"
        assert encounter_count == 0, "Encounters table should be empty after rollback"

def test_load_tables_commits_on_success():
    engine = create_engine("sqlite:///:memory:")

    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE patients (
                Id INTEGER PRIMARY KEY,
                FIRST TEXT
            )
        """))

        connection.execute(text("""
            CREATE TABLE encounters (
                Id INTEGER PRIMARY KEY,
                PATIENT INTEGER
            )
        """))

    with engine.begin() as connection:
        load_tables(connection, patients, encounters)

    with engine.connect() as connection:
        result = connection.execute(text("SELECT COUNT(*) FROM patients"))
        patient_count = result.scalar_one()
        assert patient_count == 2, "Patients table should have 2 records after successful load"

        encounter_result = connection.execute(text("SELECT COUNT(*) FROM encounters"))
        encounter_count = encounter_result.scalar_one()
        assert encounter_count == 2, "Encounters table should have 2 records after successful load"

def test_load_tables_rolls_back_on_validation_failure():
    engine = create_engine("sqlite:///:memory:")

    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE patients (
                Id INTEGER PRIMARY KEY,
                FIRST TEXT
            )
        """))

        connection.execute(text("""
            CREATE TABLE encounters (
                Id INTEGER PRIMARY KEY,
                PATIENT INTEGER
            )
        """))

   
    invalid_encounters = pd.DataFrame({
        "Id": [101, 102],
        "PATIENT": [1, 999]
        })

    with pytest.raises(RuntimeError, match="Critical data validation failed"):
        with engine.begin() as connection:
            load_tables(connection, patients, invalid_encounters)
            validation_result = validate_encounter_patient_references(connection, 'CRITICAL')
            if validation_result['status'] == 'FAIL' and validation_result['severity'] == 'CRITICAL':
                raise RuntimeError("Critical data validation failed")

    with engine.connect() as connection:
        result = connection.execute(text("SELECT COUNT(*) FROM patients"))
        encounter_result = connection.execute(text("SELECT COUNT(*) FROM encounters"))
        patient_count = result.scalar_one()
        encounter_count = encounter_result.scalar_one()
        assert patient_count == 0, "Patients table should be empty after rollback due to validation failure"
        assert encounter_count == 0, "Encounters table should be empty after rollback due to validation failure"

def test_create_tables_is_safe_to_repeat():
    engine = create_engine("sqlite:///:memory:")

    with engine.begin() as connection:
        create_tables(connection)
        create_tables(connection)

    with engine.connect() as connection:
        result = connection.execute(text("""
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            """))
        table_names = result.scalars().all()
        assert "patients" in table_names
        assert "encounters" in table_names

def test_transactional_load_rolls_back_on_validation_failure():
    engine = create_engine("sqlite:///:memory:")

    invalid_encounters = pd.DataFrame({
        "Id": [101, 102],
        "PATIENT": [1, 999]
    })

    with engine.begin() as connection:
        create_tables(connection)

    with pytest.raises(RuntimeError, match="Critical data validation failed"):
        with engine.begin() as connection:
            run_transactional_load(connection, patients, invalid_encounters)

    with engine.connect() as connection:
        result = connection.execute(text("SELECT COUNT(*) FROM patients"))
        encounter_result = connection.execute(text("SELECT COUNT(*) FROM encounters"))
        patient_count = result.scalar_one()
        encounter_count = encounter_result.scalar_one()
        assert patient_count == 0, "Patients table should be empty after rollback due to validation failure"
        assert encounter_count == 0, "Encounters table should be empty after rollback due to validation failure"

def test_transactional_load_commits_on_success():

    engine = create_engine("sqlite:///:memory:")

    with engine.begin() as connection:
        create_tables(connection)

    with engine.begin() as connection:
        validation_results = run_transactional_load(connection, patients, encounters)
    
    with engine.connect() as connection:
        result = connection.execute(text("SELECT COUNT(*) FROM patients"))
        patient_count = result.scalar_one()
        assert patient_count == 2, "Patients table should have 2 records after successful load"

        encounter_result = connection.execute(text("SELECT COUNT(*) FROM encounters"))
        encounter_count = encounter_result.scalar_one()
        assert encounter_count == 2, "Encounters table should have 2 records after successful load"

    assert all( #all() returns True only when every condition is true
        result["status"] == "PASS"
        for result in validation_results
    )

def test_full_refresh_rollback_preserves_existing_data():
    engine = create_engine("sqlite:///:memory:")

    with engine.begin() as connection:
        create_tables(connection)
        load_tables(connection, patients, encounters)

    with pytest.raises(RuntimeError):
        with engine.begin() as connection:
            clear_tables(connection)

            load_tables(connection, patients, encounters)

            raise RuntimeError("Simulated refresh failure")

    with engine.connect() as connection:
        result = connection.execute(text("SELECT COUNT(*) FROM patients"))
        encounter_result = connection.execute(text("SELECT COUNT(*) FROM encounters"))
        patient_count = result.scalar_one()
        encounter_count = encounter_result.scalar_one()
        assert patient_count == 2, "Patients table should still have 2 records after rollback"
        assert encounter_count == 2, "Encounters table should still have 2 records after rollback"

        name = connection.execute(text("SELECT FIRST FROM patients WHERE Id = 1")).scalar_one()
        assert name == "John", "Patient data should remain unchanged after rollback"

def test_full_refresh_validation_failure_preserves_existing_data():
    engine = create_engine("sqlite:///:memory:")

    invalid_encounters = pd.DataFrame({
        "Id": [201, 202],
        "PATIENT": [1, 999]
    })

    with engine.begin() as connection:
        create_tables(connection)
        load_tables(connection, patients, encounters)

    with pytest.raises(RuntimeError, match="Critical data validation failed"):
        with engine.begin() as connection:
            run_full_refresh(connection, patients, invalid_encounters)

    with engine.connect() as connection:
        result = connection.execute(text("SELECT COUNT(*) FROM patients"))
        encounter_result = connection.execute(text("SELECT COUNT(*) FROM encounters"))
        patient_count = result.scalar_one()
        encounter_count = encounter_result.scalar_one()
        assert patient_count == 2, "Patients table should still have 2 records after rollback"
        assert encounter_count == 2, "Encounters table should still have 2 records after rollback"

        name = connection.execute(text("SELECT FIRST FROM patients WHERE Id = 1")).scalar_one()
        assert name == "John", "Patient data should remain unchanged after rollback"

        encounter_101 = connection.execute(text("SELECT Id FROM encounters where Id = 101")).scalar_one()
        assert encounter_101 == 101, "Encounter data should remain unchanged after rollback"
        encounter_201 = connection.execute(text("SELECT COUNT(*) FROM encounters where Id = 201")).scalar_one()
        assert encounter_201 == 0, "Encounter 201 should not exist after rollback"

def test_full_refresh_replaces_existing_data_on_success():
    engine = create_engine("sqlite:///:memory:")

    with engine.begin() as connection:
        create_tables(connection)
        load_tables(connection, patients, encounters)

    new_patients = pd.DataFrame({
        "Id": [3, 4],
        "FIRST": ["Alice", "Bob"]
    })

    new_encounters = pd.DataFrame({
        "Id": [201, 202],
        "PATIENT": [3, 4]
    })

    with engine.begin() as connection:
        validation_results = run_full_refresh(connection, new_patients, new_encounters)

    with engine.connect() as connection:
        patient_count = connection.execute(text("SELECT COUNT(*) FROM patients")).scalar_one()
        encounter_count = connection.execute(text("SELECT COUNT(*) FROM encounters")).scalar_one()
        assert patient_count == 2, "Patients table should have 2 records after full refresh"
        assert encounter_count == 2, "Encounters table should have 2 records after full refresh"

        patient_names = connection.execute(text("SELECT FIRST FROM patients")).scalars().all()
        assert "Alice" in patient_names and "Bob" in patient_names, "Patients table should contain new patient names after full refresh"
        assert "John" not in patient_names and "Jane" not in patient_names, "Patients table should not contain old patient names after full refresh"

        encounter_Ids = connection.execute(text("SELECT Id FROM encounters")).scalars().all()
        assert 201 in encounter_Ids and 202 in encounter_Ids, "Encounters table should contain new encounter IDs after full refresh"
        assert 101 not in encounter_Ids and 102 not in encounter_Ids, "Encounters table should not contain old encounter IDs after full refresh"

        assert all(
            result["status"] == "PASS"
            for result in validation_results
        )

def test_initialize_tables_creates_missing_tables():
    engine = create_engine("sqlite:///:memory:")

    patients = pd.DataFrame({
        "Id": [1, 2],
        "FIRST": ["John", "Jane"]
    })

    encounters = pd.DataFrame({
        "Id": [101, 102],
        "PATIENT": [1, 2]
    })

    with engine.begin() as connection:
        initialize_tables(connection, patients, encounters)

    with engine.connect() as connection:
        inspector = inspect(connection)
        assert inspector.has_table("patients"), "Patients table should be created"
        assert inspector.has_table("encounters"), "Encounters table should be created"
        assert connection.execute(text("SELECT COUNT(*) FROM patients")).scalar_one() == 0, "Patients table should be empty after initialization"
        assert connection.execute(text("SELECT COUNT(*) FROM encounters")).scalar_one() == 0, "Encounters table should be empty after initialization"

def test_initialize_tables_preserves_existing_data():
    engine = create_engine("sqlite:///:memory:")

    patients = pd.DataFrame({
        "Id": [1, 2],
        "FIRST": ["John", "Jane"]
    })

    encounters = pd.DataFrame({
        "Id": [101, 102],
        "PATIENT": [1, 2]
    })

    with engine.begin() as connection:
        initialize_tables(connection, patients, encounters)
        load_tables(connection, patients, encounters)

    with engine.begin() as connection:
        initialize_tables(connection, patients, encounters)

    with engine.connect() as connection:
        patient_count = connection.execute(text("SELECT COUNT(*) FROM patients")).scalar_one()
        encounter_count = connection.execute(text("SELECT COUNT(*) FROM encounters")).scalar_one()
        assert patient_count == 2, "Patients table should still have 2 records after initialization"
        assert encounter_count == 2, "Encounters table should still have 2 records after initialization"
        assert connection.execute(text("SELECT FIRST FROM patients WHERE Id = 1")).scalar_one() == "John", "Patient data should remain unchanged after initialization"

def test_full_refresh_initializes_missing_tables():
    engine = create_engine("sqlite:///:memory:")

    patients = pd.DataFrame({
        "Id": [1, 2],
        "FIRST": ["John", "Jane"]
    })

    encounters = pd.DataFrame({
        "Id": [101, 102],
        "PATIENT": [1, 2]
    })

    with engine.begin() as connection:
        run_full_refresh(connection, patients, encounters)

    with engine.connect() as connection:
        inspector = inspect(connection)
        assert inspector.has_table("patients"), "Patients table should be created during full refresh"
        assert inspector.has_table("encounters"), "Encounters table should be created during full refresh"
        assert connection.execute(text("SELECT COUNT(*) FROM patients")).scalar_one() == 2, "Patients table should have 2 records after full refresh"
        assert connection.execute(text("SELECT COUNT(*) FROM encounters")).scalar_one() == 2, "Encounters table should have 2 records after full refresh"

def test_full_refresh_initialization_rolls_back_invalid_data():
    engine = create_engine("sqlite:///:memory:")

    patients = pd.DataFrame({
        "Id": [1, 2],
        "FIRST": ["John", "Jane"]
    })        

    encounters = pd.DataFrame({
        "Id": [101, 102],
        "PATIENT": [1, 999]
    })

    with pytest.raises(RuntimeError, match="Critical data validation failed"):
        with engine.begin() as connection:
            run_full_refresh(connection, patients, encounters)

    with engine.connect() as connection:
        inspector = inspect(connection)

        if inspector.has_table("patients"):
            patient_count = connection.execute(
                text("SELECT COUNT(*) FROM patients")
            ).scalar_one()

            assert patient_count == 0

        if inspector.has_table("encounters"):
            encounter_count = connection.execute(
                text("SELECT COUNT(*) FROM encounters")
            ).scalar_one()

            assert encounter_count == 0

def test_transactional_load_reports_critical_failure(capsys):
    engine = create_engine("sqlite:///:memory:")

    patients = pd.DataFrame({
    "Id": [1, 2],
    "FIRST": ["John", "Jane"]
    })

    encounters = pd.DataFrame({
        "Id": [101, 102],
        "PATIENT": [1, 999]
    })

    with engine.begin() as connection:
        initialize_tables(connection, patients, encounters)

    with pytest.raises(RuntimeError, match="Critical data validation failed"):
        with engine.begin() as connection:
            run_transactional_load(connection, patients, encounters)

    captured = capsys.readouterr() # move this and the following assertions outside as these won't be run due to exception from run_transactional_load

    assert "PIPELINE FAILED" in captured.out
    assert "Encounter patient referential integrity" in captured.out
    assert "1 failure(s)" in captured.out

    with engine.connect() as connection:

        assert connection.execute(text("SELECT COUNT(*) FROM patients")).scalar_one() == 0
        assert connection.execute(text("SELECT COUNT(*) FROM encounters")).scalar_one() == 0

def test_pipeline_with_realistic_data(tmp_path, monkeypatch):
    source_root = Path(__file__).resolve().parent.parent

    processed_dir = tmp_path / "data" / "processed"
    processed_dir.mkdir(parents=True)

    warehouse_dir = tmp_path / "data" / "warehouse"
    warehouse_dir.mkdir(parents=True)

    source_patients = source_root / "data" / "processed" / "patients_clean.csv"
    source_encounters = source_root / "data" / "processed" / "encounters_enriched.csv"

    database_path = tmp_path / "data" / "warehouse" / "clinical.db"

    shutil.copy2(
        source_patients,
        processed_dir / "patients_clean.csv"
    )

    shutil.copy2(
        source_encounters,
        processed_dir / "encounters_enriched.csv"
    )

    monkeypatch.setattr(pipeline, "PROJECT_ROOT", tmp_path)

    pipeline.main()

    engine = create_engine(f"sqlite:///{database_path}")

    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM patients")).scalar_one() == 108
        assert connection.execute(text("SELECT COUNT(*) FROM encounters")).scalar_one() == 5571

    pipeline.main()

    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM patients")).scalar_one() == 108
        assert connection.execute(text("SELECT COUNT(*) FROM encounters")).scalar_one() == 5571
    