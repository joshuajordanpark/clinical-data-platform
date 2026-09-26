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

# Validate if there are any du
def validate_no_duplicate_rows(df, severity):
    duplicate_count = df.duplicated().sum()
    if duplicate_count == 0:
        status = "PASS"
    else:
        status = "FAIL"

    return {"check": "No duplicate rows", 
            "status": status,
            "severity": severity,
            "count": duplicate_count}

rows_before = patients_clean.shape[0]
print(f"Input: {rows_before} rows")

def remove_duplicates(df):
    duplicate_rows = df[df.duplicated()]
    if not duplicate_rows.empty:
        print(f"\nExact duplicate rows found: {len(duplicate_rows)}")
        df = df.drop_duplicates()
    return df

patients_clean = remove_duplicates(patients_clean)

rows_after = patients_clean.shape[0]
print(f"Output: {rows_after} rows")

# Print the DataFrame, its data types, dimensions, and column titles
# print(patients.dtypes)
print(f"Rows: {patients_clean.shape[0]:,} \nColumns: {patients_clean.shape[1]:,}")

# Check for duplicate rows in the DataFrame
print(f"\nDuplicate rows: {patients_clean.duplicated().sum()}")

# Check for duplicate values in the 'Id' column
print(f"Duplicate patient IDs: {patients_clean['Id'].duplicated().sum()}")

# Check for missing values in the 'Id' column
print(f"Missing patient IDs: {patients_clean['Id'].isna().sum()}")

# Get the number of missing values in each column
missing_values = patients_clean.isna().sum()
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
    results.append(validate_no_duplicate_rows(df, 'CRITICAL'))
    return results 

def validate_date_parse(column, parse_failure_count, severity):
    if parse_failure_count == 0:
        status = "PASS"
    else:
        status = "FAIL"
    return {"check": f"{column} parse",
            "status": status,
            "severity": severity,
            "count": parse_failure_count}   

def validate_date_order(df, earlier_column, later_column, severity):
    wrong_orders = df[
        df[later_column].notna()
        & (
            df[later_column] < df[earlier_column]
        )
    ]
    if len(wrong_orders) == 0:
        status = "PASS"
    else:
        status = "FAIL"

    return {
        "check": f"{later_column} after {earlier_column}",
        "status": status,
        "severity": severity,
        "count": len(wrong_orders) 
    }

def validate_not_future(df, column, severity):
    today = pd.Timestamp.today().normalize()
    
    future_dates = df[
        df[column] > today
    ]

    if len(future_dates) == 0:
        status = "PASS"
    else:
        status = "FAIL"

    return {
        "check": f"{column} not future",
        "status": status,
        "severity": severity,
        "count": len(future_dates)
    }

def validate_transformed_patient_data(df):
    results = []

    results.append(validate_date_parse('BIRTHDATE',birthdate_parse_failures,'CRITICAL'))
    results.append(validate_date_parse('DEATHDATE',deathdate_parse_failures,'CRITICAL'))
    results.append(validate_date_order(patients_clean, 'BIRTHDATE', 'DEATHDATE', 'CRITICAL'))
    results.append(validate_not_future(patients_clean,'BIRTHDATE', 'CRITICAL'))
    return results 

validation_results = validate_patient_data(patients_clean)

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

    # Replace "00000" with a missing value in the 'ZIP' column
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

    birthdate_missing_before = patients_clean['BIRTHDATE'].isna().sum()

    # Convert BIRTHDATE column to datetime format
    patients_clean['BIRTHDATE'] = pd.to_datetime(
        patients_clean['BIRTHDATE'],
        format='%Y-%m-%d',
        errors='coerce'
    )

    birthdate_missing_after = patients_clean['BIRTHDATE'].isna().sum()

    birthdate_parse_failures = (
        birthdate_missing_after - birthdate_missing_before
    ) 

    deathdate_missing_before = patients_clean['DEATHDATE'].isna().sum()

    # Convert DEATHDATE column to datetime format
    patients_clean['DEATHDATE'] = pd.to_datetime(
        patients_clean['DEATHDATE'],
        format='%Y-%m-%d',
        errors='coerce'
    )

    deathdate_missing_after = patients_clean['DEATHDATE'].isna().sum()

    deathdate_parse_failures = (
        deathdate_missing_after - deathdate_missing_before
    )

    death_before_birth = patients_clean[
        patients_clean['DEATHDATE'].notna()
        & (
            patients_clean['DEATHDATE'] < patients_clean['BIRTHDATE']
        )
    ]

    transformed_validation_results = validate_transformed_patient_data(patients_clean)

    for result in transformed_validation_results:
        print(result)

    print(f"BIRTHDATE dtype: {patients_clean['BIRTHDATE'].dtype}")
    print(f"DEATHDATE dtype: {patients_clean['DEATHDATE'].dtype}")

    post_critical_failures = []

    for result in transformed_validation_results:
        if result['status'] == 'FAIL' and result['severity'] == 'CRITICAL':
            post_critical_failures.append(result)

    if post_critical_failures:
        print("\nPIPELINE FAILED\nCritical validation failures:")
        for failure in post_critical_failures:
            print(f"- {failure['check']}: {failure['count']} failure(s)")
    else:

        # Save the cleaned DataFrame to a new CSV file
        patients_clean.to_csv(output_path, index=False)

        print(f"\nPipeline completed successfully.")
        print(f"Output written to: {output_path}")
