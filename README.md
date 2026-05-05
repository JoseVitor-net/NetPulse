# NetPulse

Uma ferramenta de monitoramento de rede em tempo real com análise inteligente, histórico persistente e replay de sessões.

## Features

- Monitoramento ICMP multi-host em tempo real
- Interface gráfica com PyQt6
- Gráficos de latência em tempo real
- Sistema de alertas (latência, perda, falha de ISP)
- Análise inteligente de rede (NetworkAnalyzer)
- Persistência completa em SQLite
- Histórico de sessões de monitoramento
- Replay de sessões como se fossem tempo real
- Suporte a múltiplos hosts simultâneos

## Arquitetura

O sistema é construído sobre uma arquitetura limpa em camadas, garantindo alta performance e isolamento de responsabilidades:

- **PingManager**: Orquestra a execução em tempo real, mediando a comunicação entre a rede e a UI.
- **PingService**: Executa o ICMP em threads dedicadas (QThread), sem bloquear a interface.
- **NetworkAnalyzer**: Motor puro Python que detecta anomalias de rede (quedas, picos e correlação de falhas de ISP) através de janelas deslizantes (Event Stream).
- **Storage**: Persistência em banco de dados SQLite com gravação em batch para não causar gargalos de I/O nas execuções.
- **ReplayEngine**: Motor independente de reprodução de histórico (Event Sourcing) que simula sessões passadas de forma temporal.
- **UI (PyQt6)**: Camada passiva e focada apenas na visualização dos dados e interações do usuário.

## Como Executar

Clone o repositório, ative seu ambiente virtual (recomendado) e instale as dependências:

```bash
pip install -r requirements.txt
python main.py
```
