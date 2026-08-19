import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report
from sklearn.preprocessing import LabelEncoder
import pickle
import re

print("Carregando o dataset original completo...")
df = pd.read_csv('data/dataset.csv')

# --- ENGENHARIA DE FEATURES: A MUDANÇA MAIS IMPORTANTE ---
print("Aplicando engenharia de features para extrair o sinal dos dados...")

# 1. Criar Categoria do Caminhão (o sinal mais forte)
def get_truck_category(model_name):
    model_name = str(model_name).lower()
    # Pesados e Extra-Pesados (geralmente PBT > 23t)
    if any(s in model_name for s in ['fh', 'fmx', 'r4', 'r5', 'r6', 'g4', 'g5', 'actros', 'axor', 'hi-way', 'stralis', 'xf', 'meteor', '8x4', '10x4']):
        return 'Extra-Pesado'
    # Médios e Semi-Pesados (PBT ~16t-23t)
    if any(s in model_name for s in ['vm', 'atego', 'constellation', 'cargo', 'tector', 'p3', 'g3', 'worker']):
        return 'Medio'
    # Leves (PBT < 16t)
    if any(s in model_name for s in ['delivery', 'accelo', 'daily', 'f-4000', '816']):
        return 'Leve'
    return 'Outro' # Categoria para modelos menos comuns

# 2. Criar Categoria da Caçamba (nosso novo alvo)
def get_caçamba_category(model_name):
    model_name = str(model_name)
    if re.search(r'-(A|0)', model_name): return 'Pequena'
    if re.search(r'-(B|1)', model_name): return 'Media'
    if re.search(r'-(C|2)', model_name): return 'Grande'
    if re.search(r'-(D|E|3)', model_name): return 'Extra-Grande'
    if any(s in model_name.lower() for s in ['tanque', 'prancha', 'sider', 'bau', 'gaiola', 'coletor']): return 'Especial'
    return 'Outro'

df['truck_category'] = df['truck_model'].apply(get_truck_category)
df['caçamba_category'] = df['recommended_model'].apply(get_caçamba_category)

# Usaremos apenas as features inteligentes
X = df[['truck_category', 'axle_count', 'chassis_length_m']] 
y = df['caçamba_category'] # Nosso novo alvo

print("Processando features e alvo...")
X_encoded = pd.get_dummies(X, columns=['truck_category'])
le = LabelEncoder()
y_encoded = le.fit_transform(y)

# Divisão com stratify, que agora vai funcionar
X_train, X_test, y_train, y_test = train_test_split(X_encoded, y_encoded, test_size=0.25, random_state=42, stratify=y_encoded)

print(f"Dataset de {len(df)} exemplos processado com sucesso.")

# --- Treinamento do Modelo Final ---
print("\nIniciando o treinamento do modelo de categorias...")
model = RandomForestClassifier(n_estimators=100, random_state=42, n_jobs=-1)
model.fit(X_train, y_train)
print("Treinamento concluído!")

# --- Avaliação ---
print("\nAvaliando o modelo final...")
y_pred_encoded = model.predict(X_test)
y_pred = le.inverse_transform(y_pred_encoded)
y_test_labels = le.inverse_transform(y_test)

accuracy = accuracy_score(y_test_labels, y_pred)
print(f"Acurácia FINAL do modelo de categorias: {accuracy * 100:.2f}%")
print("\nRelatório de Classificação Final:")
print(classification_report(y_test_labels, y_pred))

# --- Salvamento ---
with open('recommendation_model.pkl', 'wb') as f: pickle.dump(model, f)
with open('label_encoder.pkl', 'wb') as f: pickle.dump(le, f)
model_columns = list(X_encoded.columns)
with open('model_columns.pkl', 'wb') as f: pickle.dump(model_columns, f)

print(f"\nModelo final e arquivos de suporte salvos com sucesso!")# backend/train_model.py
import pandas as pd
import numpy as np
import os
import pickle
from sklearn.preprocessing import LabelEncoder
from sklearn.model_selection import train_test_split
from xgboost import XGBClassifier
from sklearn.metrics import classification_report, accuracy_score

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# paths
DATASET = os.path.join(BASE_DIR, 'data', 'dataset.csv')
FICHA = os.path.join(BASE_DIR, 'data', 'caminhoes_ficha_tecnica.csv')
OUT_MODEL = os.path.join(BASE_DIR, 'recommendation_model.pkl')
OUT_LE = os.path.join(BASE_DIR, 'label_encoder.pkl')
OUT_COLS = os.path.join(BASE_DIR, 'model_columns.pkl')

# 1. load
df = pd.read_csv(DATASET)
ficha = pd.read_csv(FICHA)

# 2. normalize modelo names for joining (lowercase, strip)
df['truck_model_norm'] = df['truck_model'].str.lower().str.strip()
ficha['modelo_norm'] = ficha['Modelo'].str.lower().str.strip()

# 3. left-join ficha técnica (merge, adiciona PBT e capacity)
merged = df.merge(ficha[['modelo_norm','Peso_Bruto_Total_PBT_kg','Capacidade_Carga_Util_kg','Comprimento_Max_Carroceria_Sem_Alteracoes_mm']],
                  left_on='truck_model_norm', right_on='modelo_norm', how='left')

# 4. feature engineering
merged['chassis_length_mm'] = merged['chassis_length_m'] * 1000
# fillna with reasonable defaults or -1
merged['Peso_Bruto_Total_PBT_kg'] = merged['Peso_Bruto_Total_PBT_kg'].fillna(-1)
merged['Capacidade_Carga_Util_kg'] = merged['Capacidade_Carga_Util_kg'].fillna(-1)
merged['Comprimento_Max_Carroceria_Sem_Alteracoes_mm'] = merged['Comprimento_Max_Carroceria_Sem_Alteracoes_mm'].fillna(-1)

# select X and y
X = merged[['axle_count','chassis_length_mm','Peso_Bruto_Total_PBT_kg','Capacidade_Carga_Util_kg','Comprimento_Max_Carroceria_Sem_Alteracoes_mm']]
# add truck_model as categorical (one-hot)
X = pd.get_dummies(X.join(merged['truck_model']), columns=['truck_model'], prefix='model', drop_first=False)

y = merged['recommended_model']
le = LabelEncoder()
y_enc = le.fit_transform(y)

# keep columns for API alignment
model_columns = X.columns.tolist()

# train/test
X_train, X_test, y_train, y_test = train_test_split(X, y_enc, test_size=0.2, random_state=42, stratify=y_enc)

model = XGBClassifier(n_estimators=200, max_depth=6, use_label_encoder=False, eval_metric='mlogloss', random_state=42)
model.fit(X_train, y_train)

pred = model.predict(X_test)
acc = accuracy_score(y_test, pred)
print("Accuracy:", acc)
print(classification_report(y_test, pred, target_names=le.classes_))

# save
with open(OUT_MODEL, 'wb') as f: pickle.dump(model, f)
with open(OUT_LE, 'wb') as f: pickle.dump(le, f)
with open(OUT_COLS, 'wb') as f: pickle.dump(model_columns, f)

print("Model, label encoder and columns saved.")