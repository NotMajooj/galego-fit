# app.py - GALEGO Fit 2.5 (recomendação explicada + carga + visão + histórico amigável)

import os
import re
import csv
import smtplib
import pickle
import logging
import unicodedata
import datetime
import difflib
from uuid import uuid4
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

import pandas as pd
import numpy as np
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

# opcional: carrega .env em desenvolvimento
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

app = Flask(__name__, static_folder='static')
CORS(app)

# --------------------------------------------------------------------
# CONFIGURAÇÕES E CAMINHOS
# --------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
STATIC_IMAGES_DIR = os.path.join(BASE_DIR, 'static', 'images')
os.makedirs(STATIC_IMAGES_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

MODEL_PATH = os.path.join(BASE_DIR, 'recommendation_model.pkl')
LABEL_ENCODER_PATH = os.path.join(BASE_DIR, 'label_encoder.pkl')
MODEL_COLUMNS_PATH = os.path.join(BASE_DIR, 'model_columns.pkl')

DATASET_PATH = os.path.join(DATA_DIR, 'dataset.csv')
PRODUCTION_ORDERS_PATH = os.path.join(DATA_DIR, 'cacambas_ordem_producao.csv')
CATALOG_PATH = os.path.join(DATA_DIR, 'cacambas_catalogo.csv')
ACCEPT_LOG_PATH = os.path.join(DATA_DIR, 'accepted_logs.csv')
RESERVATIONS_PATH = os.path.join(DATA_DIR, 'reservas.csv')
CLIENT_HISTORY_PATH = os.path.join(DATA_DIR, 'clientes_historico.csv')
CHAT_CONFIRMATIONS_PATH = os.path.join(DATA_DIR, 'chat_confirmations.csv')

# SMTP / EMAIL (usado apenas para vendedor)
SMTP_HOST = os.environ.get('SMTP_HOST', 'smtp-relay.brevo.com')
SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
SMTP_USER = os.environ.get('SMTP_USER')         # ex.: 9c5e04001@smtp-brevo.com
SMTP_PASS = os.environ.get('SMTP_PASS')
SMTP_USE_TLS = os.environ.get('SMTP_USE_TLS', 'true').lower() in ('1', 'true', 'yes')
EMAIL_FROM = os.environ.get('EMAIL_FROM') or SMTP_USER
SALES_EMAILS = os.environ.get('SALES_EMAILS', 'vendas@empresa.com')
CONFIRM_BASE_URL = os.environ.get('CONFIRM_BASE_URL', 'http://localhost:5000')

# modelos globais
model = None
label_encoder = None
model_columns = None
original_df = None
catalog_df = None

# --------------------------------------------------------------------
# MAPEAMENTO CATEGORIA -> MODELO PADRÃO
# --------------------------------------------------------------------
CATEGORY_TO_MODEL_MAP = {
    'Pequena': 'Caçamba-A10 (Pequena)',
    'Media': 'Caçamba-B15 (Média)',
    'Medio': 'Caçamba-B15 (Média)',      # tolerância
    'Grande': 'Caçamba-C18 (Grande)',
    'Extra-Grande': 'Caçamba-D25 (Extra-Grande)',
    'Especial': 'Verificar Caçambas Especiais (Tanque/Prancha/etc.)',
    'Outro': 'Consultar Engenharia'
}

# aproximação simples de PBT e tara por número de eixos
AXLE_TO_PBT = {2: 16000, 3: 23000, 4: 32000, 5: 41000}
AXLE_TO_TARA_TRUCK = {2: 6000, 3: 8000, 4: 11000, 5: 13000}
CATEGORY_TARA_CACAMBA = {
    'Pequena': 2000,
    'Media': 3500,
    'Média': 3500,
    'Grande': 4500,
    'Extra-Grande': 6000,
    'Especial': 4000,
    'Outro': 3500
}

# densidade aproximada por tipo de carga (ton/m³)
CARGO_TYPE_DENSITY = {
    'graos': 0.8,
    'areia': 1.6,
    'brita': 1.8,
    'terra': 1.5,
    'entulho_leve': 0.9,
    'entulho_pesado': 1.3,
    'sucata': 0.7,
    'outro': 1.6  # default genérico
}

# --------------------------------------------------------------------
# HELPERS GERAIS
# --------------------------------------------------------------------
def normalize_category_key(key):
    if key is None:
        return None
    k = str(key).strip()
    k_norm = unicodedata.normalize('NFKD', k).encode('ascii', 'ignore').decode('ascii')
    return k_norm[0].upper() + k_norm[1:] if k_norm else k_norm


def slugify(name):
    if not name:
        return ''
    s = unicodedata.normalize('NFKD', str(name)).encode('ascii', 'ignore').decode('ascii')
    s = re.sub(r'[^a-zA-Z0-9_-]+', '_', s)
    return s.lower().strip('_')


def normalize_cargo_type(raw):
    """
    Converte texto livre para uma chave de tipo de carga:
    graos, areia, brita, terra, entulho_leve, entulho_pesado, sucata, outro
    """
    if not raw:
        return None
    k = unicodedata.normalize('NFKD', str(raw).lower()).encode('ascii', 'ignore').decode('ascii')
    k = k.replace('  ', ' ').strip()
    k_ = k.replace(' ', '_')

    aliases = {
        'graos': 'graos',
        'grao': 'graos',
        'soja': 'graos',
        'milho': 'graos',
        'areia': 'areia',
        'brita': 'brita',
        'pedra': 'brita',
        'terra': 'terra',
        'entulho': 'entulho_pesado',
        'entulho_leve': 'entulho_leve',
        'entulho_pesado': 'entulho_pesado',
        'sucata': 'sucata'
    }

    for key, val in aliases.items():
        if key in k_:
            return val

    return 'outro'


# --------------------------------------------------------------------
# CARREGAMENTO DE ARQUIVOS
# --------------------------------------------------------------------
def try_load_files():
    global model, label_encoder, model_columns, original_df, catalog_df
    try:
        logging.info("Carregando arquivos de modelo...")
        if os.path.exists(MODEL_PATH):
            with open(MODEL_PATH, 'rb') as f:
                model = pickle.load(f)
            logging.info("Modelo carregado.")
        else:
            logging.warning("Modelo não encontrado em %s", MODEL_PATH)

        if os.path.exists(LABEL_ENCODER_PATH):
            with open(LABEL_ENCODER_PATH, 'rb') as f:
                label_encoder = pickle.load(f)
            logging.info("Label encoder carregado.")
        else:
            logging.warning("Label encoder não encontrado em %s", LABEL_ENCODER_PATH)

        if os.path.exists(MODEL_COLUMNS_PATH):
            with open(MODEL_COLUMNS_PATH, 'rb') as f:
                model_columns = pickle.load(f)
            logging.info("Colunas do modelo carregadas.")
        else:
            logging.warning("Arquivo de colunas não encontrado em %s", MODEL_COLUMNS_PATH)

        if os.path.exists(DATASET_PATH):
            original_df = pd.read_csv(DATASET_PATH)
            logging.info("Dataset carregado com %d linhas.", len(original_df))
        else:
            original_df = None
            logging.warning("Dataset não encontrado em %s", DATASET_PATH)

        if os.path.exists(CATALOG_PATH):
            catalog_df = pd.read_csv(CATALOG_PATH)
            logging.info("Catálogo de caçambas carregado com %d linhas.", len(catalog_df))
        else:
            catalog_df = None
            logging.warning("Catálogo de caçambas não encontrado em %s", CATALOG_PATH)

    except Exception as e:
        logging.exception("Erro ao carregar arquivos: %s", e)
        model = label_encoder = model_columns = original_df = catalog_df = None


try_load_files()

# --------------------------------------------------------------------
# FUNÇÕES DE NEGÓCIO
# --------------------------------------------------------------------
def get_truck_category(model_name):
    if model_name is None:
        return 'Outro'
    m = str(model_name).lower()
    if any(s in m for s in ['fh', 'fmx', 'r4', 'r5', 'r6', 'g4', 'g5', 'actros', 'axor',
                            'hi-way', 'stralis', 'xf', 'meteor', '8x4', '10x4']):
        return 'Extra-Grande'
    if any(s in m for s in ['vm', 'atego', 'constellation', 'cargo', 'tector', 'p3', 'g3', 'worker']):
        return 'Media'
    if any(s in m for s in ['delivery', 'accelo', 'daily', 'f-4000', '816', 'agrale']):
        return 'Pequena'
    return 'Outro'


def find_similar_recommended_model(predicted_label):
    if predicted_label is None or original_df is None:
        return None
    candidates = original_df['recommended_model'].dropna().unique().tolist()
    if not candidates:
        return None
    matches = difflib.get_close_matches(str(predicted_label), candidates, n=3, cutoff=0.45)
    if matches:
        return matches[0]
    token = str(predicted_label).split()[0]
    for c in candidates:
        if token.lower() in c.lower():
            return c
    return None


def get_catalog_info(recommended_model):
    if recommended_model is None or catalog_df is None:
        return {}
    df = catalog_df[catalog_df['recommended_model'] == recommended_model]
    if df.empty:
        return {}
    r = df.iloc[0]

    info = {}
    index_lower_map = {str(col).lower(): col for col in r.index}

    # preço
    for col in ['preco_estimado', 'preco']:
        if col in index_lower_map:
            try:
                info['price'] = float(r[index_lower_map[col]])
            except Exception:
                pass
            break

    # volume
    if 'volume_m3' in index_lower_map:
        try:
            info['volume_m3'] = float(r[index_lower_map['volume_m3']])
        except Exception:
            pass

    # tara da caçamba
    if 'tara_cacamba_kg' in index_lower_map:
        try:
            info['tara_cacamba_kg'] = float(r[index_lower_map['tara_cacamba_kg']])
        except Exception:
            pass

    # estoque base
    for col in ['estoque_inicial', 'estoque_disponivel', 'estoque']:
        if col in index_lower_map:
            try:
                info['stock_base'] = int(r[index_lower_map[col]])
            except Exception:
                pass
            break

    # imagem
    if 'imagem' in index_lower_map:
        info['image_file'] = str(r[index_lower_map['imagem']])

    return info


def check_stock_for_model(recommended_model):
    if recommended_model is None or not os.path.exists(PRODUCTION_ORDERS_PATH):
        return {"found": False, "matches": [], "qty": 0}
    df = pd.read_csv(PRODUCTION_ORDERS_PATH, dtype=str).fillna('')
    token = recommended_model.split()[0] if recommended_model else ''
    mask = df['Descricao'].str.contains(token, case=False, na=False)
    df_sel = df[mask & df['Status_Producao'].isin(['Em Produção', 'Aguardando Início'])]
    return {
        "found": not df_sel.empty,
        "matches": df_sel.to_dict(orient='records'),
        "qty": int(len(df_sel))
    }


def estimate_payload_kg(axle_count, truck_category, catalog_info, cargo_type=None):
    """
    Calcula capacidade estrutural x volume x densidade, e verifica se
    a combinação tende a respeitar PBT típico por eixo.
    """
    try:
        ax = int(axle_count)
    except Exception:
        ax = 3

    pbt = AXLE_TO_PBT.get(ax, AXLE_TO_PBT[max(AXLE_TO_PBT.keys())])
    tara_truck = AXLE_TO_TARA_TRUCK.get(ax, AXLE_TO_TARA_TRUCK[max(AXLE_TO_TARA_TRUCK.keys())])

    tara_cac = catalog_info.get('tara_cacamba_kg')
    if tara_cac is None:
        tara_cac = CATEGORY_TARA_CACAMBA.get(truck_category or '', 3500)

    capacity_structural = max(pbt - tara_truck - tara_cac, 0)

    volume_m3 = catalog_info.get('volume_m3')

    # densidade padrão (ton/m³) + ajuste pelo tipo de carga
    density_ton_m3 = 1.6
    cargo_norm = normalize_cargo_type(cargo_type) if cargo_type else None
    if cargo_norm in CARGO_TYPE_DENSITY:
        density_ton_m3 = CARGO_TYPE_DENSITY[cargo_norm]

    payload_by_volume_kg = None
    if volume_m3 is not None:
        payload_by_volume_kg = volume_m3 * density_ton_m3 * 1000.0

    if payload_by_volume_kg is not None:
        estimated_payload_kg = min(capacity_structural, payload_by_volume_kg)
    else:
        estimated_payload_kg = capacity_structural

    if payload_by_volume_kg is not None and payload_by_volume_kg > capacity_structural * 1.02:
        legal_ok = False
        legal_message = (
            "Se carregar todo o volume da caçamba com esse tipo de material, "
            "há risco de exceder o PBT típico para esse número de eixos. "
            "Recomenda-se limitar a carga ou avaliar outra opção."
        )
    else:
        legal_ok = True
        legal_message = (
            "Dentro da capacidade estimada do conjunto, considerando limites típicos de PBT por eixos."
        )

    return {
        "pbt_kg": float(pbt),
        "tara_truck_kg": float(tara_truck),
        "tara_cacamba_kg": float(tara_cac),
        "capacity_structural_kg": float(round(capacity_structural, 1)),
        "volume_m3": float(round(volume_m3, 2)) if volume_m3 is not None else None,
        "payload_by_volume_kg": float(round(payload_by_volume_kg, 1)) if payload_by_volume_kg is not None else None,
        "payload_kg": float(round(estimated_payload_kg, 1)),
        "legal_ok": bool(legal_ok),
        "legal_message": legal_message,
        "cargo_type": cargo_norm,
        "density_ton_m3": float(density_ton_m3)
    }

# --------------------------------------------------------------------
# HISTÓRICO / RESERVAS / EMAIL / CHAT CONFIRMATIONS
# --------------------------------------------------------------------
def log_acceptance(payload):
    header = [
        'ts', 'reservation_id', 'truck_model', 'axle_count', 'chassis_length_m',
        'recommended_model', 'predicted_category', 'user_name', 'user_email',
        'requested_qty', 'status'
    ]
    exists = os.path.exists(ACCEPT_LOG_PATH)
    with open(ACCEPT_LOG_PATH, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if not exists:
            writer.writerow(header)
        writer.writerow([
            datetime.datetime.utcnow().isoformat(),
            payload.get('reservation_id'),
            payload.get('truck_model'),
            payload.get('axle_count'),
            payload.get('chassis_length_m'),
            payload.get('recommended_model'),
            payload.get('predicted_category'),
            payload.get('user_name'),
            payload.get('user_email'),
            payload.get('requested_qty'),
            payload.get('status', 'pending')
        ])


def create_or_update_reservation(reservation_id, data_row, status):
    rows = []
    if os.path.exists(RESERVATIONS_PATH):
        with open(RESERVATIONS_PATH, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)

    found = False
    for r in rows:
        if r.get('reservation_id') == reservation_id:
            r.update(data_row)
            r['status'] = status
            found = True

    if not found:
        row = {'reservation_id': reservation_id, 'status': status}
        row.update(data_row)
        rows.append(row)

    fieldnames = sorted({k for r in rows for k in r.keys()})
    with open(RESERVATIONS_PATH, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def load_reservation(reservation_id):
    if not os.path.exists(RESERVATIONS_PATH):
        return None
    with open(RESERVATIONS_PATH, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for r in reader:
            if r.get('reservation_id') == reservation_id:
                return r
    return None


def update_client_history_on_accept(email, name, truck_model, recommended_model):
    if not email:
        return

    rows = []
    if os.path.exists(CLIENT_HISTORY_PATH):
        with open(CLIENT_HISTORY_PATH, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)

    record = None
    for r in rows:
        if r.get('email') == email:
            record = r
            break

    if record is None:
        record = {
            'email': email,
            'name': name or '',
            'total_requests': '0',
            'total_reservations': '0',
            'total_confirmed': '0',
            'last_truck_model': '',
            'last_recommended_model': '',
            'last_updated': ''
        }
        rows.append(record)

    record['name'] = name or record.get('name', '')
    record['total_requests'] = str(int(record.get('total_requests', 0)) + 1)
    record['total_reservations'] = str(int(record.get('total_reservations', 0)) + 1)
    record['last_truck_model'] = truck_model or record.get('last_truck_model', '')
    record['last_recommended_model'] = recommended_model or record.get('last_recommended_model', '')
    record['last_updated'] = datetime.datetime.utcnow().isoformat()

    fieldnames = sorted({k for r in rows for k in r.keys()})
    with open(CLIENT_HISTORY_PATH, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def update_client_history_on_confirm(email):
    if not email or not os.path.exists(CLIENT_HISTORY_PATH):
        return
    with open(CLIENT_HISTORY_PATH, 'r', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))

    for r in rows:
        if r.get('email') == email:
            r['total_confirmed'] = str(int(r.get('total_confirmed', 0)) + 1)
            r['last_updated'] = datetime.datetime.utcnow().isoformat()
            break

    fieldnames = sorted({k for r in rows for k in r.keys()})
    with open(CLIENT_HISTORY_PATH, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def send_email_with_optional_attachment(subject, html_body,
                                        to_list, cc_list=None,
                                        attachment_path=None):
    """
    Ainda usado para notificar o vendedor.
    """
    if not SMTP_USER or not SMTP_PASS:
        raise RuntimeError("SMTP_USER/SMTP_PASS não configurados nas variáveis de ambiente.")

    msg = MIMEMultipart()
    msg['From'] = EMAIL_FROM
    msg['To'] = ', '.join(to_list)
    if cc_list:
        msg['Cc'] = ', '.join(cc_list)
    msg['Subject'] = subject
    msg.attach(MIMEText(html_body, 'html'))

    if attachment_path and os.path.exists(attachment_path):
        try:
            with open(attachment_path, 'rb') as f:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(f.read())
            encoders.encode_base64(part)
            filename = os.path.basename(attachment_path)
            part.add_header('Content-Disposition', f'attachment; filename="{filename}"')
            msg.attach(part)
        except Exception:
            logging.exception("Falha ao anexar arquivo.")

    logging.info("Conectando ao SMTP %s:%s (user=%s)", SMTP_HOST, SMTP_PORT, SMTP_USER)
    server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30)
    try:
        if SMTP_USE_TLS:
            server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        dests = to_list + (cc_list or [])
        server.sendmail(EMAIL_FROM, dests, msg.as_string())
        logging.info("Email enviado com sucesso para: %s", dests)
    finally:
        server.quit()


# ---------------------- CHAT CONFIRMATIONS HELPERS -------------------
def append_chat_confirmation(email, name, recommended_model, truck_model,
                             requested_qty, scheduled_date, scheduled_time):
    """
    Gera uma mensagem bonitinha de confirmação e salva em CSV
    para ser lida pelo chat do cliente.
    """
    if not email:
        return

    exists = os.path.exists(CHAT_CONFIRMATIONS_PATH)
    with open(CHAT_CONFIRMATIONS_PATH, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if not exists:
            writer.writerow(['email', 'name', 'message', 'created_at'])

        msg = (
            f"Olá, {name or 'cliente'}! Sua reserva de "
            f"{requested_qty or 1}x {recommended_model} "
            f"para o caminhão {truck_model} foi confirmada para "
            f"{scheduled_date} às {scheduled_time}."
        )
        writer.writerow([
            email,
            name or '',
            msg,
            datetime.datetime.utcnow().isoformat()
        ])


def load_chat_confirmations(email):
    """
    Lê todas as confirmações registradas para um determinado e-mail.
    (Simples: não marca como 'lida', só devolve tudo.)
    """
    if not email or not os.path.exists(CHAT_CONFIRMATIONS_PATH):
        return []

    result = []
    with open(CHAT_CONFIRMATIONS_PATH, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('email') == email:
                result.append({
                    "message": row.get('message'),
                    "created_at": row.get('created_at'),
                })
    return result

# --------------------------------------------------------------------
# ROTAS API
# --------------------------------------------------------------------
@app.route('/api/health', methods=['GET'])
def health():
    ready = all([model is not None, label_encoder is not None, model_columns is not None])
    return jsonify({
        "status": "ok" if ready else "not_ready",
        "model_loaded": model is not None,
        "label_encoder_loaded": label_encoder is not None,
        "model_columns_loaded": model_columns is not None
    }), (200 if ready else 503)


@app.route('/api/truck_models', methods=['GET'])
def get_truck_models():
    if original_df is None:
        return jsonify({"error": "A lista de caminhões não está disponível."}), 500
    truck_list = sorted(original_df['truck_model'].dropna().unique().tolist())
    return jsonify(truck_list)


@app.route('/api/client_history', methods=['GET'])
def client_history():
    """
    Retorna o histórico do cliente + flag is_recurring
    para o front personalizar a saudação.
    """
    email = request.args.get('email')
    if not email:
        return jsonify({"error": "Parâmetro 'email' é obrigatório."}), 400

    if not os.path.exists(CLIENT_HISTORY_PATH):
        return jsonify({
            "email": email,
            "name": "",
            "total_requests": 0,
            "total_reservations": 0,
            "total_confirmed": 0,
            "last_truck_model": "",
            "last_recommended_model": "",
            "last_updated": None,
            "is_recurring": False
        })

    with open(CLIENT_HISTORY_PATH, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for r in reader:
            if r.get('email') == email:
                total_requests = int(r.get('total_requests', 0))
                return jsonify({
                    "email": r.get('email'),
                    "name": r.get('name'),
                    "total_requests": total_requests,
                    "total_reservations": int(r.get('total_reservations', 0)),
                    "total_confirmed": int(r.get('total_confirmed', 0)),
                    "last_truck_model": r.get('last_truck_model'),
                    "last_recommended_model": r.get('last_recommended_model'),
                    "last_updated": r.get('last_updated'),
                    "is_recurring": total_requests > 0
                })

    return jsonify({
        "email": email,
        "name": "",
        "total_requests": 0,
        "total_reservations": 0,
        "total_confirmed": 0,
        "last_truck_model": "",
        "last_recommended_model": "",
        "last_updated": None,
        "is_recurring": False
    })


@app.route('/api/production_orders', methods=['GET'])
def production_orders():
    if not os.path.exists(PRODUCTION_ORDERS_PATH):
        return jsonify({"error": "Arquivo de ordens não encontrado."}), 404
    df = pd.read_csv(PRODUCTION_ORDERS_PATH)
    status = request.args.get('status')
    if status:
        df = df[df['Status_Producao'] == status]
    return jsonify(df.to_dict(orient='records'))


@app.route('/api/recommend', methods=['POST'])
def recommend():
    if not all([model is not None, label_encoder is not None, model_columns is not None]):
        return jsonify({"error": "Sistema não está pronto. Verifique logs do servidor."}), 500

    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"error": "JSON inválido ou ausente."}), 400

    try:
        truck_model = data.get('truck_model')
        axle_count = int(data.get('axle_count'))
        chassis_length_m = float(str(data.get('chassis_length_m')).replace(',', '.'))
        requested_qty = int(data.get('quantity') or 1)
        if requested_qty < 1:
            requested_qty = 1

        cargo_type_raw = data.get('cargo_type')
        cargo_type_norm = normalize_cargo_type(cargo_type_raw) if cargo_type_raw else None

        input_df = pd.DataFrame({
            'truck_model': [truck_model],
            'axle_count': [axle_count],
            'chassis_length_m': [chassis_length_m]
        })
        input_df['truck_category'] = input_df['truck_model'].apply(get_truck_category)
        truck_category = input_df['truck_category'].iloc[0]

        processed_df = input_df.drop(columns=['truck_model'])
        input_encoded = pd.get_dummies(processed_df)
        input_aligned = input_encoded.reindex(columns=model_columns, fill_value=0)

        # probabilidades para top-2
        primary_category = secondary_category = None
        primary_conf = secondary_conf = None

        try:
            proba_arr = model.predict_proba(input_aligned)[0]
            class_indices = np.arange(len(proba_arr))
            labels = label_encoder.inverse_transform(class_indices)
            sorted_idx = np.argsort(proba_arr)[::-1]
            top1_idx = sorted_idx[0]
            top2_idx = sorted_idx[1] if len(sorted_idx) > 1 else sorted_idx[0]

            primary_category = labels[top1_idx]
            secondary_category = labels[top2_idx]
            primary_conf = float(proba_arr[top1_idx])
            secondary_conf = float(proba_arr[top2_idx])
        except Exception:
            prediction_encoded = model.predict(input_aligned)
            primary_category = label_encoder.inverse_transform(prediction_encoded)[0]

        def resolve_model(category_label):
            if category_label is None:
                return None
            key = normalize_category_key(category_label)
            model_name = CATEGORY_TO_MODEL_MAP.get(key) or CATEGORY_TO_MODEL_MAP.get(category_label)
            if not model_name:
                model_name = find_similar_recommended_model(category_label)
            return model_name or 'Consultar Engenharia'

        primary_model = resolve_model(primary_category)
        secondary_model = resolve_model(secondary_category) if secondary_category else None

        catalog_info = get_catalog_info(primary_model)
        stock_info = check_stock_for_model(primary_model)
        payload_info = estimate_payload_kg(
            axle_count=axle_count,
            truck_category=truck_category,
            catalog_info=catalog_info or {},
            cargo_type=cargo_type_norm
        )

        price = catalog_info.get('price')
        base_stock = catalog_info.get('stock_base', 0)
        prod_qty = stock_info.get('qty', 0)
        total_stock = base_stock + prod_qty
        enough_stock = total_stock >= requested_qty

        # URL da imagem (sempre monta e loga caminho)
        image_url = None
        image_file = catalog_info.get('image_file')
        if image_file:
            image_path_full = os.path.join(STATIC_IMAGES_DIR, image_file)
            logging.info("Buscando imagem da caçamba em: %s", image_path_full)
            image_url = f"{CONFIRM_BASE_URL}/static/images/{image_file}"

        # flatten de payload para o front
        estimated_payload_kg = payload_info.get('payload_kg')
        legal_ok = payload_info.get('legal_ok')
        legal_message = payload_info.get('legal_message')

        # Segunda opção
        alt_payload_info = None
        alt_block = None
        comparison = None

        if secondary_model and secondary_category and secondary_conf is not None and primary_conf is not None:
            diff = primary_conf - secondary_conf
            if diff < 0.05:
                reason = "Quase empatou com a primeira opção, mas a principal tem um ajuste levemente melhor para esse chassi."
            elif diff < 0.15:
                reason = "Também serviria, porém a principal apresenta combinação mais equilibrada entre capacidade e peso bruto."
            else:
                reason = "Mais genérica; a principal foi considerada tecnicamente mais adequada para este caminhão."

            alt_catalog_info = get_catalog_info(secondary_model)
            if alt_catalog_info:
                alt_payload_info = estimate_payload_kg(
                    axle_count=axle_count,
                    truck_category=truck_category,
                    catalog_info=alt_catalog_info,
                    cargo_type=cargo_type_norm
                )

            alt_block = {
                "category": str(secondary_category),
                "recommended_model": secondary_model,
                "confidence": round(secondary_conf, 3) if secondary_conf is not None else None,
                "reason": reason
            }

        if payload_info and alt_payload_info:
            p1 = payload_info.get('payload_kg') or 0
            p2 = alt_payload_info.get('payload_kg') or 0
            if p1 > p2:
                better = primary_model
                text = "A opção principal oferece maior carga útil estimada."
            elif p2 > p1:
                better = secondary_model
                text = "A segunda opção oferece maior carga útil estimada; pode ser interessante se o foco for volume/peso."
            else:
                better = None
                text = "As duas opções têm carga útil estimada muito parecida; a escolha pode ser por prazo, preço ou preferência."

            comparison = {
                "primary_model": primary_model,
                "secondary_model": secondary_model,
                "primary_payload_kg": p1,
                "secondary_payload_kg": p2,
                "better_model": better,
                "summary": text
            }

        if alt_block and alt_payload_info:
            alt_block["estimated_payload_kg"] = alt_payload_info.get('payload_kg')
            if comparison:
                alt_block["comparison"] = comparison.get('summary')

        # ---------------- EXPLICAÇÃO TÉCNICA RESUMIDA ----------------
        tech_lines = []

        tech_lines.append(
            f"O caminhão '{truck_model}' foi classificado como categoria '{truck_category}'."
        )
        tech_lines.append(
            f"Para {axle_count} eixos, considerou-se um PBT típico de {payload_info['pbt_kg']/1000:.1f} t "
            f"e tara do caminhão de {payload_info['tara_truck_kg']/1000:.1f} t."
        )

        if payload_info.get('volume_m3') is not None:
            dens = payload_info.get('density_ton_m3', 1.6)
            cargo_txt = payload_info.get('cargo_type') or 'desconhecida'
            tech_lines.append(
                f"A caçamba possui cerca de {payload_info['volume_m3']:.1f} m³. "
                f"Para carga do tipo '{cargo_txt}', foi adotada densidade aproximada de {dens:.2f} t/m³ "
                f"para estimar a carga útil por volume."
            )

        if estimated_payload_kg:
            tech_lines.append(
                f"A carga útil estimada para essa combinação fica em torno de "
                f"{estimated_payload_kg/1000:.1f} t por viagem."
            )

        if total_stock > 0:
            tech_lines.append(
                f"Há estimativa de {total_stock} unidade(s) disponíveis entre estoque e produção."
            )
        else:
            tech_lines.append(
                "Não há unidades prontas; será necessário programar produção."
            )

        if comparison and comparison.get('better_model') == primary_model:
            tech_lines.append(
                "Entre as duas opções, esta apresenta melhor aproveitamento de carga útil estimada."
            )
        elif comparison and comparison.get('better_model') == secondary_model:
            tech_lines.append(
                "A segunda opção apresenta ligeira vantagem em carga útil; "
                "a escolha pode considerar preferência de modelo, prazo ou custo."
            )

        if legal_message:
            tech_lines.append(f"Avaliação de peso / legislação: {legal_message}")

        technical_explanation = " ".join(tech_lines)

        return jsonify({
            "predicted_category": str(primary_category),
            "recommended_model": primary_model,
            "confidence": round(primary_conf, 3) if primary_conf is not None else None,
            "image_url": image_url,
            "price": price,
            "stock_qty": int(total_stock),
            "in_stock": bool(total_stock > 0),
            "stock_from_orders": prod_qty,
            "payload_info": payload_info,
            "estimated_payload_kg": estimated_payload_kg,
            "legal_ok": legal_ok,
            "legal_message": legal_message,
            "alternative": alt_block,
            "comparison": comparison,
            "requested_qty": requested_qty,
            "enough_stock": enough_stock,
            "cargo_type_used": payload_info.get("cargo_type"),
            "density_ton_m3_used": payload_info.get("density_ton_m3"),
            "technical_explanation": technical_explanation
        })

    except Exception as e:
        logging.exception("Erro no processamento da recomendação")
        return jsonify({"error": f"Erro no processamento: {str(e)}"}), 400


# upload de imagem
@app.route('/api/upload_image', methods=['POST'])
def upload_image():
    if 'file' not in request.files:
        return jsonify({"error": "Nenhum arquivo recebido."}), 400
    f = request.files['file']
    filename = slugify(f.filename)
    if not filename:
        return jsonify({"error": "Nome de arquivo inválido."}), 400
    save_path = os.path.join(STATIC_IMAGES_DIR, filename)
    f.save(save_path)
    url = f"{CONFIRM_BASE_URL}/static/images/{filename}"
    return jsonify({"status": "ok", "image_url": url, "path": save_path, "filename": filename})


@app.route('/static/images/<path:filename>', methods=['GET'])
def serve_image(filename):
    return send_from_directory(STATIC_IMAGES_DIR, filename)


# --- DEMO: reconhecimento de caminhão pela imagem -------------------
@app.route('/api/detect_truck_from_image', methods=['POST'])
def detect_truck_from_image():
    """
    Protótipo simples de visão:
    Para a apresentação, vamos assumir que qualquer imagem enviada
    é o caminhão Agrale 8.5 (3 eixos) usado no demo.
    """
    data = request.get_json(force=True, silent=True) or {}
    image_name = data.get('filename') or ''
    image_url = data.get('image_url') or ''

    detected = {
        "truck_model": "Agrale 8.5 (baú)",
        "axle_count": 3,
        "chassis_length_m": 5.5,
        "suggested_cargo_type": "areia",
        "image_url": image_url,
        "filename": image_name
    }
    return jsonify(detected)


# usuário aceitou a recomendação -> notificar vendedor
@app.route('/api/accept_recommendation', methods=['POST'])
def accept_recommendation():
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"error": "JSON inválido"}), 400

    truck_model = data.get('truck_model')
    axle_count = data.get('axle_count')
    chassis_length_m = data.get('chassis_length_m')
    recommended_model = data.get('recommended_model')
    predicted_category = data.get('predicted_category')
    confidence = data.get('confidence')
    user_name = data.get('user_name', 'Cliente')
    user_email = data.get('user_email')
    requested_qty = int(data.get('quantity') or 1)
    image_path = data.get('image_path')

    stock = check_stock_for_model(recommended_model)
    in_stock = stock['found']
    stock_matches = stock['matches']
    qty_from_orders = stock.get('qty', 0)

    availability_text = "Disponível em estoque" if in_stock else "Não disponível em estoque"
    if qty_from_orders:
        availability_text += f" — {qty_from_orders} unidade(s) em produção/estoque"

    reservation_id = uuid4().hex[:10]
    confirm_link = f"{CONFIRM_BASE_URL}/api/confirm_reservation?reservation_id={reservation_id}"

    email_subject = f"Nova solicitação — {requested_qty}x {recommended_model} para {truck_model}"
    email_body = f"""
    <p>Olá,</p>
    <p>O usuário <strong>{user_name}</strong> ({user_email or 'sem e-mail'}) aceitou a recomendação.</p>
    <h4>Dados do pedido</h4>
    <ul>
      <li><b>Caminhão:</b> {truck_model}</li>
      <li><b>Eixos:</b> {axle_count}</li>
      <li><b>Chassi (m):</b> {chassis_length_m}</li>
      <li><b>Quantidade desejada:</b> {requested_qty} caçamba(s)</li>
      <li><b>Recomendação:</b> {recommended_model} (categoria: {predicted_category})</li>
      <li><b>Confiança do modelo:</b> {confidence}</li>
      <li><b>Disponibilidade:</b> {availability_text}</li>
    </ul>
    <p><b>Ordens/entradas encontradas (amostra):</b></p>
    <pre>{stock_matches[:5]}</pre>
    <p>
      Para <b>confirmar a reserva e agendar data/horário</b>, clique no link abaixo:<br/>
      <a href="{confirm_link}">Confirmar reserva</a>
    </p>
    <p>Atenciosamente,<br/>Sistema GALEGO Fit</p>
    """

    to_list = [e.strip() for e in SALES_EMAILS.split(',') if e.strip()]
    cc_list = [user_email] if user_email else []

    reservation_data = {
        "truck_model": truck_model,
        "axle_count": axle_count,
        "chassis_length_m": chassis_length_m,
        "recommended_model": recommended_model,
        "predicted_category": predicted_category,
        "confidence": confidence,
        "user_name": user_name,
        "user_email": user_email,
        "requested_qty": requested_qty,
        "qty_from_orders": qty_from_orders
    }

    try:
        create_or_update_reservation(reservation_id, reservation_data, status="pending")
        log_acceptance({
            "reservation_id": reservation_id,
            "truck_model": truck_model,
            "axle_count": axle_count,
            "chassis_length_m": chassis_length_m,
            "recommended_model": recommended_model,
            "predicted_category": predicted_category,
            "user_name": user_name,
            "user_email": user_email,
            "requested_qty": requested_qty,
            "status": "pending"
        })
        update_client_history_on_accept(
            email=user_email,
            name=user_name,
            truck_model=truck_model,
            recommended_model=recommended_model
        )
    except Exception:
        logging.exception("Falha ao gravar reserva / log / histórico de cliente.")

    try:
        send_email_with_optional_attachment(
            email_subject,
            email_body,
            to_list,
            cc_list=cc_list,
            attachment_path=image_path
        )
    except Exception as e:
        logging.exception("Erro ao enviar e-mail para vendedor")
        return jsonify({"error": f"Falha ao enviar e-mail: {str(e)}"}), 500

    return jsonify({
        "status": "ok",
        "reservation_id": reservation_id,
        "in_stock": in_stock,
        "matches_count": len(stock_matches)
    }), 200


# fornecedor clicou no link de confirmação -> tela com data/horário
@app.route('/api/confirm_reservation', methods=['GET', 'POST'])
def confirm_reservation():
    reservation_id = request.values.get('reservation_id')
    if not reservation_id:
        return "Parâmetro 'reservation_id' ausente.", 400

    res = load_reservation(reservation_id)
    if not res:
        return f"Reserva {reservation_id} não encontrada.", 404

    # GET -> mostra formulário de agendamento
    if request.method == 'GET':
        ag_data = res.get('scheduled_date')
        ag_hora = res.get('scheduled_time')
        if res.get('status') == 'confirmed' and ag_data and ag_hora:
            return f"""
            <html>
              <body style="font-family: Arial, sans-serif;">
                <h3>Reserva {reservation_id} já confirmada.</h3>
                <p>Agendada para <b>{ag_data}</b> às <b>{ag_hora}</b>.</p>
                <p>O cliente já vê essa confirmação diretamente no chat do GALEGO Fit.</p>
              </body>
            </html>
            """, 200

        return f"""
        <html>
          <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 30px auto;">
            <h2>Confirmar reserva #{reservation_id}</h2>
            <p>
              Cliente: <b>{res.get('user_name') or 'cliente'}</b> ({res.get('user_email') or 'sem e-mail'})<br/>
              Caminhão: <b>{res.get('truck_model')}</b> — {res.get('axle_count')} eixos, chassi {res.get('chassis_length_m')} m<br/>
              Caçamba: <b>{res.get('recommended_model')}</b> (categoria: {res.get('predicted_category')})<br/>
              Quantidade solicitada: <b>{res.get('requested_qty') or 1}</b> unidade(s)
            </p>
            <form method="POST" action="/api/confirm_reservation">
              <input type="hidden" name="reservation_id" value="{reservation_id}" />
              <label>Data do agendamento:</label><br/>
              <input type="date" name="scheduled_date" required style="margin: 4px 0 10px 0;"/><br/>
              <label>Horário:</label><br/>
              <input type="time" name="scheduled_time" required style="margin: 4px 0 10px 0;"/><br/>
              <label>Observações internas (opcional):</label><br/>
              <textarea name="internal_notes" rows="3" style="width: 100%; margin: 4px 0 10px 0;"></textarea><br/>
              <button type="submit" style="
                padding: 8px 16px;
                background: #28a745;
                color: white;
                border: none;
                border-radius: 4px;
                cursor: pointer;">
                Confirmar reserva e registrar no chat do cliente
              </button>
            </form>
          </body>
        </html>
        """, 200

    # POST -> grava data/hora e REGISTRA CONFIRMAÇÃO PARA O CHAT
    scheduled_date = request.form.get('scheduled_date')
    scheduled_time = request.form.get('scheduled_time')
    internal_notes = request.form.get('internal_notes', '')

    if not scheduled_date or not scheduled_time:
        return """
        <html>
          <body style="font-family: Arial, sans-serif;">
            <h3>Data e horário são obrigatórios.</h3>
            <p>Volte e preencha os campos.</p>
          </body>
        </html>
        """, 400

    res['scheduled_date'] = scheduled_date
    res['scheduled_time'] = scheduled_time
    res['internal_notes'] = internal_notes

    try:
        create_or_update_reservation(reservation_id, res, status="confirmed")
    except Exception:
        logging.exception("Falha ao atualizar status da reserva.")

    user_email = res.get('user_email')
    if user_email:
        try:
            append_chat_confirmation(
                email=user_email,
                name=res.get('user_name'),
                recommended_model=res.get('recommended_model'),
                truck_model=res.get('truck_model'),
                requested_qty=res.get('requested_qty'),
                scheduled_date=scheduled_date,
                scheduled_time=scheduled_time
            )
            update_client_history_on_confirm(user_email)
        except Exception:
            logging.exception(
                "Falha ao gravar confirmação para o chat / atualizar histórico."
            )

    return f"""
    <html>
      <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 30px auto;">
        <h3>Reserva confirmada com sucesso.</h3>
        <p>
          Agendada para <b>{scheduled_date}</b> às <b>{scheduled_time}</b>.<br/>
          O cliente verá essa confirmação diretamente no chat do GALEGO Fit.
        </p>
      </body>
    </html>
    """, 200


# --------------------------------------------------
# ROTA PARA O CHAT BUSCAR CONFIRMAÇÕES
# --------------------------------------------------
@app.route('/api/chat_confirmations', methods=['GET'])
def chat_confirmations():
    """
    Front do chat chama isso passando ?email=...
    e recebe uma lista de mensagens de confirmação.
    """
    email = request.args.get('email')
    if not email:
        return jsonify({"error": "Parâmetro 'email' é obrigatório."}), 400

    confirmations = load_chat_confirmations(email)
    return jsonify(confirmations)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)