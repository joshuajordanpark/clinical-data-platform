from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent

output_path = PROJECT_ROOT / 'data' / 'processed' / 'patients_clean.csv'

# Read the patients.csv file into a DataFrame
patients = pd.read_csv(PROJECT_ROOT / 'data' / 'raw' / 'patients.csv',
                       dtype={
                           'ZIP': 'string',
                           'FIPS': 'string'
                       })

# Create a copy of the DataFrame to work with
patients_clean = patients.copy()

# Print the DataFrame, its data types, dimensions, and column titles
# print(patients.dtypes)
print(f"Rows: {patients.shape[0]:,} \nColumns: {patients.shape[1]:,}")

# Check for duplicate rows in the DataFrame
print(f"\nDuplicate rows: {patients.duplicated().sum()}")

# Check for duplicate values in the 'Id' column
print(f"Duplicate patient IDs: {patients['Id'].duplicated().sum()}")

# Check for missing values in the 'Id' column
print(f"Missing patient IDs: {patients['Id'].isna().sum()}")

# Get the number of missing values in each column
missing_values = patients.isna().sum()
print("\nMissing values:")
print(missing_values[missing_values > 0])

print(f"\nValidation:")

def validate_unique_id(df, column, severity):
    duplicate_count = df[column].duplicated().sum()
    if duplicate_count == 0:
        status = "PASS"
    else:
        status = "FAIL"

    return {"check": f"{column} unique", 
            "status": status,
            "severity": severity,
            "count": duplicate_count}

def validate_not_null(df, column, severity):
    null_count = df[column].isna().sum()

    if null_count == 0:
        status = "PASS"
    else:
        status = "FAIL"

    return {"check": f"{column} not null",
            "status": status,
            "severity": severity,
            "count": null_count}

def validate_no_value(df, column, invalid_value, severity):
    invalid_count = (df[column] == invalid_value).sum()
    if invalid_count == 0:
        status = "PASS"
    else:
        status = "FAIL"

    return {"check": f"{column} invalid value '{invalid_value}'",
            "status": status,
            "severity": severity,
            "count": invalid_count}

def validate_patient_data(df):
    results = []

    results.append(validate_unique_id(df, 'Id', 'CRITICAL'))
    results.append(validate_not_null(df, 'Id', 'CRITICAL'))
    results.append(validate_no_value(df, 'ZIP', '00000', 'WARNING'))

    return results 

validation_results = validate_patient_data(patients)

for result in validation_results:
    print(result)

critical_failures = []

for result in validation_results:
    if result['status'] == 'FAIL' and result['severity'] == 'CRITICAL':
        critical_failures.append(result)

if critical_failures:
    print("\nPIPELINE FAILED\nCritical validation failures:")
    for failure in critical_failures:
        print(f"- {failure['check']}: {failure['count']} failure(s)")
else:
    # If there are no critical failures, proceed with data cleaning

    # Clean the 'ZIP' column by replacing invalid placeholders with missing value
    missing_zip_before = patients_clean['ZIP'].isna().sum()
    invalid_zip_count = (patients_clean['ZIP'] == "00000").sum()
    print(f"\nInvalid ZIP placeholders before cleaning: {invalid_zip_count}")

    # Replace "00000" with NaN in the 'ZIP' column
    patients_clean['ZIP'] = patients_clean['ZIP'].replace("00000", pd.NA)
    remaining_invalid_zips = (patients_clean['ZIP'] == "00000").sum()
    missing_zip_after = patients_clean['ZIP'].isna().sum()
    print(f"Invalid ZIP placeholders after cleaning: {remaining_invalid_zips}")
    print(f"Missing ZIP values after cleaning: {missing_zip_after}")

    # Check for rows where 'FIPS' is missing but 'ZIP' is present
    fips_without_missing_zip = patients_clean[
        patients_clean['FIPS'].isna() & patients_clean['ZIP'].notna()
    ]

    expected_missing_after = missing_zip_before + invalid_zip_count

    if missing_zip_after == expected_missing_after:
        print("ZIP normalization: PASS")
    else:
        print("ZIP normalization: FAIL")

    if fips_without_missing_zip.empty:
        print("FIPS/ZIP relationship: PASS")
    else:
        print(
            f"FIPS/ZIP relationship: FAIL - "
            f"{len(fips_without_missing_zip)} rows")

    # Save the cleaned DataFrame to a new CSV file
    patients_clean.to_csv(output_path, index=False)

    print(f"\nPipeline completed successfully.")
    print(f"Output written to: {output_path}")


