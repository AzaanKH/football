import sqlite3
import pandas as pd

# Connect to the SQLite database (or create it if it doesn't exist)
conn = sqlite3.connect('football_season.db')
cursor = conn.cursor()

# Create tables for each position
cursor.execute('''
CREATE TABLE IF NOT EXISTS wide_receivers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    PlayerName TEXT,
    PassingYDS REAL,
    PassingTD REAL,
    PassingInt REAL,
    RushingYDS REAL,
    RushingTD REAL,
    ReceivingRec REAL,
    ReceivingYDS REAL,
    ReceivingTD REAL,
    Fum REAL,
    TouchCarries REAL,
    TouchReceptions REAL,
    Targets REAL,
    RzTouch REAL,
    Rank REAL
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS running_backs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    PlayerName TEXT,
    PassingYDS REAL,
    PassingTD REAL,
    PassingInt REAL,
    RushingYDS REAL,
    RushingTD REAL,
    ReceivingRec REAL,
    ReceivingYDS REAL,
    ReceivingTD REAL,
    Fum REAL,
    TouchCarries REAL,
    TouchReceptions REAL,
    Targets REAL,
    RzTouch REAL,
    Rank REAL
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS quarterbacks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    PlayerName TEXT,
    PassingYDS REAL,
    PassingTD REAL,
    PassingInt REAL,
    RushingYDS REAL,
    RushingTD REAL,
    ReceivingRec REAL,
    ReceivingYDS REAL,
    ReceivingTD REAL,
    Fum REAL,
    TouchCarries REAL,
    TouchReceptions REAL,
    Targets REAL,
    RzTouch REAL,
    Rank REAL
)
''')

# Load data from CSVs into DataFrames
wr_data = pd.read_csv('filtered_wide_receivers.csv')
rb_data = pd.read_csv('filtered_running_backs.csv')
qb_data = pd.read_csv('filtered_quarterbacks.csv')

# Insert data into tables
wr_data.to_sql('wide_receivers', conn, if_exists='append', index=False)
rb_data.to_sql('running_backs', conn, if_exists='append', index=False)
qb_data.to_sql('quarterbacks', conn, if_exists='append', index=False)

print("Data inserted successfully")

# Commit and close the connection
conn.commit()
conn.close()