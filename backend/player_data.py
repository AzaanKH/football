import pandas as pd
from io import StringIO

# Provided text data
text_data = """
RK,NAME,POS,GP,REC,TGTS,YDS,AVG,TD,LNG,BIG,YDS/G,FUM,LST,YAC,FD
1,Nico Collins HOU,WR,3,18,28,338,18.8,1,55,5,112.7,0,0,107,16
2,Rashee Rice KC,WR,3,24,29,288,12.0,2,44,3,96.0,0,0,186,15
3,Jauan Jennings SF,WR,3,18,21,276,15.3,3,49,4,92.0,0,0,42,12
4,Justin Jefferson MIN,WR,3,14,21,273,19.5,3,97,4,91.0,0,0,101,10
5,Malik Nabers NYG,WR,3,23,37,271,11.8,3,28,6,90.3,0,0,127,14
6,DK Metcalf SEA,WR,3,17,24,262,15.4,2,71,3,87.3,0,0,105,7
7,Chris Godwin TB,WR,3,21,25,253,12.0,3,41,2,84.3,0,0,138,17
8,Dallas Goedert PHI,TE,3,17,20,239,14.1,0,61,5,79.7,0,0,158,7
8,DeVonta Smith PHI,WR,3,21,28,239,11.4,0,25,2,79.7,0,0,77,13
10,Alec Pierce IND,WR,3,13,24,218,16.8,1,65,3,72.7,1,1,106,8
11,CeeDee Lamb DAL,WR,3,16,18,215,13.4,2,41,4,71.7,0,0,72,9
12,Ja'Marr Chase CIN,WR,3,18,27,209,11.6,1,30,4,69.7,0,0,45,10
12,Davante Adams LV,WR,3,11,23,209,19.0,1,52,4,69.7,0,0,100,6
13,Jameson Williams DET,WR,3,21,32,207,9.9,1,20,2,69.0,0,0,52,12
15,Amon-Ra St. Brown DET,WR,3,10,22,198,19.8,3,60,3,66.0,0,0,31,9
16,Marvin Harrison Jr. ARI,WR,3,10,14,197,19.7,1,70,4,65.7,0,0,116,4
17,Jayden Reed GB,TE,3,18,21,197,10.9,0,27,4,65.7,0,0,81,10
17,Brock Bowers LV,WR,3,13,23,194,14.9,1,80,2,64.7,0,0,119,8
19,Tyreek Hill MIA,WR,3,11,17,189,17.2,1,66,2,63.0,0,0,61,8
20,Brian Thomas Jr. JAX,WR,3,12,14,178,14.8,1,39,2,59.3,0,0,38,10
21,Chris Olave NO,WR,3,13,14,176,13.5,0,63,3,58.7,0,0,69,7
22,Jaylen Waddle MIA,WR,3,17,21,175,10.3,0,24,1,58.3,0,0,81,9
23,Jaxon Smith-Njigba SEA,RB,3,11,15,174,15.8,0,49,4,58.0,0,0,35,7
24,Josh Reynolds DEN,WR,3,17,19,173,10.2,1,39,2,57.7,0,0,183,8
25,De'Von Achane MIA,WR,3,13,17,171,13.2,0,40,3,57.0,0,0,18,9
26,George Pickens PIT,WR,3,7,14,169,24.1,2,70,2,56.3,0,0,65,5
27,Rashid Shaheed NO,WR,3,12,18,169,14.1,1,41,4,56.3,0,0,79,7
27,Darnell Mooney ATL,WR,3,14,14,168,12.0,2,27,2,56.0,0,0,117,10
29,Khalil Shakir BUF,WR,3,19,28,167,8.8,0,44,1,55.7,0,0,80,8
30,DJ Moore CHI,WR,3,20,24,164,8.2,2,21,1,54.7,0,0,70,10
31,Stefon Diggs HOU,TE,2,13,19,164,12.6,0,28,3,82.0,0,0,54,9
31,Deebo Samuel SF,WR,3,14,18,156,11.1,0,37,1,52.0,0,0,74,7
33,Mike Gesicki CIN,WR,3,13,26,156,12.0,1,35,2,52.0,0,0,62,9
33,Diontae Johnson CAR,WR,3,9,20,156,17.3,1,47,3,52.0,1,0,39,7
33,Rome Odunze CHI,WR,3,14,17,152,10.9,1,33,1,50.7,0,0,37,8
36,Jakobi Meyers LV,WR,3,15,26,150,10.0,1,26,1,50.0,0,0,59,9
37,Garrett Wilson NYJ,WR,3,11,16,148,13.5,3,36,1,49.3,0,0,70,10
38,Allen Lazard NYJ,WR,2,16,25,148,9.3,1,21,1,49.3,0,0,67,6
39,Zay Flowers BAL,WR,2,18,27,147,8.2,1,24,3,73.5,0,0,65,7
40,Cooper Kupp LAR,TE,3,7,9,141,20.1,0,50,3,47.0,0,0,22,6
41,Tutu Atwell LAR,WR,3,12,16,141,11.8,1,49,1,47.0,0,0,96,7
41,Isaiah Likely BAL,TE,3,12,17,139,11.6,2,55,2,46.3,0,0,36,6
43,Terry McLaurin WSH,WR,3,13,17,138,10.6,0,19,0,46.0,0,0,27,10
44,Tyler Lockett SEA,WR,3,12,18,136,11.3,0,35,1,45.3,0,0,69,9
45,Hunter Henry NE,WR,3,8,16,136,17.0,1,40,3,45.3,0,0,26,5
45,Calvin Ridley TEN,WR,3,10,16,136,13.6,1,39,1,45.3,0,0,10,7
45,Jalen Tolbert DAL,RB,3,14,19,136,9.7,2,19,0,45.3,0,0,39,7
"""

# Convert the text data into a DataFrame
data = pd.read_csv(StringIO(text_data))

# Save the DataFrame as a CSV file
output_csv_path = 'wide_recievers_rankings_week_4.csv'
data.to_csv(output_csv_path, index=False)

output_csv_path