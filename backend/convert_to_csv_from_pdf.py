import pdfplumber
import pandas as pd

# Function to convert a PDF to a CSV file
def pdf_to_csv(pdf_path, output_csv_path):
    # Open the PDF file
    with pdfplumber.open(pdf_path) as pdf:
        all_data = []

        # Iterate through all pages
        for page in pdf.pages:
            # Extract tables from the page
            tables = page.extract_tables()
            
            # Check if any table data is present
            if tables:
                for table in tables:
                    # Convert table data to DataFrame
                    df = pd.DataFrame(table)
                    all_data.append(df)

        # Concatenate all DataFrames into one
        if all_data:
            final_df = pd.concat(all_data, ignore_index=True)
            # Save the DataFrame to a CSV file
            final_df.to_csv(output_csv_path, index=False, header=False)
            print(f"Data extracted and saved to {output_csv_path}")
        else:
            print("No tabular data found in the PDF.")

# Convert your PDF file to CSV
pdf_to_csv('wr_rankings_week_4.pdf', 'week_4_rankings.csv')
pdf_to_csv('rb_rankings_week_4.pdf', 'week_4_rankings.csv')
pdf_to_csv('qb_rankings_week_4.pdf', 'week_4_rankings.csv')