import sqlite3
import pandas as pd

conn = sqlite3.connect('football_season.db')
cursor = conn.cursor()

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

wr_data = pd.read_csv('wide_receivers_rankings_week_4.csv')
rb_data = pd.read_csv('running_backs_rankings_week_4.csv')
qb_data = pd.read_csv('quarterbacks_rankings_week_4.csv')

wr_data.to_sql('wide_receivers', conn, if_exists='append', index=False)
rb_data.to_sql('running_backs', conn, if_exists='append', index=False)
qb_data.to_sql('quarterbacks', conn, if_exists='append', index=False)

print("Data inserted successfully")

conn.commit()
conn.close()