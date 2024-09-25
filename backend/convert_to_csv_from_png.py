import pytesseract
from PIL import Image
import pandas as pd

# Function to convert image to text and then to DataFrame
def image_to_csv(image_path, output_csv_path, expected_columns):
    # Load the image using PIL
    image = Image.open(image_path)
    
    # Extract text from the image using Tesseract
    text = pytesseract.image_to_string(image)
    
    # Split the text into lines
    lines = text.splitlines()
    
    # Process the lines into a structured format
    data = []
    for line in lines:
        # Normalize spaces/tabs and split into entries
        entries = line.strip().split()
        
        # Check if the length of entries matches the expected number of columns
        if len(entries) == expected_columns:
            data.append(entries)
        elif len(entries) > expected_columns:
            # If there are more entries, try to combine them correctly
            # This often happens if spaces within a single value cause additional splits
            combined_entries = []
            for entry in entries:
                if len(combined_entries) < expected_columns - 1:
                    combined_entries.append(entry)
                else:
                    # Combine remaining entries as the last column value
                    combined_entries.append(" ".join(entries[len(combined_entries):]))
                    break
            data.append(combined_entries)
        elif len(entries) > 1:
            # Pad the row if it has fewer columns than expected
            entries.extend([''] * (expected_columns - len(entries)))
            data.append(entries)
    
    # Create a DataFrame from the extracted data
    df = pd.DataFrame(data)

    # Save the DataFrame to a CSV file
    df.to_csv(output_csv_path, index=False)
    print(f"Data extracted and saved to {output_csv_path}")

# Define the expected number of columns (adjust based on the actual data structure)
EXPECTED_COLUMNS = 7  # For example, adjust if you expect 7 columns from the image data

# Use the function for your image files with expected columns
# image_to_csv('week_1_wrs.png', 'week_1_wrs.csv', EXPECTED_COLUMNS)
# image_to_csv('week_2_wrs.png', 'week_2_wrs.csv', EXPECTED_COLUMNS)
# image_to_csv('week_3_wrs.png', 'week_3_wrs.csv', EXPECTED_COLUMNS)

image_to_csv('week_1_rbs.png', 'week_1_rbs.csv', EXPECTED_COLUMNS)
image_to_csv('week_2_rbs.png', 'week_2_rbs.csv', EXPECTED_COLUMNS)
image_to_csv('week_3_rbs.png', 'week_3_rbs.csv', EXPECTED_COLUMNS)

# Repeat the process for other positions or weeks as needed
image_to_csv('week_1_qbs.png', 'week_1_qbs.csv', EXPECTED_COLUMNS)
image_to_csv('week_2_qbs.png', 'week_2_qbs.csv', EXPECTED_COLUMNS)
image_to_csv('week_3_qbs.png', 'week_3_qbs.csv', EXPECTED_COLUMNS)