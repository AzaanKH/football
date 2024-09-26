import pdfplumber
import pandas as pd


def pdf_to_csv(pdf_path, output_csv_path):

    with pdfplumber.open(pdf_path) as pdf:
        all_data = []


        for page in pdf.pages:

            tables = page.extract_tables()
            

            if tables:
                for table in tables:
                    df = pd.DataFrame(table)
                    all_data.append(df)

        if all_data:
            final_df = pd.concat(all_data, ignore_index=True)
            final_df.to_csv(output_csv_path, index=False, header=False)
            print(f"Data extracted and saved to {output_csv_path}")
        else:
            print("No tabular data found in the PDF.")

pdf_to_csv('wr_rankings_week_4.pdf', 'week_4_rankings.csv')
pdf_to_csv('rb_rankings_week_4.pdf', 'week_4_rankings.csv')
pdf_to_csv('qb_rankings_week_4.pdf', 'week_4_rankings.csv')