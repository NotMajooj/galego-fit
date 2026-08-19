```
# GALEGO Fit — Protótipo


## Requisitos
- Python 3.9+
- Node.js 18+ (npm)


## Preparar backend
1. Abra um terminal em `backend/`
2. (opcional) crie um ambiente virtual: python -m venv venv && source venv/bin/activate
3. pip install -r requirements.txt
4. python train_model.py # treina o modelo e gera model.joblib com dataset de exemplo
5. flask run --host=0.0.0.0 --port=5000


## Preparar frontend
1. Abra outro terminal em `frontend/`
2. npm install
3. npm start


O frontend assume que a API está em http://localhost:5000. Se você rodar a API em outra porta, ajuste a URL em src/components/ConfigForm.jsx


---


Observações:
- Os dados de exemplo são mínimos; para uso real você deve usar o histórico de vendas e a tabela de compatibilidades da GALEGO.
- Melhorias sugeridas: adicionar painel admin para editar regras, fotos e fichas técnicas, exportar PDF com orçamento, reconhecimento automático de modelo por imagem.
```
