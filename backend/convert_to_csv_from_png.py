import pytesseract
from PIL import Image
import pandas as pd

def image_to_csv(image_path, output_csv_path, expected_columns):
    image = Image.open(image_path)
    
    text = pytesseract.image_to_string(image)
    
    lines = text.splitlines()
    
    data = []
    for line in lines:
        entries = line.strip().split()
        
        if len(entries) == expected_columns:
            data.append(entries)
        elif len(entries) > expected_columns:
            combined_entries = []
            for entry in entries:
                if len(combined_entries) < expected_columns - 1:
                    combined_entries.append(entry)
                else:
                    combined_entries.append(" ".join(entries[len(combined_entries):]))
                    break
            data.append(combined_entries)
        elif len(entries) > 1:
            entries.extend([''] * (expected_columns - len(entries)))
            data.append(entries)
    
    df = pd.DataFrame(data)

    df.to_csv(output_csv_path, index=False)
    print(f"Data extracted and saved to {output_csv_path}")

EXPECTED_COLUMNS = 7  

# image_to_csv('week_1_wrs.png', 'week_1_wrs.csv', EXPECTED_COLUMNS)
# image_to_csv('week_2_wrs.png', 'week_2_wrs.csv', EXPECTED_COLUMNS)
# image_to_csv('week_3_wrs.png', 'week_3_wrs.csv', EXPECTED_COLUMNS)

image_to_csv('week_1_rbs.png', 'week_1_rbs.csv', EXPECTED_COLUMNS)
image_to_csv('week_2_rbs.png', 'week_2_rbs.csv', EXPECTED_COLUMNS)
image_to_csv('week_3_rbs.png', 'week_3_rbs.csv', EXPECTED_COLUMNS)

image_to_csv('week_1_qbs.png', 'week_1_qbs.csv', EXPECTED_COLUMNS)
image_to_csv('week_2_qbs.png', 'week_2_qbs.csv', EXPECTED_COLUMNS)
image_to_csv('week_3_qbs.png', 'week_3_qbs.csv', EXPECTED_COLUMNS)