// chat.jsx - GALEGO Fit 2.5 (visão + explicação técnica + carga + histórico amigável)

import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';

// === CONFIGURAÇÕES ===
const API_KEY = process.env.REACT_APP_GEMINI_API_KEY;
const GEMINI_API_URL =
  `https://generativelanguage.googleapis.com/v1/models/gemini-2.5-flash:generateContent?key=${API_KEY}`;

const BACKEND_API_URL = 'http://localhost:5000/api';

// Agente agora coleta 5 infos e devolve:
// RECOMENDAR:[MODELO],[EIXOS],[CHASSI],[QTD],[CARGA]
const systemPrompt = [
  {
    role: 'user',
    parts: [
      {
        text: `INSTRUÇÃO IMPORTANTE: Você é um assistente especialista e amigável da GALEGO Implementos.
        Seja BREVE, DIRETO e prestativo. NÃO use um nome próprio para se apresentar.
        
        Objetivo principal: coletar 5 informações, sempre uma de cada vez:
        1) Modelo do caminhão
        2) Número de eixos
        3) Comprimento do chassi (em metros)
        4) Quantas caçambas o cliente deseja (inteiro, ex: 1, 2, 5...)
        5) Tipo principal de carga (ex.: grãos, areia, brita, terra, entulho leve, entulho pesado, sucata, outro)

        Quando você tiver algum contexto de histórico do cliente, siga estas regras:
        - Se for primeiro atendimento (total_requests = 0), faça uma saudação curta de boas-vindas.
        - Se houver histórico (total_requests > 0), cumprimente como cliente recorrente, diga que é bom tê-lo de volta
          e mencione, de forma breve, o último caminhão e a última caçamba utilizados, se essas informações existirem.
        - Você pode perguntar se o cliente deseja “refazer a última compra” ou repetir aquela configuração como ponto de partida,
          mas AINDA ASSIM deve confirmar claramente as 5 informações (modelo, eixos, chassi, quantidade, tipo de carga).
        
        Fluxo de coleta (sempre manter):
        - Comece perguntando SÓ o modelo do caminhão.
        - Depois pergunte SÓ os eixos.
        - Depois pergunte SÓ o comprimento de chassi.
        - Depois pergunte SÓ quantas caçambas ele deseja.
        - Por fim, pergunte SÓ o tipo principal de carga.

        Quando tiver TUDO, responda APENAS com:
        RECOMENDAR:[MODELO],[EIXOS],[CHASSI],[QTD],[CARGA]
        
        Importante:
        - Use respostas curtas, em tom profissional mas simples.
        - Se o usuário fugir do assunto (futebol, etc.), explique educadamente que você só pode ajudar na escolha de caçambas.`
      }
    ]
  }
];

// Dataset fake de últimas compras (pra simular cliente recorrente)
const MOCK_PURCHASES = [
  {
    email: 'cliente.exemplo@galego.com',
    data: '2025-09-10',
    truck_model: 'Agrale 8700 4x2',
    axle_count: 2,
    chassis_length_m: 5.9,
    caçamba: 'Caçamba-A09 (Pequena Reforçada)',
    status: 'Confirmada'
  },
  {
    email: 'cliente.exemplo@galego.com',
    data: '2025-10-02',
    truck_model: 'Agrale 14000 6x2',
    axle_count: 3,
    chassis_length_m: 8.3,
    caçamba: 'Caçamba-B15 (Média)',
    status: 'Confirmada'
  },
  {
    email: 'cliente.exemplo@galego.com',
    data: '2025-11-15',
    truck_model: 'VW Constellation 24.280',
    axle_count: 3,
    chassis_length_m: 8.8,
    caçamba: 'Caçamba-B16 (Média Reforçada)',
    status: 'Reservada'
  }
];

export default function Chat() {
  const [message, setMessage] = useState('');
  const [chatHistory, setChatHistory] = useState([]);
  const [loading, setLoading] = useState(false);

  const [truckModels, setTruckModels] = useState([]);

  const [activeTab, setActiveTab] = useState('chat');

  const [userName, setUserName] = useState('Cliente Exemplo');
  const [userEmail, setUserEmail] = useState('cliente.exemplo@galego.com');

  const [clientHistory, setClientHistory] = useState(null);
  const [loadingHistory, setLoadingHistory] = useState(false);

  const [lastRecommendation, setLastRecommendation] = useState(null);
  const [notifyLoading, setNotifyLoading] = useState(false);

  // confirmações do backend já mostradas
  const confirmationKeysRef = useRef(new Set());

  // VISÃO
  const [imageUploading, setImageUploading] = useState(false);
  const [imageRecognition, setImageRecognition] = useState(null);

  // --------------------------------------------------
  // Carrega lista de modelos do backend (opcional)
  // --------------------------------------------------
  useEffect(() => {
    axios
      .get(`${BACKEND_API_URL}/truck_models`)
      .then((response) => setTruckModels(response.data || []))
      .catch((error) => console.error('Erro ao buscar modelos do app.py', error));
  }, []);

  // --------------------------------------------------
  // Histórico do cliente + mensagem personalizada
  // --------------------------------------------------
  const handleLoadHistory = async () => {
    if (!userEmail) {
      alert('Informe um e-mail para carregar o histórico do cliente.');
      return;
    }
    setLoadingHistory(true);
    try {
      const response = await axios.get(`${BACKEND_API_URL}/client_history`, {
        params: { email: userEmail }
      });
      const h = response.data;
      setClientHistory(h);

      let txt = '';

      if (h && h.is_recurring) {
        // Cliente que já passou pelo sistema
        txt = `Que bom ter você de volta, ${h.name || 'cliente'}! `;

        if (h.last_truck_model || h.last_recommended_model) {
          txt += `Na última vez, usamos o caminhão "${h.last_truck_model ||
            'não informado'}" com a caçamba "${h.last_recommended_model ||
            'não informada'}". `;
        }

        txt +=
          'Se quiser, podemos usar essa mesma combinação como ponto de partida: é só dizer que deseja "refazer a última compra" ou que quer a mesma caçamba. Caso prefira, montamos uma nova configuração do zero.';

      } else {
        // Primeiro atendimento
        txt = `Olá, ${h?.name || userName || 'cliente'}! Parece ser o seu primeiro atendimento aqui no GALEGO Fit. ` +
          'Vou te ajudar a escolher a caçamba ideal para o seu caminhão. Vamos começar informando o modelo do caminhão?';
      }

      setChatHistory((prev) => [
        ...prev,
        {
          role: 'model',
          text: txt
        }
      ]);
    } catch (err) {
      console.error('Erro ao buscar histórico do cliente:', err);
      setClientHistory(null);
    } finally {
      setLoadingHistory(false);
    }
  };

  const filteredMockPurchases = MOCK_PURCHASES.filter(
    (p) => p.email.toLowerCase() === (userEmail || '').toLowerCase()
  );

  // --------------------------------------------------
  // BUSCA CONFIRMAÇÕES DO BACKEND E JOGA NO CHAT
  // --------------------------------------------------
  useEffect(() => {
    if (!userEmail) return;

    const fetchConfirmations = async () => {
      try {
        const resp = await axios.get(
          `${BACKEND_API_URL}/chat_confirmations`,
          { params: { email: userEmail } }
        );
        const items = resp.data || [];

        items.forEach((item) => {
          const key = `${item.created_at}::${item.message}`;
          if (!confirmationKeysRef.current.has(key)) {
            confirmationKeysRef.current.add(key);
            const aiMessage = {
              role: 'model',
              text: item.message
            };
            setChatHistory((prev) => [...prev, aiMessage]);
          }
        });
      } catch (err) {
        console.error(
          'Erro ao buscar confirmações para o chat:',
          err.response?.data || err.message
        );
      }
    };

    fetchConfirmations();
    const intervalId = setInterval(fetchConfirmations, 10000);
    return () => clearInterval(intervalId);
  }, [userEmail]);

  // --------------------------------------------------
  // Função auxiliar: roda /api/recommend
  // --------------------------------------------------
  const runRecommendation = async ({
    truck_model,
    axle_count,
    chassis_length_m,
    quantity,
    cargo_type,
    prefixText
  }) => {
    const recommendationData = {
      truck_model,
      axle_count,
      chassis_length_m,
      quantity,
      cargo_type
    };

    try {
      const recResponse = await axios.post(
        `${BACKEND_API_URL}/recommend`,
        recommendationData
      );

      const {
        predicted_category,
        recommended_model,
        confidence,
        image_url,
        price,
        stock_qty,
        in_stock,
        stock_from_orders,
        estimated_payload_kg,
        legal_ok,
        legal_message,
        alternative,
        requested_qty,
        enough_stock,
        cargo_type_used,
        density_ton_m3_used,
        technical_explanation
      } = recResponse.data;

      const baseText =
        prefixText ||
        `Perfeito — para ${truck_model} com ${axle_count} eixos, chassi de ${chassis_length_m}m, carga principal "${cargo_type || 'não informada'}" e pedido de ${requested_qty} caçamba(s), nossa recomendação técnica principal é: ${recommended_model}.`;

      const meta = {
        truck_model,
        axle_count,
        chassis_length_m,
        predicted_category,
        recommended_model,
        confidence,
        image_url,
        price,
        stock_qty,
        in_stock,
        stock_from_orders,
        estimated_payload_kg,
        legal_ok,
        legal_message,
        alternative,
        requested_qty,
        enough_stock,
        cargo_type_used,
        density_ton_m3_used,
        technical_explanation
      };

      const aiMessage = { role: 'model', text: baseText, meta };
      setChatHistory((prev) => [...prev, aiMessage]);
      setLastRecommendation(meta);
    } catch (backendError) {
      console.error(
        'Erro ao chamar o backend /recommend:',
        backendError.response?.data || backendError.message
      );
      const aiMessage = {
        role: 'model',
        text: 'Puxa, não consegui contatar nosso engenheiro (backend). Verifique se o servidor está online.'
      };
      setChatHistory((prev) => [...prev, aiMessage]);
    }
  };

  // --------------------------------------------------
  // ENVIO DE MENSAGEM (texto -> Gemini -> backend)
  // --------------------------------------------------
  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!message.trim()) return;

    const userMessage = { role: 'user', text: message };
    const newUiHistory = [...chatHistory, userMessage];
    setChatHistory(newUiHistory);
    setMessage('');
    setLoading(true);

    // Se o usuário claramente pedir para "refazer a última compra",
    // podemos só deixar o Gemini lidar com isso com base no contexto,
    // então não fazemos nada especial aqui além de passar o histórico.

    const apiHistory = newUiHistory.map((msg) => ({
      role: msg.role === 'user' ? 'user' : 'model',
      parts: [{ text: msg.text }]
    }));

    const historyContext = clientHistory
      ? `Contexto do cliente (NÃO leia literalmente): total de atendimentos = ${clientHistory.total_requests}, ` +
        `reservas geradas = ${clientHistory.total_reservations}, ` +
        `compras confirmadas = ${clientHistory.total_confirmed}. ` +
        (clientHistory.last_truck_model
          ? `Último caminhão atendido: ${clientHistory.last_truck_model}. `
          : '') +
        (clientHistory.last_recommended_model
          ? `Última caçamba recomendada: ${clientHistory.last_recommended_model}. `
          : '') +
        `Se total_requests = 0, trate como primeiro atendimento (boas-vindas rápidas).
         Se total_requests > 0, trate como cliente recorrente, diga que é bom tê-lo de volta
         e ofereça repetir a última combinação como ponto de partida, sempre confirmando as 5 informações
         antes de emitir o comando RECOMENDAR:[...].`
      : null;

    const extraContext = historyContext
      ? [
          {
            role: 'user',
            parts: [{ text: historyContext }]
          }
        ]
      : [];

    const requestBody = {
      contents: [...systemPrompt, ...extraContext, ...apiHistory]
    };

    try {
      const response = await axios.post(GEMINI_API_URL, requestBody, {
        headers: { 'Content-Type': 'application/json' }
      });

      let aiText =
        response.data?.candidates?.[0]?.content?.parts?.[0]?.text ||
        'Desculpe, não entendi.';

      // Se o agente terminou a coleta e mandou RECOMENDAR
      if (aiText.startsWith('RECOMENDAR:')) {
        const parts = aiText.replace('RECOMENDAR:', '').split(',');
        const [modelRaw, axlesRaw, chassisRaw, qtyRaw, cargoRaw] = parts.map((p) =>
          p ? p.trim() : ''
        );

        const axleParsed = parseInt(axlesRaw, 10);
        const chassisParsed = parseFloat(chassisRaw.replace(',', '.'));
        let quantityParsed = parseInt(qtyRaw, 10);
        if (Number.isNaN(quantityParsed) || quantityParsed < 1) {
          quantityParsed = 1;
        }
        const cargoType = cargoRaw || '';

        await runRecommendation({
          truck_model: modelRaw,
          axle_count: axleParsed,
          chassis_length_m: chassisParsed,
          quantity: quantityParsed,
          cargo_type: cargoType
        });

        setLoading(false);
        return;
      }

      const aiMessage = { role: 'model', text: aiText };
      setChatHistory((prev) => [...prev, aiMessage]);
    } catch (error) {
      console.error(
        'Erro ao chamar a API Gemini:',
        error.response?.data || error.message
      );
      const errorMessage = {
        role: 'model',
        text: 'Desculpe, não consegui me conectar ao serviço de linguagem.'
      };
      setChatHistory((prev) => [...prev, errorMessage]);
    } finally {
      setLoading(false);
    }
  };

  // --------------------------------------------------
  // VISÃO: upload -> /upload_image -> /detect_truck_from_image
  // --------------------------------------------------
  const handleImageChange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    setImageUploading(true);
    try {
      // 1) sobe a imagem pro backend
      const formData = new FormData();
      formData.append('file', file);

      const uploadResp = await axios.post(
        `${BACKEND_API_URL}/upload_image`,
        formData,
        {
          headers: { 'Content-Type': 'multipart/form-data' }
        }
      );

      const { image_url, filename } = uploadResp.data;

      // 2) chama o "modelo de visão" demo
      const detectResp = await axios.post(
        `${BACKEND_API_URL}/detect_truck_from_image`,
        { image_url, filename }
      );

      const data = detectResp.data;
      setImageRecognition(data);

      const prefixText =
        'Usei a imagem enviada para identificar o caminhão. Com base nela, segue a recomendação:';

      await runRecommendation({
        truck_model: data.truck_model,
        axle_count: data.axle_count,
        chassis_length_m: data.chassis_length_m,
        quantity: 1,
        cargo_type: data.suggested_cargo_type,
        prefixText
      });

      setChatHistory((prev) => [
        ...prev,
        {
          role: 'model',
          text: `Imagem reconhecida como ${data.truck_model} com ${data.axle_count} eixos, chassi de ${data.chassis_length_m}m e carga principal "${data.suggested_cargo_type}".`
        }
      ]);
    } catch (err) {
      console.error(
        'Erro ao reconhecer caminhão pela imagem:',
        err.response?.data || err.message
      );
      setChatHistory((prev) => [
        ...prev,
        {
          role: 'model',
          text: 'Não consegui processar a imagem enviada. Tente novamente ou informe os dados manualmente.'
        }
      ]);
    } finally {
      setImageUploading(false);
      e.target.value = '';
    }
  };

  // --------------------------------------------------
  // NOTIFICAR VENDEDOR
  // --------------------------------------------------
  const handleNotifyVendor = async () => {
    if (!lastRecommendation) {
      alert('Nenhuma recomendação disponível ainda.');
      return;
    }
    setNotifyLoading(true);
    try {
      const payload = {
        truck_model: lastRecommendation.truck_model,
        axle_count: lastRecommendation.axle_count,
        chassis_length_m: lastRecommendation.chassis_length_m,
        recommended_model: lastRecommendation.recommended_model,
        predicted_category: lastRecommendation.predicted_category,
        confidence: lastRecommendation.confidence,
        user_name: userName || 'Cliente',
        user_email: userEmail || '',
        quantity: lastRecommendation.requested_qty || 1,
        image_path: null
      };

      const resp = await axios.post(
        `${BACKEND_API_URL}/accept_recommendation`,
        payload
      );
      const { reservation_id } = resp.data || {};

      const confirmationText = reservation_id
        ? `Notificação enviada ao vendedor! Código de reserva: ${reservation_id}.`
        : 'Notificação enviada ao vendedor com sucesso!';

      const aiMessage = { role: 'model', text: confirmationText };
      setChatHistory((prev) => [...prev, aiMessage]);
    } catch (err) {
      console.error(
        'Erro ao notificar vendedor:',
        err.response?.data || err.message
      );
      const aiMessage = {
        role: 'model',
        text: 'Não consegui enviar a notificação ao vendedor. Verifique o backend / SMTP.'
      };
      setChatHistory((prev) => [...prev, aiMessage]);
    } finally {
      setNotifyLoading(false);
    }
  };

  // --------------------------------------------------
  // CARD DE RECOMENDAÇÃO
  // --------------------------------------------------
  const renderRecommendationCard = (meta) => {
    if (!meta) return null;

    const {
      recommended_model,
      predicted_category,
      confidence,
      image_url,
      price,
      stock_qty,
      in_stock,
      estimated_payload_kg,
      legal_ok,
      legal_message,
      alternative,
      requested_qty,
      enough_stock,
      cargo_type_used,
      density_ton_m3_used,
      technical_explanation
    } = meta;

    return (
      <div
        style={{
          marginTop: 8,
          padding: 10,
          borderRadius: 10,
          background: '#ffffff',
          boxShadow: '0 1px 4px rgba(0,0,0,0.08)',
          fontSize: 13,
          maxWidth: 380
        }}
      >
        <div style={{ display: 'flex', gap: 8 }}>
          {image_url && (
            <img
              src={image_url}
              alt={recommended_model}
              style={{
                width: 120,
                height: 'auto',
                borderRadius: 6,
                objectFit: 'cover'
              }}
            />
          )}
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 700, marginBottom: 4 }}>
              {recommended_model}
            </div>
            <div style={{ color: '#555' }}>Categoria: {predicted_category}</div>
            {typeof confidence === 'number' && (
              <div style={{ color: '#777', marginTop: 2 }}>
                Confiança do modelo: {Math.round(confidence * 100)}%
              </div>
            )}
            {typeof price === 'number' && (
              <div style={{ marginTop: 4 }}>
                <b>Preço estimado (unitário):</b>{' '}
                {price.toLocaleString('pt-BR', {
                  style: 'currency',
                  currency: 'BRL'
                })}
              </div>
            )}
            <div style={{ marginTop: 4 }}>
              <b>Quantidade desejada:</b> {requested_qty || 1} unid.
            </div>
            <div style={{ marginTop: 4 }}>
              <b>Estoque total estimado:</b>{' '}
              {in_stock
                ? `${stock_qty} unid. (em estoque/produção)`
                : `${stock_qty || 0} unid. — sem disponibilidade imediata`}
            </div>
            <div style={{ marginTop: 4 }}>
              <b>Atende ao pedido?</b>{' '}
              {enough_stock
                ? 'Sim, estoque suficiente para a quantidade solicitada.'
                : 'Provavelmente será necessário programar produção adicional.'}
            </div>
            {typeof estimated_payload_kg === 'number' && (
              <div style={{ marginTop: 4 }}>
                <b>Carga útil estimada:</b> {estimated_payload_kg.toFixed(0)} kg
                {cargo_type_used && (
                  <> (considerando carga tipo "{cargo_type_used}")</>
                )}
              </div>
            )}
            {typeof density_ton_m3_used === 'number' && (
              <div style={{ marginTop: 2, fontSize: 12, color: '#555' }}>
                Densidade adotada: ~{density_ton_m3_used.toFixed(2)} t/m³
              </div>
            )}
            {legal_message && (
              <div
                style={{
                  marginTop: 6,
                  padding: 6,
                  borderRadius: 6,
                  background: legal_ok ? '#e7f9ec' : '#ffecec',
                  color: legal_ok ? '#145c2b' : '#a10000',
                  fontSize: 12
                }}
              >
                {legal_ok ? '✅ ' : '⚠️ '} {legal_message}
              </div>
            )}
          </div>
        </div>

        {alternative && (
          <div
            style={{
              marginTop: 10,
              paddingTop: 8,
              borderTop: '1px dashed #ddd'
            }}
          >
            <div style={{ fontWeight: 600, marginBottom: 4 }}>
              Segunda opção sugerida:
            </div>
            <div style={{ marginBottom: 4 }}>
              <b>{alternative.recommended_model}</b> ({alternative.category})
            </div>
            <div style={{ fontSize: 12, color: '#555', marginBottom: 4 }}>
              {alternative.reason}
            </div>
            {typeof alternative.estimated_payload_kg === 'number' && (
              <div style={{ fontSize: 12, color: '#555', marginBottom: 2 }}>
                Carga útil estimada:{' '}
                {alternative.estimated_payload_kg.toFixed(0)} kg/viagem
              </div>
            )}
            {alternative.comparison && (
              <div style={{ fontSize: 12, color: '#555' }}>
                {alternative.comparison}
              </div>
            )}
          </div>
        )}

        {technical_explanation && (
          <div
            style={{
              marginTop: 10,
              padding: 8,
              borderRadius: 6,
              background: '#f7f7ff',
              fontSize: 12,
              color: '#333'
            }}
          >
            <div style={{ fontWeight: 600, marginBottom: 4 }}>
              Resumo técnico:
            </div>
            {technical_explanation}
          </div>
        )}
      </div>
    );
  };

  // --------------------------------------------------
  // RENDER
  // --------------------------------------------------
  return (
    <div
      className="card"
      style={{
        maxWidth: '980px',
        margin: '20px auto',
        padding: 16,
        borderRadius: 10,
        border: '1px solid #ddd',
        boxShadow: '0 2px 6px rgba(0,0,0,0.05)'
      }}
    >
      {/* Cabeçalho: "login" simples */}
      <div
        style={{
          marginBottom: 12,
          display: 'flex',
          gap: 8,
          alignItems: 'center',
          flexWrap: 'wrap'
        }}
      >
        <div style={{ fontWeight: 600, marginRight: 8 }}>Dados do cliente:</div>
        <input
          type="text"
          placeholder="Nome do cliente"
          value={userName}
          onChange={(e) => setUserName(e.target.value)}
          style={{
            padding: 6,
            borderRadius: 6,
            border: '1px solid #ddd',
            minWidth: 160
          }}
        />
        <input
          type="email"
          placeholder="E-mail do cliente"
          value={userEmail}
          onChange={(e) => setUserEmail(e.target.value)}
          style={{
            padding: 6,
            borderRadius: 6,
            border: '1px solid #ddd',
            minWidth: 220
          }}
        />
        <button
          type="button"
          onClick={handleLoadHistory}
          disabled={loadingHistory || !userEmail}
          style={{
            padding: '6px 10px',
            borderRadius: 6,
            border: '1px solid #007bff',
            background: '#007bff',
            color: 'white',
            cursor: 'pointer',
            fontSize: 13
          }}
        >
          {loadingHistory ? 'Carregando...' : 'Carregar histórico'}
        </button>
        {clientHistory && (
          <span
            style={{
              fontSize: 12,
              padding: '2px 8px',
              borderRadius: 999,
              background:
                clientHistory.total_confirmed > 0 ? '#e7f9ec' : '#f0f0f0',
              color: clientHistory.total_confirmed > 0 ? '#145c2b' : '#555'
            }}
          >
            {clientHistory.total_confirmed > 0
              ? 'Cliente recorrente'
              : 'Primeiro atendimento'}
          </span>
        )}
      </div>

      {/* Abas */}
      <div
        style={{
          display: 'flex',
          gap: 8,
          marginBottom: 12,
          borderBottom: '1px solid #eee'
        }}
      >
        <button
          type="button"
          onClick={() => setActiveTab('chat')}
          style={{
            padding: '6px 12px',
            borderRadius: 8,
            border: 'none',
            background: activeTab === 'chat' ? '#007bff' : 'transparent',
            color: activeTab === 'chat' ? '#fff' : '#555',
            cursor: 'pointer'
          }}
        >
          Atendimento
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('history')}
          style={{
            padding: '6px 12px',
            borderRadius: 8,
            border: 'none',
            background: activeTab === 'history' ? '#007bff' : 'transparent',
            color: activeTab === 'history' ? '#fff' : '#555',
            cursor: 'pointer'
          }}
        >
          Últimas compras
        </button>
      </div>

      {activeTab === 'chat' ? (
        <>
          <div style={{ display: 'flex', gap: 12, alignItems: 'stretch' }}>
            {/* histórico de mensagens */}
            <div
              className="chat-history"
              style={{
                flex: 2,
                height: '420px',
                overflowY: 'auto',
                border: '1px solid #ddd',
                padding: '10px',
                borderRadius: '6px',
                marginBottom: '10px',
                background: '#fafafa'
              }}
            >
              {chatHistory.map((msg, index) => (
                <div
                  key={index}
                  style={{
                    textAlign: msg.role === 'user' ? 'right' : 'left',
                    margin: '10px 0'
                  }}
                >
                  <div
                    style={{
                      display: 'inline-block',
                      maxWidth: '85%',
                      wordWrap: 'break-word',
                      whiteSpace: 'pre-wrap',
                      background:
                        msg.role === 'user' ? '#007bff' : '#f0f0f0',
                      color: msg.role === 'user' ? 'white' : 'black',
                      padding: '8px 12px',
                      borderRadius: '15px'
                    }}
                  >
                    {msg.text}
                  </div>

                  {msg.meta && (
                    <div style={{ marginTop: 6, textAlign: 'left' }}>
                      {renderRecommendationCard(msg.meta)}
                    </div>
                  )}
                </div>
              ))}

              {loading && (
                <div style={{ textAlign: 'left', margin: '10px 0' }}>
                  <span
                    style={{
                      background: '#f0f0f0',
                      color: 'black',
                      padding: '8px 12px',
                      borderRadius: '15px'
                    }}
                  >
                    Digitando...
                  </span>
                </div>
              )}
            </div>

            {/* painel lateral */}
            <div
              style={{
                flex: 1,
                minWidth: 260,
                border: '1px solid #ddd',
                borderRadius: 6,
                padding: 10,
                background: '#ffffff',
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'space-between'
              }}
            >
              <div>
                <div
                  style={{
                    fontWeight: 600,
                    marginBottom: 8,
                    borderBottom: '1px solid #eee',
                    paddingBottom: 4
                  }}
                >
                  Resumo técnico da recomendação
                </div>
                {lastRecommendation ? (
                  renderRecommendationCard(lastRecommendation)
                ) : (
                  <div style={{ fontSize: 13, color: '#777' }}>
                    Assim que o agente recomendar uma caçamba,
                    o resumo técnico aparecerá aqui.
                  </div>
                )}

                {/* bloco de visão */}
                <div style={{ marginTop: 16 }}>
                  <div style={{ fontWeight: 600, marginBottom: 4 }}>
                    Reconhecer caminhão pela imagem
                  </div>
                  <input
                    type="file"
                    accept="image/*"
                    onChange={handleImageChange}
                    disabled={imageUploading}
                  />
                  {imageUploading && (
                    <div style={{ fontSize: 12, color: '#777', marginTop: 4 }}>
                      Processando imagem...
                    </div>
                  )}
                  {imageRecognition && (
                    <div style={{ fontSize: 12, color: '#555', marginTop: 4 }}>
                      Última imagem reconhecida como:{' '}
                      {imageRecognition.truck_model}
                    </div>
                  )}
                </div>
              </div>

              <div style={{ marginTop: 12 }}>
                <button
                  type="button"
                  onClick={handleNotifyVendor}
                  disabled={!lastRecommendation || notifyLoading}
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    borderRadius: 8,
                    border: 'none',
                    background: lastRecommendation ? '#28a745' : '#ccc',
                    color: 'white',
                    fontWeight: 600,
                    cursor: lastRecommendation ? 'pointer' : 'not-allowed'
                  }}
                >
                  {notifyLoading
                    ? 'Enviando notificação...'
                    : 'Notificar vendedor / reservar'}
                </button>
              </div>
            </div>
          </div>

          {/* input do chat */}
          <form
            onSubmit={handleSubmit}
            style={{ display: 'flex', gap: 8, marginTop: 10, alignItems: 'center' }}
          >
            <input
              type="text"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="Digite sua mensagem..."
              style={{
                flex: 1,
                padding: 10,
                borderRadius: 8,
                border: '1px solid #ddd'
              }}
              disabled={loading}
            />
            <button
              type="submit"
              disabled={loading}
              style={{
                padding: '10px 16px',
                borderRadius: 8,
                border: 'none',
                background: '#007bff',
                color: 'white',
                cursor: 'pointer'
              }}
            >
              Enviar
            </button>
          </form>
        </>
      ) : (
        // === ABA "ÚLTIMAS COMPRAS" ===
        <div
          style={{
            minHeight: 200,
            border: '1px solid #ddd',
            borderRadius: 6,
            padding: 10,
            background: '#fafafa'
          }}
        >
          <div style={{ marginBottom: 8, fontWeight: 600 }}>
            Histórico do cliente
          </div>

          {clientHistory ? (
            <div
              style={{
                marginBottom: 12,
                fontSize: 13,
                background: '#fff',
                padding: 8,
                borderRadius: 6,
                border: '1px solid #eee'
              }}
            >
              <div>
                <b>Nome:</b> {clientHistory.name || '(não informado)'}
              </div>
              <div>
                <b>E-mail:</b> {clientHistory.email}
              </div>
              <div>
                <b>Total de atendimentos:</b> {clientHistory.total_requests}
              </div>
              <div>
                <b>Reservas geradas:</b> {clientHistory.total_reservations}
              </div>
              <div>
                <b>Compras confirmadas:</b> {clientHistory.total_confirmed}
              </div>
              {clientHistory.last_truck_model && (
                <div>
                  <b>Último caminhão atendido:</b>{' '}
                  {clientHistory.last_truck_model}
                </div>
              )}
              {clientHistory.last_recommended_model && (
                <div>
                  <b>Última caçamba recomendada:</b>{' '}
                  {clientHistory.last_recommended_model}
                </div>
              )}
            </div>
          ) : (
            <div style={{ fontSize: 13, color: '#777', marginBottom: 8 }}>
              Carregue o histórico do cliente para ver o resumo de atendimentos.
            </div>
          )}

          <div style={{ fontWeight: 600, marginBottom: 4 }}>
            Últimas compras (exemplo)
          </div>
          {filteredMockPurchases.length === 0 ? (
            <div style={{ fontSize: 13, color: '#777' }}>
              Nenhuma compra simulada encontrada para o e-mail informado.
              Experimente usar: <code>cliente.exemplo@galego.com</code>
            </div>
          ) : (
            <table
              style={{
                width: '100%',
                borderCollapse: 'collapse',
                fontSize: 13,
                background: '#fff',
                borderRadius: 6,
                overflow: 'hidden'
              }}
            >
              <thead>
                <tr style={{ background: '#f0f0f0' }}>
                  <th style={{ padding: 6, borderBottom: '1px solid #ddd' }}>
                    Data
                  </th>
                  <th style={{ padding: 6, borderBottom: '1px solid #ddd' }}>
                    Caminhão
                  </th>
                  <th style={{ padding: 6, borderBottom: '1px solid #ddd' }}>
                    Eixos
                  </th>
                  <th style={{ padding: 6, borderBottom: '1px solid #ddd' }}>
                    Chassi (m)
                  </th>
                  <th style={{ padding: 6, borderBottom: '1px solid #ddd' }}>
                    Caçamba
                  </th>
                  <th style={{ padding: 6, borderBottom: '1px solid #ddd' }}>
                    Status
                  </th>
                </tr>
              </thead>
              <tbody>
                {filteredMockPurchases.map((p, idx) => (
                  <tr key={idx}>
                    <td
                      style={{
                        padding: 6,
                        borderBottom: '1px solid #f2f2f2'
                      }}
                    >
                      {p.data}
                    </td>
                    <td
                      style={{
                        padding: 6,
                        borderBottom: '1px solid #f2f2f2'
                      }}
                    >
                      {p.truck_model}
                    </td>
                    <td
                      style={{
                        padding: 6,
                        borderBottom: '1px solid #f2f2f2'
                      }}
                    >
                      {p.axle_count}
                    </td>
                    <td
                      style={{
                        padding: 6,
                        borderBottom: '1px solid #f2f2f2'
                      }}
                    >
                      {p.chassis_length_m}
                    </td>
                    <td
                      style={{
                        padding: 6,
                        borderBottom: '1px solid #f2f2f2'
                      }}
                    >
                      {p.caçamba}
                    </td>
                    <td
                      style={{
                        padding: 6,
                        borderBottom: '1px solid #f2f2f2'
                      }}
                    >
                      {p.status}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}