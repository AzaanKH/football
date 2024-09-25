import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.model_selection import GridSearchCV
from xgboost import XGBRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error
import numpy as np
import pickle

# Load the data
rb_data = pd.read_csv('filtered_running_backs.csv')
qb_data = pd.read_csv('filtered_quarterbacks.csv')
wr_data = pd.read_csv('filtered_wide_receivers.csv')
week_1_qbs_df = pd.read_csv('week_1_qbs.csv')
week_1_rbs_df = pd.read_csv('week_1_rbs.csv')
week_1_wrs_df = pd.read_csv('week_1_wrs.csv')
week_2_qbs_df = pd.read_csv('week_2_qbs.csv')
week_2_rbs_df = pd.read_csv('week_2_rbs.csv')
week_2_wrs_df = pd.read_csv('week_2_wrs.csv')
week_3_qbs_df = pd.read_csv('week_3_qbs.csv')
week_3_rbs_df = pd.read_csv('week_3_rbs.csv')
week_3_wrs_df = pd.read_csv('week_3_wrs.csv')
week_4_rankings = pd.read_csv('week_4_rankings.csv')

all_qb_data = pd.concat([qb_data, week_1_qbs_df, week_2_qbs_df, week_3_qbs_df], ignore_index=True)
all_rb_data = pd.concat([rb_data, week_1_rbs_df, week_2_rbs_df, week_3_rbs_df], ignore_index=True)
all_wr_data = pd.concat([wr_data, week_1_wrs_df, week_2_wrs_df, week_3_wrs_df, week_4_rankings], ignore_index=True)

# Define features and target variable
features = ['PassingYDS', 'PassingTD', 'PassingInt', 'RushingYDS', 'RushingTD', 
            'ReceivingRec', 'ReceivingYDS', 'ReceivingTD', 'Fum', 'TouchCarries', 
            'TouchReceptions', 'Targets', 'RzTouch', 'Rank']
target = 'TotalPoints'

# def feature_engineering(data):
#     # Example Feature: Rolling Average of Previous 3 Games (if data available)
#     data['Prev3GameAvgPoints'] = data['TotalPoints'].rolling(window=3, min_periods=1).mean()
    
#     # Example: Calculate Yards Per Attempt for Running Backs
#     data['YardsPerCarry'] = data['RushingYDS'] / (data['TouchCarries'] + 1e-5)  # Avoid division by zero
    
#     # Example: Add binary indicator for Home/Away
#     # data['IsHomeGame'] = np.where(data['Location'] == 'home', 1, 0)  # Assuming 'Location' is a column in your data

#     # Example: Include Offense/Defense Rankings
#     # Assuming 'TeamOffenseRank' and 'OpponentDefenseRank' are columns in your data
#     # data['OffenseVsDefenseDiff'] = data['TeamOffenseRank'] - data['OpponentDefenseRank']
    
#     # Handle missing values in engineered features
#     data.fillna(0, inplace=True)
    
#     return data

# rb_data = feature_engineering(rb_data)
# qb_data = feature_engineering(qb_data)
# wr_data = feature_engineering(wr_data)

def tune_hyperparameters(X, y):
    param_grid = {
        'n_estimators': [50, 100, 200],
        'learning_rate': [0.01, 0.1, 0.2],
        'max_depth': [3, 6, 9],
        'subsample': [0.6, 0.8, 1.0],
        'colsample_bytree': [0.6, 0.8, 1.0]
    }
    
    xgb_model = XGBRegressor(random_state=42)
    
    grid_search = GridSearchCV(estimator=xgb_model, param_grid=param_grid, 
                               cv=3, scoring='neg_mean_absolute_error', verbose=2, n_jobs=-1)
    
    grid_search.fit(X, y)
    
    return grid_search.best_estimator_, grid_search.best_params_


# X_rb = rb_data[features]  # Use the features selected earlier plus any newly engineered features
# y_rb = rb_data['TotalPoints']
# res = []
# best_rb_model, best_rb_params = tune_hyperparameters(X_rb, y_rb)
# print(f"Best parameters for Running Backs: {best_rb_params}")
# res.append(f"Best parameters for Running Backs: {best_rb_params}")

# X_qb = qb_data[features]
# y_qb = qb_data['TotalPoints']
# best_qb_model, best_qb_params = tune_hyperparameters(X_qb, y_qb)
# print(f"Best parameters for Quarterbacks: {best_qb_params}")
# res.append(f"Best parameters for Quarterbacks: {best_qb_params}")

# X_wr = wr_data[features]
# y_wr = wr_data['TotalPoints']
# best_wr_model, best_wr_params = tune_hyperparameters(X_wr, y_wr)
# print(f"Best parameters for Wide Receivers: {best_wr_params}")
# res.append(f"Best parameters for Wide Receivers: {best_wr_params}")
# print(res)



def train_and_evaluate_model(data, features, target, position_name, best_params):
    data = data[features + [target]].copy()
    
    data.fillna(0, inplace=True)
    
    X = data[features]
    y = data[target]
    
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    
    xgb_model = XGBRegressor(
        n_estimators=best_params['n_estimators'],
        learning_rate=best_params['learning_rate'],
        max_depth=best_params['max_depth'],
        subsample=best_params['subsample'],
        colsample_bytree=best_params['colsample_bytree'],
        random_state=42
    )
    
    xgb_model.fit(X_train, y_train)
    
    y_pred = xgb_model.predict(X_test)
    
    mae = mean_absolute_error(y_test, y_pred)
    mse = mean_squared_error(y_test, y_pred)
    rmse = np.sqrt(mse)
    
    print(f"Model performance for {position_name}:")
    print(f"Mean Absolute Error (MAE): {mae}")
    print(f"Mean Squared Error (MSE): {mse}")
    print(f"Root Mean Squared Error (RMSE): {rmse}")
    
    return xgb_model

# Best parameters for each model as previously identified
best_params_rb = {'colsample_bytree': 0.8, 'learning_rate': 0.1, 'max_depth': 3, 'n_estimators': 200, 'subsample': 0.8}
best_params_qb = {'colsample_bytree': 0.6, 'learning_rate': 0.1, 'max_depth': 3, 'n_estimators': 200, 'subsample': 0.8}
best_params_wr = {'colsample_bytree': 0.6, 'learning_rate': 0.2, 'max_depth': 3, 'n_estimators': 200, 'subsample': 0.6}

# Train and evaluate models using the combined data
rb_model = train_and_evaluate_model(all_rb_data, features, target, "Running Backs", best_params_rb)
qb_model = train_and_evaluate_model(all_qb_data, features, target, "Quarterbacks", best_params_qb)
wr_model = train_and_evaluate_model(all_wr_data, features, target, "Wide Receivers", best_params_wr)

# Save the models for later use
with open('rb_model.pkl', 'wb') as f:
    pickle.dump(rb_model, f)

with open('qb_model.pkl', 'wb') as f:
    pickle.dump(qb_model, f)

with open('wr_model.pkl', 'wb') as f:
    pickle.dump(wr_model, f)
