import React from 'react';
// import ConfigForm from './components/ConfigForm'; // Linha antiga comentada
import Chat from './components/Chat'; // <-- IMPORTE O NOVO CHAT

export default function App() {
  return (
    <div className="container">
      <header>
        <h1>GALEGO Fit</h1>
        <p>Assistente Inteligente de Caçambas</p> {/* Título atualizado */}
      </header>

      <main>
        {/* <ConfigForm /> */} {/* Formulário antigo comentado */}
        <Chat /> {/* <-- USE O NOVO CHAT */}
      </main>
    </div>
  );
}