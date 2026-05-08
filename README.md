# NetPulse

Uma ferramenta de desktop leve para monitoramento de rede multi-host, análise heurística e visualização em tempo real baseada em Python e PyQt6.

## Funcionalidades Atuais Confirmadas
- ✅ **Ping Simultâneo:** Monitoramento não-bloqueante de N hosts via lib `ping3` (ICMP nativo).
- ✅ **Dashboard de Alta Performance:** Renderização O(1) fluida usando `pyqtgraph`.
- ✅ **Inteligência Passiva:** `NetworkAnalyzer` preditivo capaz de apontar quebra no seu ISP baseando-se em correlação entre falhas de rotas distintas.
- ✅ **Zero I/O Lag:** Backups das sessões enviados ao SQLite utilizando cache in-memory e descarregamento via Batch Queries.
- ✅ **Time-Machine (Replay):** Capacidade inovadora de rever sessões antigas desenhadas progressivamente na sua tela.

## Roadmap Planejado
- ⏳ Integração Nmap para visualização de portas.
- ⏳ Exportação da Session via API.
- ⏳ Integração com Modelos de Linguagem para emitir sumários falados de rede.

## Instalação e Execução

### Requisitos
- Windows / Linux
- Python 3.11+ (Recomendado privilégios de Admin no Windows para sockets ICMP brutos).

### Passos:
1. Clone o projeto e entre no diretório.
```bash
git clone https://github.com/SEU_USUARIO/NetPulse.git
cd NetPulse
```

2. Crie e ative um ambiente virtual:
```bash
python -m venv .venv
# No Windows:
.venv\Scripts\activate
```

3. Instale os requerimentos rigorosos:
```bash
pip install -r requirements.txt
```

4. Execute:
```bash
python main.py
```

## Limitações Conhecidas
Para que a ferramenta seja capaz de emitir pacotes ICMP brutos no Windows usando a biblioteca `ping3`, ela **requer execução do terminal como Administrador**. A falha de privilégio pode acarretar em permissões negadas em tempo de runtime.
