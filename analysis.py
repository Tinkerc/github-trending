import os
import re
import csv
from collections import defaultdict

def extract_entries_from_file(file_path):
    entries = []
    current_language = None
    current_date = None
    with open(file_path, 'r', encoding='utf-8') as file:
        for line in file:
            # Check for date header
            date_match = re.match(r'##\s*(\d{4}-\d{2}-\d{2})', line)
            if date_match:
                current_date = date_match.group(1)
            # Check for language header
            language_match = re.match(r'####\s*(\w+)', line)
            if language_match:
                current_language = language_match.group(1)
            # Match entries
            entry_match = re.match(r'\*\s*\[(.*?)\]\s*\((.*?)\)\s*:\s*(.*)', line)
            if entry_match and current_language and current_date:
                name, url, description = entry_match.groups()
                entries.append((name.strip(), url.strip(), description.strip(), current_language, current_date))
    return entries

def analyze_md_files(directory):
    entry_count = defaultdict(int)
    entry_details = {}

    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith('.md'):
                file_path = os.path.join(root, file)
                last_date = file.replace('.md', '')  # Use file name as last_date
                entries = extract_entries_from_file(file_path)
                for entry in entries:
                    entry_with_date = entry[:-1] + (last_date,)  # Update entry with last_date
                    entry_count[entry_with_date] += 1
                    entry_details[entry_with_date] = entry_with_date

    return entry_count, entry_details

def save_to_csv(entry_count, entry_details, output_directory):
    os.makedirs(output_directory, exist_ok=True)
    
    # Aggregate data by Language
    language_data = defaultdict(list)
    
    for entry, count in entry_count.items():
        name, url, description, language, last_date = entry
        language_data[language].append({'Name': name, 'URL': url, 'Description': description, 
                                        'Count': count, 'Last Date': last_date})

    # Save each language's data to a separate CSV file
    for language, data in language_data.items():
        # Sort data by Last Date in descending order
        sorted_data = sorted(data, key=lambda x: x['Last Date'], reverse=True)
        
        output_file = os.path.join(output_directory, f"{language}_analysis_results.csv")
        with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['Name', 'URL', 'Description', 'Count', 'Last Date']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            writer.writeheader()
            for row in sorted_data:
                writer.writerow(row)

if __name__ == "__main__":
    directory = './2025'
    output_directory = './output'
    entry_count, entry_details = analyze_md_files(directory)
    save_to_csv(entry_count, entry_details, output_directory)