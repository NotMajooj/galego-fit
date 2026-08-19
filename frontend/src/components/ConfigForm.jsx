import React, { useState, useEffect } from 'react';
import axios from 'axios';

const API_URL = 'http://127.0.0.1:5000';

export default function ConfigForm() {
  const [truckModels, setTruckModels] = useState([]);
  const [selectedTruck, setSelectedTruck] = useState('');
  const [chassisLength, setChassisLength] = useState('8.5'); // Valor padrão
  const [axleCount, setAxleCount] = useState('3'); // Valor padrão
  
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);

  // Efeito para carregar os modelos de caminhão do backend
  useEffect(() => {
    const fetchTruckModels = async () => {
      try {
        // Agora buscamos a lista da nossa API!
        const response = await axios.get(`${API_URL}/api/truck_models`);
        setTruckModels(response.data);
        if (response.data.length > 0) {
          setSelectedTruck(response.data[0]);
        }
      } catch (err) {
        console.error("Erro ao buscar modelos de caminhões:", err);
        alert('Não foi possível carregar a lista de caminhões do backend.');
      }
    };
    fetchTruckModels();
  }, []);

  const handleSubmit = async (event) => {
    event.preventDefault();
    setLoading(true);
    setResult(null);

    if (!selectedTruck || !axleCount || !chassisLength) {
      alert('Por favor, preencha todos os campos.');
      setLoading(false);
      return;
    }

    try {
      const requestData = {
        truck_model: selectedTruck,
        axle_count: parseInt(axleCount),
        chassis_length_m: parseFloat(chassisLength)
      };

      const response = await axios.post(`${API_URL}/api/recommend`, requestData);
      setResult(response.data);
    } catch (err) {
      console.error(err);
      alert('Erro ao gerar recomendação: ' + (err.response?.data?.error || err.message));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="card">
      <form onSubmit={handleSubmit} className="form-grid">
        <label className="form-label">
          Modelo do caminhão
          <select 
            value={selectedTruck} 
            onChange={e => setSelectedTruck(e.target.value)}
            className="form-select"
          >
            <option value="" disabled>Selecione um modelo</option>
            {truckModels.map(model => (
              <option key={model} value={model}>{model}</option>
            ))}
          </select>
        </label>

        <label className="form-label">
          Número de eixos
          <input 
            type="number" 
            value={axleCount} 
            onChange={e => setAxleCount(e.target.value)}
            className="form-input"
          />
        </label>

        <label className="form-label">
          Comprimento do chassi (m)
          <input 
            type="number" 
            step="0.1" 
            value={chassisLength} 
            onChange={e => setChassisLength(e.target.value)}
            className="form-input"
          />
        </label>

        <div>
          <button type="submit" disabled={loading} className="form-button">
            {loading ? 'Calculando...' : 'Gerar Recomendação'}
          </button>
        </div>
      </form>

      {result && (
        <div className="card result-box">
          <h3>Recomendação Inteligente</h3>
          <p><strong>Categoria prevista:</strong> {result.predicted_category}</p>
          <p><strong>Sugestão de modelo:</strong> {result.recommended_model}</p>
        </div>
      )}
    </div>
  );
}