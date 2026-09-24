import pandas as pd

# Read the patients.csv file into a DataFrame
patients = pd.read_csv('/Users/JoshPark/Documents/clinical-data-platform/data/raw/patients.csv')

# Get the number of rows and columns in the DataFrame
patientsDimension = patients.shape

# Get the column titles of the DataFrame
columnTitles = patients.columns.tolist()

# Get the number of rows in the DataFrame
row_count = len(patients)

# Print the DataFrame, its data types, dimensions, and column titles
print(patients.dtypes)

print(patientsDimension)

print(f"Column titles: {columnTitles}")

# Get the number of missing values in each column
missing_values = patients.isna().sum()
print(patients.info())
print(patients.isna())
print(missing_values)

# Check for duplicate rows in the DataFrame
print(patients.duplicated().any())

# Check for duplicate values in the 'Id' column
print(patients['Id'].duplicated().any())