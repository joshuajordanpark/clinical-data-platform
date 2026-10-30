import sqlite3
import pandas as pd
import pytest

from src.load_to_sqlite import load_tables, validate_encounter_patient_references

@pytest.fixture
def db_connection():
    conn = sqlite3.connect(':memory:')
    yield conn
    conn.close()

def test_load_tables(db_connection):

    # Create a sample DataFrame
    patients = pd.DataFrame({
        'Id': ['P001', 'P002'],
        'FIRST': ['Alice', 'Bob']
    })

    encounters = pd.DataFrame({
        'Id': ['E001', 'E002', 'E003'],
        'PATIENT': ['P001', 'P001', 'P002']
    })

    # Load the tables into the SQLite database
    load_tables(db_connection, patients, encounters)

    # Verify the tables were loaded correctly
    cursor = db_connection.cursor()

    cursor.execute("SELECT COUNT(*) FROM patients")
    patients_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM encounters")
    encounters_count = cursor.fetchone()[0]

    assert patients_count == len(patients)
    assert encounters_count == len(encounters)

    cursor.execute("SELECT Id, FIRST FROM patients ORDER BY Id")
    patients_data = cursor.fetchall()
    assert patients_data == [('P001', 'Alice'), ('P002', 'Bob')]

    cursor.execute("SELECT Id, PATIENT FROM encounters ORDER BY Id")
    encounters_data = cursor.fetchall()
    assert encounters_data == [('E001', 'P001'), ('E002', 'P001'), ('E003', 'P002')]

def test_invalid_encounter_patient_reference(db_connection):
    patients = pd.DataFrame({
        'Id': ['P001', 'P002'],
        'FIRST': ['Alice', 'Bob']
    })

    encounters = pd.DataFrame({
        'Id': ['E001', 'E002', 'E003'],
        'PATIENT': ['P001', 'P999', 'P002']  # 'P999' is an invalid patient reference
    })

    load_tables(db_connection, patients, encounters)

    result = validate_encounter_patient_references(db_connection, 'CRITICAL')

    assert result['status'] == 'FAIL'
    assert result['count'] == 1
    assert result['severity'] == 'CRITICAL'

@pytest.mark.parametrize(
        "patient_references, expected_status, expected_count",
        [
            (['P001', 'P002', 'P001'], 'PASS', 0),
            (['P001', 'P999', 'P002'], 'FAIL', 1),
            (['P999', 'P888', 'P002'], 'FAIL', 2)
        ]
)

def test_encounter_reference_validation(db_connection, patient_references, expected_status, expected_count):
    patients = pd.DataFrame({
        'Id': ['P001', 'P002'],
        'FIRST': ['Alice', 'Bob']
    })

    encounters = pd.DataFrame({
        'Id': ['E001', 'E002', 'E003'],
        'PATIENT': patient_references
    })

    load_tables(db_connection, patients, encounters)

    result = validate_encounter_patient_references(db_connection, 'CRITICAL')

    assert result['status'] == expected_status
    assert result['count'] == expected_count
    assert result['severity'] == 'CRITICAL'